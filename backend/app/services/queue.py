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
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings

T = TypeVar("T")

logger = logging.getLogger(__name__)

# What the queue runs: give it a session, get a result. Anything analysis- or
# document-specific is bound into the callable by the caller, so this module
# never imports app.services.analysis (which imports this one).
Job = Callable[[AsyncSession], Awaitable[T]]


class AnalysisQueue:
    """In-process priority queue drained by a fixed pool of worker tasks.

    Started and stopped from the app lifespan hook (app.main).
    """

    def __init__(self) -> None:
        # Built in start(): asyncio primitives must be created on the running
        # loop, and this object is instantiated at import time.
        self._queue: asyncio.PriorityQueue | None = None
        self._workers: list[asyncio.Task] = []
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        # Monotonic tie-breaker. PriorityQueue compares tuples element by
        # element, so two entries with equal priority would go on to compare the
        # job callables themselves and raise TypeError. It also makes ordering
        # FIFO within a priority level.
        self._sequence = itertools.count()
        # In-flight jobs per user (queued + running); the priority policy.
        self._pending: defaultdict[int, int] = defaultdict(int)

    async def start(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        workers: int | None = None,
        maxsize: int | None = None,
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
        count = settings.analysis_workers if workers is None else workers
        self._workers = [
            asyncio.create_task(self._worker(), name=f"analysis-worker-{i}")
            for i in range(count)
        ]
        logger.info("analysis queue started with %d worker(s)", count)

    async def stop(self) -> None:
        """Cancel the worker pool and wait for the tasks to finish unwinding."""
        for worker in self._workers:
            worker.cancel()
        # return_exceptions so one worker's CancelledError does not mask the
        # others' shutdown.
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        logger.info("analysis queue stopped")

    async def submit(self, user_id: int, job: Job[T]) -> T:
        """Enqueue ``job`` for ``user_id`` and await its result.

        The caller parks on a Future until a worker runs the job. Raises
        whatever the job raises.
        """
        if self._queue is None:
            raise RuntimeError("AnalysisQueue.start() was never called")

        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._pending[user_id] += 1
        entry = (self._priority_for(user_id), next(self._sequence), user_id, job, future)
        try:
            # maxsize is finite (Task 3's backpressure), so put() genuinely
            # blocks; a caller cancelled while waiting here would otherwise
            # leave _pending incremented forever — nothing enqueued a job for
            # the _worker's finally block to ever decrement it.
            await self._queue.put(entry)
        except BaseException:
            self._release(user_id)
            raise
        return await future

    def _priority_for(self, user_id: int) -> int:
        """Lower runs sooner. Placeholder until Task 4 — see that task."""
        return 0

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
                # Shutdown. Wake the caller rather than leaving it parked forever.
                if not future.done():
                    future.cancel()
                raise
            except Exception as exc:
                logger.exception("analysis job failed for user %s", user_id)
                if not future.done():
                    future.set_exception(exc)
            finally:
                self._release(user_id)
                self._queue.task_done()


queue = AnalysisQueue()
