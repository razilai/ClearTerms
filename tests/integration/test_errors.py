"""Integration tests: domain-exception to HTTP-response mapping."""


import httpx

# --- error mapping ---
#
# Each test builds a throwaway probe app rather than registering routes on the
# shared app.main.app singleton — routes added to the real app are never
# removed and would leak into every later test in the session.


async def _probe_app_response(exc: Exception) -> httpx.Response:
    """Raise `exc` from a route on a throwaway app wired with the real handlers."""
    from fastapi import FastAPI

    from app.api.errors import register_exception_handlers

    probe = FastAPI()
    register_exception_handlers(probe)

    @probe.get("/boom")
    async def boom() -> None:
        raise exc

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get("/boom")


async def test_queue_full_maps_to_503() -> None:
    from app.services.exceptions import QueueFullError

    resp = await _probe_app_response(QueueFullError())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Analysis queue is full, try again shortly"
    assert resp.headers["Retry-After"] == "30"


async def test_queue_shutdown_maps_to_503() -> None:
    from app.services.exceptions import QueueShutdownError

    resp = await _probe_app_response(QueueShutdownError())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Analysis is shutting down, try again shortly"
    assert resp.headers["Retry-After"] == "30"


async def test_queue_timeout_maps_to_504() -> None:
    from app.services.exceptions import QueueTimeoutError

    resp = await _probe_app_response(QueueTimeoutError())
    assert resp.status_code == 504
    assert (
        resp.json()["detail"]
        == "Analysis is taking longer than expected, try again shortly"
    )
