"""Bounded priority queue for TOS analysis.

Two jobs, deliberately separated:

* a **concurrency limit** — only ``analysis_workers`` analyses run at once, so
  a burst of requests cannot swamp Ollama;
* **fairness** — when a slot frees, the waiting job whose user has the fewest
  jobs in flight goes next, so one user submitting twenty documents cannot make
  everyone else wait behind all twenty.

The queue owns the database session a job runs on. Callers must not close over
their request-scoped session: a job can sit here for a long time, and a request
session is both committed/closed at request end and holding a database
connection (and, mid-transaction, locks) the whole time it waits.

Cache hits never reach this module — see app.services.analysis.
"""

import asyncio
import itertools
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.services.exceptions import (
    QueueFullError,
    QueueShutdownError,
    QueueTimeoutError,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)

# What the queue runs: give it a session, get a result. Anything analysis- or
# document-specific is bound into the callable by the caller, so this module
# never imports app.services.analysis (which imports this one).
Job = Callable[[AsyncSession], Awaitable[T]]

# One queued item: (priority, sequence, user_id, job, the caller's future).
# Spelled out rather than left bare so the worker loop's 5-tuple unpack is
# actually checked — that unpack is the one place a shape mismatch would be a
# runtime crash. Any, not T: entries of different result types share one queue.
QueueEntry = tuple[int, int, int, Job[Any], "asyncio.Future[Any]"]


