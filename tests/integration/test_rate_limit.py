"""Integration tests: login and analyze rate limiting (routes wired)."""


import httpx
import pytest

from app.core.config import settings
from app.services import auth
from app.services import rate_limit as rate_limit_service
from tests.conftest import signup_headers
from tests.integration.factories import ANALYZE_BODY

# --- rate limiting ---
#
# On `committing_client`, so each request gets its own committing session and the
# limiter's independent counter session (patched onto the shared per-test
# connection) is visible across requests — the shared-session `client` fixture
# would keep everything in one uncommitted transaction. The transaction-boundary
# property (a failed request still counts) is proven at the service tier in
# unit/test_rate_limit.py; here we prove the routes are wired and return 429 +
# Retry-After.


async def test_login_is_rate_limited_per_ip(
    committing_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_login_max", 3)
    await signup_headers(committing_client, "rl@example.com", "s3cretpass")
    creds = {"username": "rl@example.com", "password": "s3cretpass"}

    for _ in range(3):
        ok = await committing_client.post("/auth/login", data=creds)
        assert ok.status_code == 200, ok.text

    limited = await committing_client.post("/auth/login", data=creds)
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


async def test_analyze_is_rate_limited_per_user(
    committing_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_analyze_max", 2)
    headers = await signup_headers(committing_client, "rlu@example.com", "s3cretpass")
    user_id = auth.decode_access_token(headers["Authorization"].removeprefix("Bearer "))

    # Fill this user's analyze window to the limit directly — the same limiter the
    # route uses, so buckets match — without invoking the (slow) agent.
    for _ in range(2):
        await rate_limit_service.enforce(
            "analyze",
            str(user_id),
            settings.rate_limit_analyze_max,
            settings.rate_limit_analyze_window_seconds,
        )

    # The next /analyze trips the limiter in the dependency, before the agent runs.
    limited = await committing_client.post(
        "/analyze", json=ANALYZE_BODY, headers=headers
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers
