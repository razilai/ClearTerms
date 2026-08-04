"""Unit tests for pure backend logic (no db, no HTTP, no LLM)."""

import asyncio
import inspect

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent, ModelRetry

from app.agent import classifier
from app.agent.categories import (
    CATEGORY_SPECS,
    SCORE_ABSENT,
    SCORE_SCALE,
    ClauseCategory,
)
from app.agent.classifier import (
    MAX_EVIDENCE_RETRIES,
    build_agent,
    check_evidence,
    classify_chunk,
    load_prompts,
    render_categories,
    render_score_scale,
    render_system_prompt,
)
from app.agent.evidence import is_verbatim, normalize
from app.agent.output import (
    ChunkClassification,
    ChunkFindings,
    ClauseScore,
    Finding,
    densify,
    drop_duplicate_findings,
)

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
    assert absent.findings == []


# --- app.agent.output: densify and duplicate handling ---------------------


def _finding(category: ClauseCategory, score: int = 2) -> Finding:
    return Finding(
        category=category,
        evidence=f"evidence for {category.value}",
        score=score,
        explanation=f"explanation for {category.value}",
    )


def test_densify_returns_every_category_in_enum_order() -> None:
    result = densify([_finding(ClauseCategory.ARBITRATION)])
    assert [s.category for s in result.scores] == list(ClauseCategory)


def test_densify_fills_absent_categories_with_zero_and_no_findings() -> None:
    result = densify([_finding(ClauseCategory.ARBITRATION)])
    absent = [s for s in result.scores if s.category is not ClauseCategory.ARBITRATION]
    assert all(s.score == SCORE_ABSENT for s in absent)
    assert all(s.findings == [] for s in absent)


def test_densify_preserves_reported_findings() -> None:
    result = densify([_finding(ClauseCategory.LIABILITY, score=1)])
    liability = next(s for s in result.scores if s.category is ClauseCategory.LIABILITY)
    assert liability.score == 1
    assert len(liability.findings) == 1
    assert liability.findings[0].evidence == "evidence for liability"
    assert liability.findings[0].explanation == "explanation for liability"


def test_densify_of_nothing_is_six_zeros() -> None:
    result = densify([])
    assert len(result.scores) == len(ClauseCategory)
    assert all(s.score == SCORE_ABSENT for s in result.scores)


def test_findings_are_present_exactly_when_score_is_nonzero() -> None:
    result = densify([_finding(ClauseCategory.TERMINATION, score=1)])
    for score in result.scores:
        assert bool(score.findings) == (score.score > SCORE_ABSENT)


def test_densify_keeps_every_finding_for_a_category() -> None:
    """Four predatory arbitration clauses must not collapse into one."""
    findings = [
        Finding(
            category=ClauseCategory.ARBITRATION,
            evidence="You waive any right to a jury trial.",
            score=2,
            explanation="Jury waiver.",
        ),
        Finding(
            category=ClauseCategory.ARBITRATION,
            evidence="Claims must be filed within 30 days.",
            score=1,
            explanation="Shortened but stated deadline.",
        ),
    ]
    result = densify(findings)
    arbitration = next(
        s for s in result.scores if s.category is ClauseCategory.ARBITRATION
    )
    assert len(arbitration.findings) == 2
    assert [f.score for f in arbitration.findings] == [2, 1]


def test_densify_preserves_the_order_the_model_reported() -> None:
    findings = [
        Finding(
            category=ClauseCategory.LIABILITY,
            evidence="first clause",
            score=1,
            explanation="a",
        ),
        Finding(
            category=ClauseCategory.LIABILITY,
            evidence="second clause",
            score=2,
            explanation="b",
        ),
    ]
    result = densify(findings)
    liability = next(s for s in result.scores if s.category is ClauseCategory.LIABILITY)
    assert [f.evidence for f in liability.findings] == ["first clause", "second clause"]


def test_category_score_is_the_max_of_its_findings() -> None:
    findings = [
        _finding(ClauseCategory.DATA_COLLECTION, score=1),
        _finding(ClauseCategory.DATA_COLLECTION, score=2),
    ]
    result = densify(findings)
    data = next(s for s in result.scores if s.category is ClauseCategory.DATA_COLLECTION)
    assert data.score == 2
    assert len(data.findings) == 2


def test_drop_duplicate_findings_removes_byte_identical_repeats() -> None:
    """Two identical findings are the model stuttering, not two clauses."""
    findings = [_finding(ClauseCategory.ARBITRATION), _finding(ClauseCategory.ARBITRATION)]
    assert len(drop_duplicate_findings(findings)) == 1


