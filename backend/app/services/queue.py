"""Priority queue for TOS analysis (guardrail).

Prevents a single user from spamming analysis requests; cache hits skip the
queue entirely so repeat requests are free.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class AnalysisQueue:
    """In-process priority queue; a worker task drains jobs on the event loop.

    Priority derives from per-user pending counts so one user can't starve
    others. Started/stopped from the app lifespan hook.
    """

    async def start(self) -> None:
        """Spawn the worker task."""
        # TODO: implement (pass so the lifespan hook can boot before phase 6)

    async def stop(self) -> None:
        """Drain and cancel the worker task."""
        # TODO: implement

    async def submit(self, user_id: int, job: Callable[[], Awaitable[T]]) -> T:
        """Enqueue an analysis job for user_id and await its result.

        MVP: run the job inline. The per-user priority scheduling this class is
        meant to provide is a later phase; the seam (callers submit a job and
        await the result) is in place so wiring it up later needs no changes at
        the call sites.
        """
        return await job()


queue = AnalysisQueue()