class AnalysisQueue:
    """In-process priority queue drained by a fixed pool of worker tasks.

    Started and stopped from the app lifespan hook (app.main).
    """

    def __init__(self) -> None:
        # Built in start(): asyncio primitives must be created on the running
        # loop, and this object is instantiated at import time.
        self._queue: asyncio.PriorityQueue[QueueEntry] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        # Only so submit() can tell "never started" from "already stopped" —
        # both leave _queue None, but they are different bugs to chase.
        self._ever_started = False
        # Monotonic tie-breaker. PriorityQueue compares tuples element by
        # element, so two entries with equal priority would go on to compare the
        # job callables themselves and raise TypeError. It also makes ordering
        # FIFO within a priority level.
        self._sequence = itertools.count()
        # In-flight jobs per user (queued + running); the priority policy.
        self._pending: defaultdict[int, int] = defaultdict(int)
        self._timeout: float = settings.analysis_queue_timeout_seconds

    async def start(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        workers: int | None = None,
        maxsize: int | None = None,
        timeout: float | None = None,
    ) -> None:
        """Spawn the worker pool.

        Safe to call again without an intervening stop(): a second call would
        otherwise reassign self._queue/self._workers out from under the
        already-running pool, leaking those tasks (they keep running, bound to
        the old queue, but nothing can ever cancel or await them again).
        """
        if self._workers:
            await self.stop()
        self._session_factory = session_factory
        self._queue = asyncio.PriorityQueue(
            maxsize=settings.analysis_queue_maxsize if maxsize is None else maxsize
        )
        self._timeout = (
            settings.analysis_queue_timeout_seconds if timeout is None else timeout
        )
        count = settings.analysis_workers if workers is None else workers
        self._ever_started = True
        self._workers = [
            asyncio.create_task(self._worker(), name=f"analysis-worker-{i}")
            for i in range(count)
        ]
        logger.info("analysis queue started with %d worker(s)", count)

    async def stop(self) -> None:
        """Cancel the worker pool, then fail everything still queued.

        Leaving the queue object alive would accept work nobody can run: a
        later submit() would pass the ``is None`` guard, park on a Future no
        worker services, and sit there for the whole caller timeout; and the
        entries already queued would simply be dropped by the next start(),
        their callers parked forever and their _pending counts never released.
        """
        for worker in self._workers:
            worker.cancel()
        # return_exceptions so one worker's CancelledError does not mask the
        # others' shutdown.
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

        dropped = 0
        if self._queue is not None:
            # Per-entry bookkeeping for work that will never run. Note this
            # releases the counts these entries added; _pending as a whole is
            # deliberately NOT reset, so it stays real accounting (a leftover
            # count after a clean stop is a genuine leak, and tests assert it).
            #
            # A job a worker had already dequeued is not here: that worker's
            # own except/finally resolved its Future and released its count
            # before the gather above returned. So every entry is settled
            # exactly once, by exactly one of the two paths.
            while True:
                try:
                    _priority, _seq, user_id, _job, future = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._release(user_id)
                if not future.done():
                    # Expect asyncio to log "QueueShutdownError exception in
                    # shielded future" at ERROR for any entry whose caller
                    # already timed out and walked away (submit shields the
                    # future, and since 3.12 shield reports exceptions set on
                    # one nobody is waiting on). Noisy but accurate, and the
                    # alternative — future.cancel() — is the defect this
                    # replaced. The count logged below is what makes those
                    # lines interpretable.
                    future.set_exception(QueueShutdownError())
                dropped += 1
                self._queue.task_done()
        # Dropped last, and only after the drain: a submit racing this shutdown
        # then hits the guard in submit() and fails fast instead of enqueueing
        # onto a queue that nothing will ever drain again.
        self._queue = None
        if dropped:
            logger.warning(
                "analysis queue stopped, dropping %d queued job(s); "
                "their callers get QueueShutdownError",
                dropped,
            )
        else:
            logger.info("analysis queue stopped")

    async def submit(self, user_id: int, job: Job[T]) -> T:
        """Enqueue ``job`` for ``user_id`` and await its result.

        The caller parks on a Future until a worker runs the job. Raises
        whatever the job raises, or QueueFullError / QueueTimeoutError /
        QueueShutdownError — the last if the queue stops while it waits.
        """
        if self._queue is None:
            raise RuntimeError(
                "AnalysisQueue has been stopped"
                if self._ever_started
                else "AnalysisQueue.start() was never called"
            )

        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        entry = (self._priority_for(user_id), next(self._sequence), user_id, job, future)
        try:
            # Non-blocking: a caller that cannot even get a queue slot is shed
            # immediately rather than made to wait for the right to wait.
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            raise QueueFullError() from None
        # Only counted once the job is actually queued: a rejected submission
        # never reaches the worker's finally, so counting it here would leak
        # _pending upward forever and permanently deprioritise this user.
        self._pending[user_id] += 1

        try:
            return await asyncio.wait_for(asyncio.shield(future), self._timeout)
        except TimeoutError:
            # shield keeps the job alive: it stays queued, runs, and populates
            # the analysis cache even though this caller stopped waiting. The
            # next request for the same document is then a cache hit.
            raise QueueTimeoutError() from None

    def _priority_for(self, user_id: int) -> int:
        """Lower runs sooner: a user's Nth in-flight job sits at priority N.

        So every user's first job outranks every user's second, and a burst from
        one user cannot make everyone else wait behind all of it.

        Nothing starves — but not because a user holds only one entry per
        level; they can hold several. With one worker: A submits j1 (count 0
        -> priority 0), the worker takes j1 but the count stays 1, so A's j2
        goes in at priority 1; j1 finishes and releases, so A's j3 *also* goes
        in at priority 1. Two entries of A's at the same level, repeatable per
        completed job.

        The real argument is sequence ordering at the top level. Priority 0
        requires _pending == 0, so a user never has more than one *queued*
        priority-0 entry at a time, and the monotonic _sequence tie-break keeps
        earlier priority-0 arrivals ahead of later ones. A priority-0 entry
        therefore waits behind a fixed, only-shrinking set — the priority-0
        entries that were already queued when it arrived, at most one per other
        user — and nothing enqueued afterwards can overtake it. Every user's
        first job is served after a bounded wait, so no aging term is needed.

        Uses .get() rather than the subscript: this runs before put_nowait, so
        a rejected submission (QueueFullError) never reaches the increment or
        the worker's finally/_release — a subscript read would insert a
        stray zero-valued key here that nothing ever cleans up.
        """
        return self._pending.get(user_id, 0)

    def _release(self, user_id: int) -> None:
        """Undo one submit()'s pending-count increment for ``user_id``."""
        self._pending[user_id] -= 1
        if self._pending[user_id] <= 0:
            del self._pending[user_id]

    async def _worker(self) -> None:
        assert self._queue is not None and self._session_factory is not None
        while True:
            _priority, _seq, user_id, job, future = await self._queue.get()
            try:
                async with self._session_factory() as session:
                    result = await job(session)
                    # The queue owns this session, so it owns the transaction
                    # boundary too (unlike request sessions, where the request
                    # commits — see app.db.engine.get_session).
                    await session.commit()
                if not future.done():
                    future.set_result(result)
            except asyncio.CancelledError:
                # Shutdown. Wake the caller rather than leaving it parked
                # forever — but with an exception, not future.cancel():
                # cancellation passes through the caller's shield into its
                # wait_for and re-raises as CancelledError inside a request
                # task that was never itself cancelled. That marks the request
                # cancelled, so Starlette drops the connection with no response
                # at all, and get_session's `except Exception` does not even
                # roll back (CancelledError is a BaseException). A domain error
                # gets the caller a real 503 instead.
                if not future.done():
                    future.set_exception(QueueShutdownError())
                raise
            except Exception as exc:
                logger.exception("analysis job failed for user %s", user_id)
                if not future.done():
                    future.set_exception(exc)
            finally:
                self._release(user_id)
                self._queue.task_done()


queue = AnalysisQueue()
