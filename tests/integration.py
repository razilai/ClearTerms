"""Integration tests: auth + forum endpoints against the app with faked repos."""

import httpx

from tests.conftest import signup_headers

POST_BODY = {"title": "Sneaky arbitration clause", "body": "Section 12 forces arbitration."}


async def _create_post(client: httpx.AsyncClient, headers: dict) -> int:
    resp = await client.post("/forum/posts", json=POST_BODY, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- auth ---


async def test_signup_returns_token(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/signup", json={"email": "new@example.com", "password": "s3cretpass"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_signup_short_password(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/signup", json={"email": "new@example.com", "password": "short"}
    )
    assert resp.status_code == 422


async def test_signup_email_lowercased(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/signup", json={"email": "Bob@Example.COM", "password": "s3cretpass"}
    )
    assert resp.status_code == 201
    resp = await client.post(
        "/auth/login", data={"username": "bob@example.com", "password": "s3cretpass"}
    )
    assert resp.status_code == 200


async def test_signup_duplicate_email(client: httpx.AsyncClient) -> None:
    await signup_headers(client, "dup@example.com")
    resp = await client.post(
        "/auth/signup", json={"email": "dup@example.com", "password": "otherpass"}
    )
    assert resp.status_code == 409


async def test_login_ok(client: httpx.AsyncClient) -> None:
    await signup_headers(client, "bob@example.com", "s3cretpass")
    resp = await client.post(
        "/auth/login", data={"username": "bob@example.com", "password": "s3cretpass"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_wrong_password(client: httpx.AsyncClient) -> None:
    await signup_headers(client, "bob@example.com", "s3cretpass")
    resp = await client.post(
        "/auth/login", data={"username": "bob@example.com", "password": "nope"}
    )
    assert resp.status_code == 401


async def test_login_unknown_email(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/login", data={"username": "ghost@example.com", "password": "pw"}
    )
    assert resp.status_code == 401


async def test_missing_auth_header(client: httpx.AsyncClient) -> None:
    resp = await client.get("/forum/posts")
    assert resp.status_code == 401


async def test_garbage_bearer_token(client: httpx.AsyncClient) -> None:
    resp = await client.get(
        "/forum/posts", headers={"Authorization": "Bearer garbage"}
    )
    assert resp.status_code == 401


# --- posts ---


async def test_create_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["author_email"] == "alice@example.com"
    assert body["title"] == POST_BODY["title"]
    assert body["like_count"] == 0


async def test_list_posts(client: httpx.AsyncClient, auth_headers: dict) -> None:
    await _create_post(client, auth_headers)
    resp = await client.get("/forum/posts", headers=auth_headers)
    assert resp.status_code == 200
    posts = resp.json()
    assert len(posts) == 1
    assert posts[0]["author_email"] == "alice@example.com"


async def test_post_detail_with_comments(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "Same in their privacy policy."},
        headers=auth_headers,
    )
    resp = await client.get(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["comments"]) == 1
    assert detail["comments"][0]["author_email"] == "alice@example.com"
    assert detail["comments"][0]["edited_at"] is None


async def test_get_missing_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.get("/forum/posts/9999", headers=auth_headers)
    assert resp.status_code == 404


async def test_delete_own_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    post_id = await _create_post(client, auth_headers)
    resp = await client.delete(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 204
    resp = await client.get(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_delete_other_users_post(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    mallory = await signup_headers(client, "mallory@example.com")
    resp = await client.delete(f"/forum/posts/{post_id}", headers=mallory)
    assert resp.status_code == 403


# --- comments ---


async def _post_and_comment(
    client: httpx.AsyncClient, headers: dict
) -> tuple[int, int]:
    post_id = await _create_post(client, headers)
    comment_id = (
        await client.post(
            f"/forum/posts/{post_id}/comments",
            json={"body": "original"},
            headers=headers,
        )
    ).json()["id"]
    return post_id, comment_id


async def test_comment_on_missing_post(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        "/forum/posts/9999/comments", json={"body": "hi"}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_edit_own_comment(client: httpx.AsyncClient, auth_headers: dict) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    resp = await client.patch(
        f"/forum/comments/{comment_id}", json={"body": "edited"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["body"] == "edited"
    assert body["edited_at"] is not None


async def test_edit_other_users_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    mallory = await signup_headers(client, "mallory@example.com")
    resp = await client.patch(
        f"/forum/comments/{comment_id}", json={"body": "hijack"}, headers=mallory
    )
    assert resp.status_code == 403


async def test_edit_missing_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.patch(
        "/forum/comments/9999", json={"body": "x"}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_delete_own_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    resp = await client.delete(f"/forum/comments/{comment_id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_delete_other_users_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    mallory = await signup_headers(client, "mallory@example.com")
    resp = await client.delete(f"/forum/comments/{comment_id}", headers=mallory)
    assert resp.status_code == 403


# --- likes ---


async def test_toggle_like(client: httpx.AsyncClient, auth_headers: dict) -> None:
    post_id = await _create_post(client, auth_headers)
    resp = await client.put(f"/forum/posts/{post_id}/like", headers=auth_headers)
    assert resp.json() == {"like_count": 1, "liked": True}
    resp = await client.put(f"/forum/posts/{post_id}/like", headers=auth_headers)
    assert resp.json() == {"like_count": 0, "liked": False}


async def test_like_missing_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.put("/forum/posts/9999/like", headers=auth_headers)
    assert resp.status_code == 404
"""Integration tests for the classifier against a live Ollama server.

These are the tests unit tests cannot be: everything here depends on what a
real model actually does with the prompt. They are slow (one model call takes
seconds to minutes depending on hardware) and they are skipped entirely when
Ollama is not reachable, so they never break a teammate who has not installed
it.

Every test here is marked ``slow`` and is deselected by default, so a routine
``uv run pytest`` stays fast. Run them from ``backend/`` with::

    uv run pytest -m slow -v

``-m slow`` is required — without it every test in this module is deselected.
If you name this file by path instead, add ``-c pyproject.toml``: a path
outside ``backend/`` makes pytest choose the repo root as rootdir, which
silently discards this project's pytest configuration, including the
``pythonpath`` entry that makes ``app`` importable.

The three chunks below are classified once each at module scope; every test
asserts against those cached results rather than paying for its own call.
"""

import asyncio
import json
import urllib.error
import urllib.request

import pytest

from app.agent.categories import MAX_SCORE, MIN_SCORE, SCORE_ABSENT, ClauseCategory
from app.agent.classifier import classify_chunk
from app.agent.evidence import is_verbatim
from app.agent.output import ChunkClassification
from app.core.config import settings


def _ollama_has_model() -> bool:
    """True if Ollama is up and settings.agent_model is pulled."""
    try:
        with urllib.request.urlopen(
            f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=3
        ) as response:
            tags = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    return any(m.get("name") == settings.agent_model for m in tags.get("models", []))


pytestmark = pytest.mark.slow


if not _ollama_has_model():
    pytest.skip(
        f"Ollama not reachable at {settings.ollama_base_url} "
        f"or model {settings.agent_model!r} not pulled",
        allow_module_level=True,
    )


# --- fixtures: one model call each, shared across the module -------------

ARBITRATION_CHUNK = """12. Dispute Resolution.
You and the Company agree that any dispute arising out of these Terms shall be
resolved exclusively by binding arbitration administered by an arbitrator of
the Company's choosing. You waive any right to a trial by jury and you waive
any right to participate in a class action. Arbitration shall take place in
Singapore. There is no opt-out from this provision."""

MULTI_CHUNK = """15. Limitation of Liability.
The Service is provided "as is" without warranty of any kind. Our total
liability to you for any claim shall not exceed fifty dollars, regardless of
the fees you have paid.

16. Termination.
We may suspend or terminate your account at any time, for any reason, without
notice. Any unused credits are forfeited upon termination."""

BENIGN_CHUNK = """3. Definitions.
"Account" means the personal profile you create when registering. "Content"
means text, images, or other material. "Service" means the website and mobile
applications operated by the Company. Headings are for convenience only and do
not affect interpretation of these Terms."""


def _classify(text: str) -> ChunkClassification:
    return asyncio.run(classify_chunk(text))


@pytest.fixture(scope="module")
def arbitration() -> ChunkClassification:
    return _classify(ARBITRATION_CHUNK)


@pytest.fixture(scope="module")
def multi() -> ChunkClassification:
    return _classify(MULTI_CHUNK)


@pytest.fixture(scope="module")
def benign() -> ChunkClassification:
    return _classify(BENIGN_CHUNK)


# --- contract: these must hold whatever the model says -------------------


def test_returns_every_category(multi: ChunkClassification) -> None:
    assert [s.category for s in multi.scores] == list(ClauseCategory)


def test_scores_are_within_the_scale(multi: ChunkClassification) -> None:
    assert all(MIN_SCORE <= s.score <= MAX_SCORE for s in multi.scores)


def test_findings_are_present_exactly_when_scored(multi: ChunkClassification) -> None:
    for score in multi.scores:
        assert bool(score.findings) == (score.score > SCORE_ABSENT)


def test_category_score_is_the_max_of_its_findings(multi: ChunkClassification) -> None:
    for score in multi.scores:
        if score.findings:
            assert score.score == max(f.score for f in score.findings)


def test_findings_never_carry_a_zero_score(multi: ChunkClassification) -> None:
    """Literal[1, 2] must survive the round trip through Ollama's schema handling."""
    for score in multi.scores:
        assert all(f.score in (1, 2) for f in score.findings)


def test_findings_are_filed_under_their_own_category(
    multi: ChunkClassification,
) -> None:
    for score in multi.scores:
        assert all(f.category is score.category for f in score.findings)


def test_evidence_is_verbatim_from_the_chunk(multi: ChunkClassification) -> None:
    """The validator should have dropped anything not in the source."""
    for score in multi.scores:
        for finding in score.findings:
            assert is_verbatim(finding.evidence, MULTI_CHUNK), (
                f"{score.category.value}: {finding.evidence!r}"
            )


def test_explanations_are_non_empty(multi: ChunkClassification) -> None:
    for score in multi.scores:
        assert all(f.explanation.strip() for f in score.findings)


# --- behaviour: what the model actually does with the prompt -------------


def test_detects_obvious_arbitration(arbitration: ChunkClassification) -> None:
    found = next(
        s for s in arbitration.scores if s.category is ClauseCategory.ARBITRATION
    )
    assert found.score > SCORE_ABSENT


def test_scores_egregious_arbitration_as_aggressive(
    arbitration: ChunkClassification,
) -> None:
    """No opt-out, jury and class waiver, provider-chosen arbitrator, distant venue."""
    found = next(
        s for s in arbitration.scores if s.category is ClauseCategory.ARBITRATION
    )
    assert found.score == MAX_SCORE


def test_is_sparse_on_a_single_topic_chunk(arbitration: ChunkClassification) -> None:
    """A dispute-resolution section should not light up most of the taxonomy."""
    reported = [s for s in arbitration.scores if s.score > SCORE_ABSENT]
    assert len(reported) <= 3, [s.category.value for s in reported]


def test_finds_both_categories_in_a_two_section_chunk(
    multi: ChunkClassification,
) -> None:
    """Chunk boundaries do not align with sections; both must be caught."""
    scored = {s.category for s in multi.scores if s.score > SCORE_ABSENT}
    assert ClauseCategory.LIABILITY in scored
    assert ClauseCategory.TERMINATION in scored


def test_benign_boilerplate_scores_mostly_absent(benign: ChunkClassification) -> None:
    """A definitions section addresses nothing; the model must resist scoring it."""
    reported = [s for s in benign.scores if s.score > SCORE_ABSENT]
    assert len(reported) <= 1, [s.category.value for s in reported]