def test_drop_duplicate_findings_keeps_findings_differing_in_any_field() -> None:
    findings = [
        Finding(
            category=ClauseCategory.ARBITRATION,
            evidence="same quote",
            score=1,
            explanation="a",
        ),
        Finding(
            category=ClauseCategory.ARBITRATION,
            evidence="same quote",
            score=2,
            explanation="a",
        ),
    ]
    assert len(drop_duplicate_findings(findings)) == 2


# --- app.agent.evidence --------------------------------------------------

CHUNK = (
    "14. Limitation of Liability. The Service is provided “as is” and we "
    "disclaim all warranties — express or implied.\nOur total liability shall "
    "not exceed one hundred dollars."
)


def test_normalize_collapses_whitespace_runs() -> None:
    assert normalize("a  b\n\tc") == "a b c"


def test_normalize_straightens_curly_quotes() -> None:
    assert normalize("“as is”") == '"as is"'
    assert normalize("it’s") == "it's"


def test_normalize_flattens_dashes() -> None:
    assert normalize("a — b") == "a - b"


def test_normalize_casefolds() -> None:
    assert normalize("As Is") == "as is"


def test_is_verbatim_accepts_an_exact_quote() -> None:
    assert is_verbatim("Our total liability shall not exceed one hundred dollars.", CHUNK)


def test_is_verbatim_accepts_straightened_quotes() -> None:
    """The model retypes curly quotes as straight ones constantly."""
    assert is_verbatim('The Service is provided "as is"', CHUNK)


def test_is_verbatim_accepts_a_folded_line_break() -> None:
    assert is_verbatim(
        "express or implied. Our total liability shall not exceed one hundred dollars.",
        CHUNK,
    )


def test_is_verbatim_accepts_different_casing() -> None:
    assert is_verbatim("LIMITATION OF LIABILITY", CHUNK)


def test_is_verbatim_rejects_a_paraphrase() -> None:
    assert not is_verbatim("Liability is capped at one hundred dollars.", CHUNK)


def test_is_verbatim_rejects_an_invented_quote() -> None:
    assert not is_verbatim("You agree to binding arbitration.", CHUNK)


def test_is_verbatim_rejects_empty_evidence() -> None:
    """An empty string is a substring of everything; reject it explicitly."""
    assert not is_verbatim("", CHUNK)
    assert not is_verbatim("   ", CHUNK)


# --- app.agent.classifier: prompt rendering ------------------------------


def test_load_prompts_has_a_system_prompt_and_one_example() -> None:
    prompts = load_prompts()
    assert prompts["system"]["prompt"].strip()
    assert len(prompts["few_shot"]["examples"]) == 1


def test_rendered_prompt_contains_every_category_slug() -> None:
    rendered = render_system_prompt()
    for category in ClauseCategory:
        assert category.value in rendered, category


def test_rendered_prompt_contains_the_neutral_spec_text() -> None:
    rendered = render_system_prompt()
    for spec in CATEGORY_SPECS.values():
        assert spec.detection in rendered
        assert spec.standard in rendered
        assert spec.aggressive in rendered


def test_rendered_prompt_excludes_product_voice() -> None:
    """display_name and description are for humans; loaded framing skews scores."""
    rendered = render_system_prompt()
    for spec in CATEGORY_SPECS.values():
        assert spec.description not in rendered


def test_rendered_prompt_contains_the_score_scale() -> None:
    rendered = render_system_prompt()
    for meaning in SCORE_SCALE.values():
        assert meaning in rendered


def test_rendered_prompt_has_no_unsubstituted_placeholders() -> None:
    # Not a blanket "{" check: the rendered JSON example legitimately has braces.
    rendered = render_system_prompt()
    assert "{categories}" not in rendered
    assert "{score_scale}" not in rendered
    assert "{example_text}" not in rendered
    assert "{example_output}" not in rendered


def test_rendered_categories_include_boundary_rules() -> None:
    rendered = render_categories()
    for spec in CATEGORY_SPECS.values():
        for rule in spec.boundaries:
            assert rule in rendered


def test_example_findings_are_valid_findings() -> None:
    """The few-shot example must parse as real model output."""
    example = load_prompts()["few_shot"]["examples"][0]
    findings = [Finding(**f) for f in example["findings"]]
    assert len(findings) >= 2
    assert {f.score for f in findings} == {1, 2}


def test_example_evidence_is_verbatim_from_the_example_text() -> None:
    """The example must model the behaviour it asks for."""
    example = load_prompts()["few_shot"]["examples"][0]
    for finding in example["findings"]:
        assert is_verbatim(finding["evidence"], example["text"]), finding["category"]


