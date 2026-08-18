"""Integration tests: analyze + history + preferences pipeline."""


import httpx

from tests.integration.factories import ANALYZE_BODY

# --- analysis + history + preferences ---
#
# Run the whole pipeline (analyze -> cache -> verdict -> history) against the
# real repos and a real agent against settings.agent_model (qwen2.5:0.5b, a tiny
# one), so a live Ollama IS required (CI installs it and pulls the model);
# scores are therefore nondeterministic, and the assertions below check shape,
# not fixed values.


async def test_analyze_returns_verdict_and_id(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Live agent scores are nondeterministic; assert shape, not a fixed verdict.
    assert body["verdict"] in {"up", "down"}
    assert isinstance(body["analysis_id"], int)


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
    big = {"text": "x" * 1_000_001, "url": None}
    resp = await client.post("/analyze", json=big, headers=auth_headers)
    assert resp.status_code == 413


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


# --- analysis pipeline through a live queue ---------------------------------


async def test_analyze_runs_through_a_live_queue(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # The `client` fixture starts the queue itself (bound to the same
    # in-memory database the client's requests use); starting it again here
    # against a different, file-backed factory would point the worker at a
    # database the caller can't see its writes in.
    resp = await client.post(
        "/analyze",
        json={"text": "You waive all rights. We may share your data.", "url": None},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] in {"up", "down"}
    assert isinstance(body["analysis_id"], int)
