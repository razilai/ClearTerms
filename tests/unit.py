"""Unit tests for pure backend logic (no db, no HTTP, no LLM)."""

import pytest
from pydantic import ValidationError

from app.agent.categories import (
    CATEGORY_SPECS,
    MAX_SCORE,
    MIN_SCORE,
    SCORE_SCALE,
    ClauseCategory,
)
from app.agent.output import ChunkFindings, ClauseScore, Finding

# Frozen on purpose: these strings are stored in Analysis.category and
# Preference.category, so changing one invalidates cached analyses and orphans
# existing preference rows. Editing this list should be a deliberate act.
EXPECTED_SLUGS = {
    "unilateral_changes",
    "arbitration",
    "liability",
    "content_licensing",
    "data_collection",
    "termination",
}


def test_slugs_are_frozen() -> None:
    assert {c.value for c in ClauseCategory} == EXPECTED_SLUGS


def test_every_category_has_a_spec() -> None:
    assert set(CATEGORY_SPECS) == set(ClauseCategory)


def test_specs_are_keyed_by_their_own_category() -> None:
    for category, spec in CATEGORY_SPECS.items():
        assert spec.category is category


def test_prompt_fields_are_populated() -> None:
    for category, spec in CATEGORY_SPECS.items():
        assert spec.detection.strip(), category
        assert spec.standard.strip(), category
        assert spec.aggressive.strip(), category
        assert spec.boundaries, f"{category} has no tiebreak rule"
        assert all(rule.strip() for rule in spec.boundaries), category


def test_display_fields_are_populated_and_unique() -> None:
    display_names = [spec.display_name for spec in CATEGORY_SPECS.values()]
    assert all(name.strip() for name in display_names)
    assert len(set(display_names)) == len(display_names)
    assert all(spec.description.strip() for spec in CATEGORY_SPECS.values())


# --- app.agent.output: schemas -------------------------------------------


def test_finding_rejects_score_zero() -> None:
    """Absence is expressed by omitting a category, never by scoring it 0."""
    with pytest.raises(ValidationError):
        Finding(
            category=ClauseCategory.ARBITRATION,
            evidence="You waive any right to a jury trial.",
            score=0,
            explanation="Not addressed.",
        )


def test_finding_rejects_score_three() -> None:
    with pytest.raises(ValidationError):
        Finding(
            category=ClauseCategory.ARBITRATION,
            evidence="You waive any right to a jury trial.",
            score=3,
            explanation="Very aggressive.",
        )


def test_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Finding(
            category=ClauseCategory.ARBITRATION,
            score=2,
            explanation="Mandatory arbitration with no opt-out.",
        )


def test_finding_field_order_puts_evidence_before_score() -> None:
    """Constrained decoding emits fields in schema order: quote, then judge."""
    fields = list(Finding.model_fields)
    assert fields.index("evidence") < fields.index("score")


def test_chunk_findings_accepts_an_empty_list() -> None:
    """A chunk addressing no category is normal, not an error."""
    assert ChunkFindings(findings=[]).findings == []


def test_clause_score_allows_absent_category() -> None:
    absent = ClauseScore(category=ClauseCategory.LIABILITY, score=0)
    assert absent.evidence is None
    assert absent.explanation is None