def test_example_omits_most_categories() -> None:
    """Sparseness is taught by showing categories left out."""
    example = load_prompts()["few_shot"]["examples"][0]
    reported = {f["category"] for f in example["findings"]}
    assert len(reported) < len(ClauseCategory)


def test_render_score_scale_lists_all_three_levels() -> None:
    rendered = render_score_scale()
    for score in SCORE_SCALE:
        assert str(score) in rendered


# --- app.agent.classifier: evidence validator ----------------------------

VALIDATOR_CHUNK = (
    "You agree that all disputes shall be resolved by binding arbitration. "
    "We may terminate your account at any time for any reason."
)


def _quoted(category: ClauseCategory, evidence: str, score: int = 2) -> Finding:
    return Finding(
        category=category,
        evidence=evidence,
        score=score,
        explanation=f"explanation for {category.value}",
    )


def test_check_evidence_passes_verbatim_findings_through() -> None:
    findings = [
        _quoted(
            ClauseCategory.ARBITRATION,
            "all disputes shall be resolved by binding arbitration",
        )
    ]
    assert check_evidence(findings, VALIDATOR_CHUNK, retry=0) == findings


def test_check_evidence_accepts_an_empty_result() -> None:
    assert check_evidence([], VALIDATOR_CHUNK, retry=0) == []


def test_check_evidence_retries_on_a_bad_quote() -> None:
    findings = [_quoted(ClauseCategory.ARBITRATION, "you must arbitrate everything")]
    with pytest.raises(ModelRetry):
        check_evidence(findings, VALIDATOR_CHUNK, retry=0)


def test_retry_message_names_the_offending_category() -> None:
    findings = [_quoted(ClauseCategory.ARBITRATION, "you must arbitrate everything")]
    with pytest.raises(ModelRetry) as excinfo:
        check_evidence(findings, VALIDATOR_CHUNK, retry=0)
    assert "arbitration" in str(excinfo.value)


def test_check_evidence_drops_a_bad_quote_after_the_retry() -> None:
    findings = [_quoted(ClauseCategory.ARBITRATION, "you must arbitrate everything")]
    assert check_evidence(findings, VALIDATOR_CHUNK, retry=MAX_EVIDENCE_RETRIES) == []


def test_dropping_one_finding_keeps_the_others() -> None:
    good = _quoted(
        ClauseCategory.TERMINATION,
        "We may terminate your account at any time for any reason.",
    )
    bad = _quoted(ClauseCategory.ARBITRATION, "you must arbitrate everything")
    surviving = check_evidence([good, bad], VALIDATOR_CHUNK, retry=MAX_EVIDENCE_RETRIES)
    assert surviving == [good]


def test_dropped_findings_densify_to_zero() -> None:
    bad = _quoted(ClauseCategory.ARBITRATION, "you must arbitrate everything")
    surviving = check_evidence([bad], VALIDATOR_CHUNK, retry=MAX_EVIDENCE_RETRIES)
    result = densify(surviving)
    arbitration = next(
        s for s in result.scores if s.category is ClauseCategory.ARBITRATION
    )
    assert arbitration.score == SCORE_ABSENT
    assert arbitration.findings == []


# --- app.agent.classifier: agent wiring ----------------------------------


def test_build_agent_returns_an_agent() -> None:
    assert isinstance(build_agent(), Agent)


def test_build_agent_is_cached() -> None:
    """One agent per process — rebuilding re-renders the prompt every call."""
    assert build_agent() is build_agent()


def test_classify_chunk_is_async() -> None:
    assert inspect.iscoroutinefunction(classify_chunk)


def test_classify_chunk_returns_all_six_categories(monkeypatch) -> None:
    """The dense contract holds regardless of what the model reported."""

    class _Result:
        output = ChunkFindings(
            findings=[
                Finding(
                    category=ClauseCategory.ARBITRATION,
                    evidence="binding arbitration",
                    score=2,
                    explanation="Mandatory, no opt-out.",
                )
            ]
        )

    class _FakeAgent:
        async def run(self, prompt: str, deps: str) -> _Result:
            return _Result()

    monkeypatch.setattr(classifier, "build_agent", lambda: _FakeAgent())

    result = asyncio.run(classifier.classify_chunk("You agree to binding arbitration."))
    assert isinstance(result, ChunkClassification)
    assert [s.category for s in result.scores] == list(ClauseCategory)
    arbitration = next(
        s for s in result.scores if s.category is ClauseCategory.ARBITRATION
    )
    assert arbitration.score == 2


