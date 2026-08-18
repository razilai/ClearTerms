"""Unit tests: preferences repo and compute_verdict."""



import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.categories import SCORE_AGGRESSIVE, SCORE_STANDARD
from app.core.config import settings
from app.db.repos import preferences, users
from app.models import Analysis
from app.services import preferences as preferences_service
from tests.unit.factories import _items, _preference

# --- preferences repo -------------------------------------------------------
#
# Preference.user_id is a real FK, so these create actual users rather than
# inventing ids: the tests stay valid if FK enforcement is ever switched on.


async def test_get_for_user_returns_only_that_users_preferences(
    session: AsyncSession,
) -> None:
    alice = await users.create(session, "ada@example.com", "pw1")
    bob = await users.create(session, "bob@example.com", "pw2")
    await preferences.replace_for_user(
        session, alice.id, _items(("arbitration", True), ("liability", False))
    )
    await preferences.replace_for_user(
        session, bob.id, _items(("data_collection", False))
    )

    found = await preferences.get_for_user(session, alice.id)
    assert {(p.category, p.enabled) for p in found} == {
        ("arbitration", True),
        ("liability", False),
    }
    assert all(p.user_id == alice.id for p in found)


async def test_get_for_user_returns_empty_list_when_none(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")

    assert await preferences.get_for_user(session, user.id) == []


async def test_replace_for_user_sets_initial_preferences(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")

    returned = await preferences.replace_for_user(
        session, user.id, _items(("arbitration", True), ("liability", False))
    )
    assert {(p.category, p.enabled) for p in returned} == {
        ("arbitration", True),
        ("liability", False),
    }

    found = await preferences.get_for_user(session, user.id)
    assert {(p.category, p.enabled) for p in found} == {
        ("arbitration", True),
        ("liability", False),
    }


async def test_replace_for_user_wipes_previous_set(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")
    other = await users.create(session, "bob@example.com", "pw2")
    await preferences.replace_for_user(
        session, user.id, _items(("arbitration", True), ("liability", False))
    )
    await preferences.replace_for_user(session, other.id, _items(("arbitration", False)))

    await preferences.replace_for_user(
        session, user.id, _items(("data_collection", False), ("termination", True))
    )

    found = await preferences.get_for_user(session, user.id)
    assert {(p.category, p.enabled) for p in found} == {
        ("data_collection", False),
        ("termination", True),
    }
    # The replaced categories are gone entirely, not merely toggled off.
    assert {p.category for p in found}.isdisjoint({"arbitration", "liability"})
    # The wipe is scoped to one user: bob keeps his own "arbitration" row.
    other_found = await preferences.get_for_user(session, other.id)
    assert {(p.category, p.enabled) for p in other_found} == {("arbitration", False)}


async def test_duplicate_category_for_user_raises(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")
    await preferences.replace_for_user(session, user.id, _items(("arbitration", True)))

    # Added directly rather than through the repo: this pins the DB constraint
    # itself, leaving replace_for_user free to dedupe its own input if it wants.
    session.add(_preference(user.id, "arbitration", enabled=False))
    with pytest.raises(IntegrityError):
        await session.flush()


# --- compute_verdict --------------------------------------------------------
#
# Pure function over cached scores x preferences: no session needed. A category
# the user has switched off must not be able to produce a thumbs-down, and a
# category they never configured must still count (fresh accounts get a
# meaningful verdict).


def _score(category: str, score: int) -> Analysis:
    return Analysis(
        document_id=0,
        category=category,
        score=score,
        model_version=settings.model_version,
    )


def test_compute_verdict_counts_unconfigured_categories() -> None:
    verdict = preferences_service.compute_verdict(
        [_score("arbitration", SCORE_AGGRESSIVE)], []
    )
    assert verdict == "down"


def test_compute_verdict_ignores_disabled_category() -> None:
    verdict = preferences_service.compute_verdict(
        [_score("arbitration", SCORE_AGGRESSIVE)],
        [_preference(user_id=1, category="arbitration", enabled=False)],
    )
    assert verdict == "up"


def test_compute_verdict_keeps_enabled_category() -> None:
    verdict = preferences_service.compute_verdict(
        [_score("arbitration", SCORE_AGGRESSIVE)],
        [_preference(user_id=1, category="arbitration", enabled=True)],
    )
    assert verdict == "down"


def test_compute_verdict_disabling_one_category_leaves_others_counting() -> None:
    verdict = preferences_service.compute_verdict(
        [
            _score("arbitration", SCORE_AGGRESSIVE),
            _score("liability", SCORE_AGGRESSIVE),
        ],
        [_preference(user_id=1, category="arbitration", enabled=False)],
    )
    assert verdict == "down"


def test_compute_verdict_up_when_nothing_is_aggressive() -> None:
    verdict = preferences_service.compute_verdict(
        [_score("arbitration", SCORE_STANDARD)], []
    )
    assert verdict == "up"
