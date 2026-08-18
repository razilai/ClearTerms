"""Integration tests: analyze + history + preferences pipeline."""


import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repos import documents as documents_repo
from app.models import Analysis
from tests.conftest import signup_headers
from tests.integration.factories import ANALYZE_BODY

# --- analysis + history + preferences ---
#
# Run the whole pipeline (analyze -> cache -> verdict -> history) against the
# real repos and a real agent. Per conftest's `light_agent` fixture the model is
# a tiny one; the tests that actually invoke it are marked `needs_ollama` and
# skip when Ollama is unreachable (CI installs it and pulls the model), so a
# teammate without Ollama still runs the rest of this module. Scores are
# nondeterministic, so the assertions below check shape, not fixed values.


@pytest.mark.needs_ollama
async def test_analyze_returns_verdict_and_id(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Live agent scores are nondeterministic; assert shape, not a fixed verdict.
    assert body["verdict"] in {"up", "down"}
    assert isinstance(body["analysis_id"], int)


@pytest.mark.needs_ollama
async def test_analyze_is_cached_across_calls(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    first = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    second = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    # Same normalized text -> same document -> same analysis_id.
    assert first.json()["analysis_id"] == second.json()["analysis_id"]


async def test_analyze_too_large(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    # One byte past the cap (ASCII, so chars == bytes). No agent runs: the byte
    # check in api/analysis.py rejects it before the queue, so no Ollama needed.
    big = {"text": "x" * (settings.max_analyze_bytes + 1), "url": None}
    resp = await client.post("/analyze", json=big, headers=auth_headers)
    assert resp.status_code == 413


@pytest.mark.needs_ollama
async def test_analysis_detail(client: httpx.AsyncClient, auth_headers: dict) -> None:
    analysis_id = (
        await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    ).json()["analysis_id"]

    resp = await client.get(f"/analyses/{analysis_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == analysis_id
    assert body["url"] == "https://ex.test/tos"
    # One CategoryScore per clause category.
    assert len(body["scores"]) == 6
    # Live agent scores are nondeterministic; each must be on the 0-2 scale.
    assert {s["score"] for s in body["scores"]} <= {0, 1, 2}


async def test_analysis_detail_missing(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get("/analyses/9999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.needs_ollama
async def test_history_lists_analyzed_documents(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)

    resp = await client.get("/history", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["next_cursor"] is None
    entries = body["items"]
    assert len(entries) == 1
    assert entries[0]["url"] == "https://ex.test/tos"
    assert entries[0]["verdict"] in {"up", "down"}


async def test_history_empty_for_new_user(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get("/history", headers=auth_headers)
    assert resp.json() == {"items": [], "next_cursor": None}


async def test_history_rejects_malformed_cursor(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """The shared cursor parser (PageParamsDep) rejects a hand-edited cursor
    before the service runs — 400, not 500 — on /history as on the forum lists.
    No agent involved."""
    resp = await client.get("/history?cursor=not-a-cursor", headers=auth_headers)
    assert resp.status_code == 400


async def test_analysis_detail_is_not_user_scoped(
    client: httpx.AsyncClient, auth_headers: dict, session: AsyncSession
) -> None:
    """`/analyses/{id}` is a per-document cache view, not per-user: any authed
    user can read an analysis id, by design (auth alone gates the route). Seeded
    directly so no agent runs."""
    doc = await documents_repo.create(
        session, "cross-user-hash", "https://ex.test/x", "normalized text"
    )
    session.add(
        Analysis(
            document_id=doc.id,
            category="arbitration",
            score=1,
            model_version=settings.model_version,
        )
    )
    await session.flush()

    bob = await signup_headers(client, "bob@example.com")
    resp = await client.get(f"/analyses/{doc.id}", headers=bob)
    assert resp.status_code == 200
    assert resp.json()["id"] == doc.id


async def test_preferences_round_trip(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    assert (await client.get("/preferences", headers=auth_headers)).json() == {
        "items": []
    }

    items = [{"category": "arbitration", "enabled": False}]
    put = await client.put(
        "/preferences", json={"items": items}, headers=auth_headers
    )
    assert put.status_code == 200
    assert put.json() == {"items": items}
    assert (await client.get("/preferences", headers=auth_headers)).json() == {
        "items": items
    }


async def test_preferences_duplicate_category_rejected(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    items = [
        {"category": "arbitration", "enabled": False},
        {"category": "arbitration", "enabled": True},
    ]
    resp = await client.put(
        "/preferences", json={"items": items}, headers=auth_headers
    )
    assert resp.status_code == 400
