"""Unit tests: the analysis queue and its pipeline wiring."""


import asyncio
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models import Document, User
from app.services.exceptions import (
    QueueFullError,
    QueueShutdownError,
    QueueTimeoutError,
)
from app.services.queue import AnalysisQueue

# --- analysis queue ----------------------------------------------------------
#
# The `session` fixture binds every session to one shared connection, which
# would hide the cross-session behaviour under test here. These use
# `file_session_factory` (a throwaway Postgres database, one independent
# connection per session) so the worker's session is genuinely independent of
# the caller's.


async def test_submit_runs_the_job_and_returns_its_result(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def job(session: AsyncSession) -> str:
            return "done"

        assert await q.submit(user_id=1, job=job) == "done"
    finally:
        await q.stop()


async def test_worker_gives_the_job_a_live_session_the_caller_does_not_own(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The job's session must be usable and must not be the caller's."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:
        async with file_session_factory() as caller_session:

            async def job(session: AsyncSession) -> bool:
                # Usable: a real query runs against it.
                await session.execute(select(User))
                return session is not caller_session

            assert await q.submit(user_id=1, job=job) is True
    finally:
        await q.stop()


async def test_worker_commits_the_job_session(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Writes a job makes are durable without the caller committing anything."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def job(session: AsyncSession) -> None:
            session.add(User(email="queued@example.com", password_hash="x"))

        await q.submit(user_id=1, job=job)
    finally:
        await q.stop()

    async with file_session_factory() as verify:
        found = await verify.execute(
            select(User).where(User.email == "queued@example.com")
        )
        assert found.scalar_one_or_none() is not None


async def test_job_exception_propagates_to_the_caller(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def job(session: AsyncSession) -> None:
            raise ValueError("job blew up")

        with pytest.raises(ValueError, match="job blew up"):
            await q.submit(user_id=1, job=job)

        # The worker survives a failed job and keeps serving.
        async def ok(session: AsyncSession) -> str:
            return "still alive"

        assert await q.submit(user_id=1, job=ok) == "still alive"
    finally:
        await q.stop()


async def test_single_worker_runs_one_job_at_a_time(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    running = 0
    peak = 0
    try:

        async def job(session: AsyncSession) -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1

        await asyncio.gather(*(q.submit(user_id=i, job=job) for i in range(5)))
    finally:
        await q.stop()

    assert peak == 1


async def test_two_workers_run_two_jobs_at_a_time(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=2)
    running = 0
    peak = 0
    try:

        async def job(session: AsyncSession) -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1

        await asyncio.gather(*(q.submit(user_id=i, job=job) for i in range(6)))
    finally:
        await q.stop()

    assert peak == 2


async def test_jobs_from_one_user_run_in_submission_order(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Same user, same priority -> FIFO. Proves the tie-break is stable."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    order: list[int] = []
    try:

        def make(n: int) -> Callable[[AsyncSession], Awaitable[None]]:
            async def job(session: AsyncSession) -> None:
                order.append(n)

            return job

        await asyncio.gather(*(q.submit(user_id=7, job=make(n)) for n in range(5)))
    finally:
        await q.stop()

    assert order == [0, 1, 2, 3, 4]


async def test_stop_cancels_workers(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=2)
    # Captured before stop() empties the list: asserting only `_workers == []`
    # restates stop()'s own assignment, so it would pass no matter what stop()
    # did to the tasks. The claim in the name is that they were cancelled.
    workers = list(q._workers)
    await q.stop()
    assert q._workers == []
    assert workers and all(worker.cancelled() for worker in workers)


async def test_stop_fails_waiting_callers_instead_of_abandoning_them(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Shutdown settles everyone: the job mid-run and the one still queued.

    Both used to be abandoned — the running one's future was cancelled (which
    reaches the caller as CancelledError, i.e. a dropped connection rather than
    a response), and the queued one was left untouched on a queue the next
    start() replaces, so its caller parked until its own timeout for nothing.

    timeout=2.0 rather than the 300s default purely so this fails fast instead
    of hanging if the shutdown path regresses; nothing here needs 2s.
    """
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=2.0)
    release = asyncio.Event()

    async def blocker(session: AsyncSession) -> None:
        await release.wait()

    async def never_runs(session: AsyncSession) -> None:
        raise AssertionError("a queued job must not run after stop()")

    # Staggered, as in the sibling tests: the first submission has to reach the
    # worker so the second genuinely sits in the queue rather than in a worker.
    running = asyncio.create_task(q.submit(user_id=1, job=blocker))
    await asyncio.sleep(0.05)
    queued = asyncio.create_task(q.submit(user_id=2, job=never_runs))
    await asyncio.sleep(0.05)

    await q.stop()

    with pytest.raises(QueueShutdownError):
        await queued
    with pytest.raises(QueueShutdownError):
        await running
    # The drain releases the queued entry's count, the worker's finally the
    # running one's; neither may be left behind.
    assert q._pending == {}


async def test_submit_after_stop_is_rejected_rather_than_parked(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stopped queue must not accept work no worker will ever take.

    The message distinguishes this from the never-started case: both leave
    _queue None, but they are different bugs to go looking for.
    """
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=1.0)
    await q.stop()

    async def job(session: AsyncSession) -> None:
        return None

    with pytest.raises(RuntimeError, match="stopped"):
        await q.submit(user_id=1, job=job)


async def test_submit_before_start_says_start_was_never_called() -> None:
    q = AnalysisQueue()

    async def job(session: AsyncSession) -> None:
        return None

    with pytest.raises(RuntimeError, match=r"start\(\) was never called"):
        await q.submit(user_id=1, job=job)


async def test_submit_raises_when_the_queue_is_full(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, maxsize=1)
    release = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # One job occupies the worker, one fills the single queue slot. The
        # two submissions are staggered with an intervening await: creating
        # both back-to-back schedules them in the same event-loop tick, and
        # the worker's wakeup (queued via the first put_nowait) is itself
        # deferred to the *next* tick — so an unstaggered second submission
        # can race the worker for the one slot and get rejected instead of
        # the third.
        first = asyncio.create_task(q.submit(user_id=1, job=blocker))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(q.submit(user_id=2, job=blocker))
        await asyncio.sleep(0.05)

        with pytest.raises(QueueFullError):
            await q.submit(user_id=3, job=blocker)

        release.set()
        await asyncio.gather(first, second)
    finally:
        release.set()
        await q.stop()


async def test_submit_raises_when_the_wait_exceeds_the_timeout(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=0.05)
    release = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        first = asyncio.create_task(q.submit(user_id=1, job=blocker))
        await asyncio.sleep(0.01)

        async def quick(session: AsyncSession) -> str:
            return "never seen"

        with pytest.raises(QueueTimeoutError):
            await q.submit(user_id=2, job=quick)

        release.set()
        # first's own caller-side wait times out too: it has been waiting
        # since before the initial sleep, so its 0.05s deadline elapses
        # before the second submission's later deadline does — the timeout
        # applies uniformly to every caller, not just ones still queued.
        with pytest.raises(QueueTimeoutError):
            await first
    finally:
        release.set()
        await q.stop()


async def test_timed_out_job_still_runs_and_still_caches(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Giving up on the wait must not throw away the work already queued."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=0.05)
    release = asyncio.Event()
    ran = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        async def later(session: AsyncSession) -> None:
            ran.set()

        first = asyncio.create_task(q.submit(user_id=1, job=blocker))
        await asyncio.sleep(0.01)

        with pytest.raises(QueueTimeoutError):
            await q.submit(user_id=2, job=later)

        release.set()
        # first's own caller-side wait times out too, same reasoning as
        # above — its deadline elapses before release.set() is even called.
        # The job itself (blocker) keeps running regardless (shielded); it
        # is the later job's persistence past its own caller's timeout that
        # this test is really about.
        with pytest.raises(QueueTimeoutError):
            await first
        await asyncio.wait_for(ran.wait(), timeout=1.0)
    finally:
        release.set()
        await q.stop()


async def test_submit_returns_the_result_when_it_finishes_within_the_timeout(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The normal path: a caller waits under wait_for/shield and gets the
    job's actual return value back, not a timeout.

    timeout=1.0 vs. a ~0.02s job is a ~50x margin — comfortably deterministic
    on any machine this suite runs on, rather than tuned close to the edge
    the way the two timeout tests above deliberately are.
    """
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=1.0)
    try:

        async def job(session: AsyncSession) -> str:
            await asyncio.sleep(0.02)
            return "the real result"

        assert await q.submit(user_id=1, job=job) == "the real result"
    finally:
        await q.stop()


async def test_a_new_users_first_job_beats_a_busy_users_backlog(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    order: list[str] = []
    release = asyncio.Event()
    try:

        def make(label: str) -> Callable[[AsyncSession], Awaitable[None]]:
            async def job(session: AsyncSession) -> None:
                order.append(label)

            return job

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # Occupy the single worker so everything else genuinely queues up.
        held = asyncio.create_task(q.submit(user_id=99, job=blocker))
        await asyncio.sleep(0.05)

        # Alice piles up four documents, then Bob submits one.
        alice = [
            asyncio.create_task(q.submit(user_id=1, job=make(f"alice{n}")))
            for n in range(4)
        ]
        await asyncio.sleep(0.05)
        bob = asyncio.create_task(q.submit(user_id=2, job=make("bob0")))
        await asyncio.sleep(0.05)

        release.set()
        await asyncio.gather(held, bob, *alice)
    finally:
        release.set()
        await q.stop()

    # Scores, with alpha = 10 and the blocker taking sequence 0:
    #   alice0  priority 0, seq 1 ->  1
    #   alice1  priority 1, seq 2 -> 12
    #   alice2  priority 2, seq 3 -> 23
    #   alice3  priority 3, seq 4 -> 34
    #   bob0    priority 0, seq 5 ->  5
    # Alice's first was already queued at priority 0 before Bob arrived, so it
    # keeps its place; Bob's single job then beats alice1..alice3. Bob is well
    # inside the alpha-arrival window, so ageing does not come into it here —
    # test_ageing_bounds_how_often_a_later_job_is_overtaken covers that.
    assert order[0] == "alice0"
    assert order[1] == "bob0"
    assert order[2:] == ["alice1", "alice2", "alice3"]


async def test_ageing_bounds_how_often_a_later_job_is_overtaken(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A priority-p job yields to at most p*alpha newcomers, then wins forever.

    Without the sequence term in the score this would starve: every newcomer
    arrives at priority 0 and would overtake a priority-1 job indefinitely.
    """
    alpha = settings.analysis_queue_alpha
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    order: list[str] = []
    release = asyncio.Event()
    try:

        def make(label: str) -> Callable[[AsyncSession], Awaitable[None]]:
            async def job(session: AsyncSession) -> None:
                order.append(label)

            return job

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # Occupy the single worker (sequence 0) so everything else queues.
        held = asyncio.create_task(q.submit(user_id=99, job=blocker))
        await asyncio.sleep(0.05)

        # Alice: first job scores 0*alpha + 1 = 1, second 1*alpha + 2.
        alice = [
            asyncio.create_task(q.submit(user_id=1, job=make(f"alice{n}")))
            for n in range(2)
        ]
        await asyncio.sleep(0.05)

        # Enough fresh users to run past the bound. Each is a first job, so it
        # scores exactly its own sequence number.
        newcomers = [
            asyncio.create_task(q.submit(user_id=100 + n, job=make(f"new{n}")))
            for n in range(alpha + 2)
        ]
        await asyncio.sleep(0.05)

        release.set()
        await asyncio.gather(held, *alice, *newcomers)
    finally:
        release.set()
        await q.stop()

    assert order[0] == "alice0"
    # alice1 scores alpha + 2; newcomers score their sequence, 3 upward, so
    # exactly those with sequence < alpha + 2 get in front — alpha - 1 of them.
    overtaking = order[1 : order.index("alice1")]
    assert len(overtaking) == alpha - 1
    assert all(label.startswith("new") for label in overtaking)
    # The rest lose, which is the property that makes starvation impossible:
    # arrivals past the bound can never overtake, however many of them there are.
    assert order[order.index("alice1") + 1 :] == [
        f"new{n}" for n in range(alpha - 1, alpha + 2)
    ]


async def test_pending_counter_returns_to_zero_after_jobs_finish(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A leaked counter would permanently deprioritise the user."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def ok(session: AsyncSession) -> None:
            return None

        async def boom(session: AsyncSession) -> None:
            raise ValueError("nope")

        await q.submit(user_id=5, job=ok)
        with pytest.raises(ValueError):
            await q.submit(user_id=5, job=boom)
    finally:
        await q.stop()

    assert q._pending == {}


async def test_rejected_submission_does_not_leak_the_pending_counter(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A QueueFullError never reaches a worker, so it must not have counted."""
    q = AnalysisQueue()
    # maxsize=1, not 0 — asyncio.Queue treats maxsize=0 as *unbounded*.
    await q.start(file_session_factory, workers=1, maxsize=1)
    release = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # Staggered with an intervening await, matching
        # test_submit_raises_when_the_queue_is_full above: creating both
        # back-to-back schedules them in the same event-loop tick, and the
        # worker's wakeup (queued via the first put_nowait) is itself
        # deferred to the *next* tick — so an unstaggered second submission
        # can race the worker for the one slot and get rejected instead of
        # the third.
        first = asyncio.create_task(q.submit(user_id=5, job=blocker))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(q.submit(user_id=5, job=blocker))
        await asyncio.sleep(0.05)

        with pytest.raises(QueueFullError):
            await q.submit(user_id=5, job=blocker)

        release.set()
        await asyncio.gather(first, second)
    finally:
        release.set()
        await q.stop()

    assert q._pending == {}


async def test_a_fresh_users_rejected_submission_leaves_no_stray_key(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The case the other two leak detectors miss.

    test_pending_counter_returns_to_zero_after_jobs_finish never rejects a
    submission at all, and test_rejected_submission_does_not_leak_the_pending_counter
    always rejects a user who already has in-flight entries, so
    ``self._pending[user_id]`` inside _priority_for hits an existing key
    either way. Here user 3 has never submitted anything: if _priority_for
    reads ``self._pending[user_id]`` (a defaultdict subscript) instead of
    ``.get(user_id, 0)``, that read alone inserts a stray ``{3: 0}`` before
    put_nowait ever runs — and since put_nowait then rejects the submission,
    neither the increment nor the worker's finally/_release ever runs to
    clean it up.
    """
    q = AnalysisQueue()
    # maxsize=1, not 0 — asyncio.Queue treats maxsize=0 as *unbounded*.
    await q.start(file_session_factory, workers=1, maxsize=1)
    release = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # Staggered as in the sibling tests above: user 1 occupies the
        # worker, user 2 fills the single queue slot, each given its own
        # tick so the rejection below fires because the queue is genuinely
        # full rather than by a scheduling accident.
        first = asyncio.create_task(q.submit(user_id=1, job=blocker))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(q.submit(user_id=2, job=blocker))
        await asyncio.sleep(0.05)

        # User 3 has no prior or concurrent submission of their own.
        with pytest.raises(QueueFullError):
            await q.submit(user_id=3, job=blocker)

        release.set()
        await asyncio.gather(first, second)
    finally:
        release.set()
        await q.stop()

    assert q._pending == {}


# --- analysis pipeline: queue wiring ----------------------------------------
#
# Document get-or-create is not tested here: analyze_document_job calls
# documents_repo.create directly, whose ON CONFLICT DO NOTHING + re-read is
# covered by test_create_document_duplicate_hash_returns_existing above.


async def test_analyze_issues_no_write_before_submitting(
    file_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller must have issued no write by the time it parks on the queue.

    Holding an *uncommitted write* across the wait is the defect this task
    removes: on SQLite that is the global write lock, on Postgres a row lock on
    documents.text_hash plus a pooled connection held for the whole wait.

    Deliberately NOT asserted via `session.in_transaction()`: SQLAlchemy
    autobegins a transaction on the first SELECT, so that flag is True after a
    harmless read and would be testing the wrong thing.
    """
    from sqlalchemy import event

    from app.services import analysis as analysis_service
    from app.services.queue import AnalysisQueue

    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    statements: list[str] = []
    writes_at_submit: list[str] = []
    submitted = False

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = file_session_factory.kw["bind"]
    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        async with file_session_factory() as caller:
            user = User(email="probe@example.com", password_hash="x")
            caller.add(user)
            await caller.commit()
            statements.clear()  # fixture setup is not under test

            class SpyQueue:
                async def submit(self, user_id: int, job: object) -> object:
                    nonlocal submitted
                    submitted = True
                    writes_at_submit.extend(
                        s
                        for s in statements
                        if s.lstrip()
                        .upper()
                        .startswith(("INSERT", "UPDATE", "DELETE"))
                    )
                    return await q.submit(user_id, job)  # type: ignore[arg-type]

            # monkeypatch (not raw assignment) so the module singleton is
            # restored at teardown; a leaked patch would point every later test
            # at this dead queue.
            monkeypatch.setattr(analysis_service, "queue", SpyQueue())
            await analysis_service.analyze(
                caller, user.id, "Some terms of service text.", None
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)
        await q.stop()

    # First: the assertion below is only meaningful if analyze went through the
    # queue at all. writes_at_submit is populated inside SpyQueue.submit, so a
    # refactor that stopped submitting would satisfy `== []` trivially and
    # leave the invariant this test exists for unguarded.
    assert submitted, "analyze did not submit to the queue"
    assert writes_at_submit == []


async def test_concurrent_jobs_for_the_same_text_share_one_document(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The get-or-create race: both jobs must land on one document row.

    Tested at the service layer, not over HTTP: the `client` fixture overrides
    `get_session` so every request in a test shares ONE AsyncSession, and
    AsyncSession is not safe for concurrent use by multiple tasks. Two
    concurrent HTTP requests would exercise an unsupported configuration rather
    than the race. Here each job gets a genuinely independent session, which is
    what production does.
    """
    from app.services.analysis import analyze_document_job

    async def run_job() -> int:
        async with file_session_factory() as session:
            document_id = await analyze_document_job(
                session,
                text_hash="race-hash",
                url=None,
                normalized_text="identical terms of service text.",
                original_text="Identical terms of service text.",
            )
            await session.commit()
            return document_id

    first, second = await asyncio.gather(run_job(), run_job())
    assert first == second

    async with file_session_factory() as verify:
        rows = await verify.execute(
            select(Document).where(Document.text_hash == "race-hash")
        )
        assert len(rows.scalars().all()) == 1
