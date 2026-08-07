"""Unit tests for the agent layer: document chunking.

Pure functions only — no model, no Ollama, no database. Anything that depends
on what a real model does lives in ``tests/system.py``.
"""

import pytest

from app.agent import classifier
from app.agent.categories import SCORE_ABSENT
from app.agent.chunking import (
    find_headings,
    split_document,
    split_sections,
    tiktoken_counter,
)
from app.agent.output import densify
from app.core.config import settings
from app.schemas.analysis import ChunkClassification, ClauseCategory, Finding


def words(text: str) -> int:
    """Stand-in token counter: deterministic, offline, and easy to eyeball.

    Real budgets use tiktoken, which downloads its BPE table on first use.
    Injecting the counter keeps these tests off the network.
    """
    return len(text.split())


# --- heading detection ------------------------------------------------------


def test_finds_numbered_section_headings() -> None:
    doc = "1. Definitions.\nAn account is a profile.\n\n2. Eligibility.\nBe 18.\n"
    assert [h.text for h in find_headings(doc)] == [
        "1. Definitions.",
        "2. Eligibility.",
    ]


def test_heading_offset_points_at_the_heading_not_the_blank_line_before_it() -> None:
    """``\\s*`` would let the match start on the preceding newline."""
    doc = "1. Definitions.\nAn account.\n\n2. Eligibility.\nBe 18.\n"
    second = find_headings(doc)[1]
    assert doc[second.offset] == "2"


def test_rejects_a_long_line_that_merely_starts_with_a_number() -> None:
    """Real headings are short; body prose beginning with a number is not one."""
    doc = (
        "1. Fees.\nFees are billed monthly.\n"
        "50. This is a long line of body prose that happens to begin with a "
        "number and runs well past any plausible heading length.\n"
    )
    assert [h.text for h in find_headings(doc)] == ["1. Fees."]


def test_rejects_an_inline_enumeration_that_restarts_numbering() -> None:
    """Section numbers ascend; a 1. after a 3. is a list item, not a section."""
    doc = (
        "3. Acceptable Use.\nProhibited activities include:\n"
        "1. Reverse engineering the Service.\n"
        "2. Scraping content at scale.\n"
    )
    assert [h.text for h in find_headings(doc)] == ["3. Acceptable Use."]


def test_accepts_deeper_subsection_numbering() -> None:
    doc = "12. Disputes.\nArbitration applies.\n\n12.3.1 Opt-out.\nWithin 30 days.\n"
    assert [h.text for h in find_headings(doc)] == ["12. Disputes.", "12.3.1 Opt-out."]


def test_ignores_a_number_that_is_not_at_the_start_of_a_line() -> None:
    doc = "1. Fees.\nYou agree to Section 12. Payment is due monthly.\n"
    assert [h.text for h in find_headings(doc)] == ["1. Fees."]


def test_requires_a_capitalised_title_after_the_number() -> None:
    doc = "1. Fees.\nBilling applies.\n\n2. lowercase continuation of a sentence\n"
    assert [h.text for h in find_headings(doc)] == ["1. Fees."]


def test_returns_nothing_for_text_with_no_headings() -> None:
    doc = "This agreement has no numbering at all. It is one flat paragraph.\n"
    assert find_headings(doc) == []


# --- section slicing --------------------------------------------------------


def test_pairs_each_heading_with_the_text_beneath_it() -> None:
    doc = "1. Definitions.\nAn account is a profile.\n\n2. Eligibility.\nBe 18.\n"
    sections = split_sections(doc)
    assert [s.heading for s in sections] == ["1. Definitions.", "2. Eligibility."]


def test_body_excludes_its_own_heading_line() -> None:
    doc = "1. Definitions.\nAn account is a profile.\n\n2. Eligibility.\nBe 18.\n"
    assert split_sections(doc)[0].body == "An account is a profile."


def test_final_section_runs_to_the_end_of_the_document() -> None:
    doc = "1. Definitions.\nAn account.\n\n2. Eligibility.\nBe 18. No exceptions.\n"
    assert split_sections(doc)[-1].body == "Be 18. No exceptions."


def test_preamble_before_the_first_heading_is_kept_with_an_empty_heading() -> None:
    """Dropping it would silently lose document text that may carry a clause."""
    doc = "Last updated May 2026. By using the Service you accept these Terms.\n\n1. Fees.\nMonthly.\n"
    sections = split_sections(doc)
    assert sections[0].heading == ""
    assert sections[0].body.startswith("Last updated May 2026.")
    assert [s.heading for s in sections[1:]] == ["1. Fees."]


def test_no_sections_when_the_document_has_no_headings() -> None:
    doc = "This agreement has no numbering at all. It is one flat paragraph.\n"
    assert split_sections(doc) == []


# --- whole-document splitting -----------------------------------------------

TWO_SECTIONS = (
    "1. Fees.\nMonthly billing applies here.\n\n2. Term.\nThe term is one year.\n"
)

BIG_SECTION = (
    "4. Limitation of Liability.\n"
    "The Service is provided as is without warranty of any kind. "
    "Our total liability shall not exceed fifty dollars in any period. "
    "Some jurisdictions do not allow that exclusion at all. "
    "In those places our liability is limited as far as law permits.\n"
)

NO_HEADINGS = (
    "This agreement has no numbering anywhere in it. "
    "You accept the terms by using the service at all. "
    "We may change the terms whenever we like. "
    "Your account may be closed without any notice given.\n"
)


def test_a_section_under_budget_becomes_one_chunk_carrying_its_heading() -> None:
    chunks = split_document(TWO_SECTIONS, count_tokens=words, max_tokens=8)
    assert chunks == [
        "1. Fees.\nMonthly billing applies here.",
        "2. Term.\nThe term is one year.",
    ]


def test_small_consecutive_sections_are_packed_into_one_chunk() -> None:
    chunks = split_document(TWO_SECTIONS, count_tokens=words, max_tokens=20)
    assert len(chunks) == 1
    assert "1. Fees." in chunks[0]
    assert "2. Term." in chunks[0]


def test_an_oversized_section_repeats_its_heading_on_every_piece() -> None:
    chunks = split_document(BIG_SECTION, count_tokens=words, max_tokens=20)
    assert len(chunks) > 1
    assert all(c.startswith("4. Limitation of Liability.") for c in chunks)


def test_no_chunk_exceeds_the_budget_once_the_heading_is_reattached() -> None:
    """The heading is added after the splitter ran; its cost must be budgeted."""
    chunks = split_document(BIG_SECTION, count_tokens=words, max_tokens=20)
    assert [c for c in chunks if words(c) > 20] == []


def test_falls_back_to_windows_when_no_headings_are_found() -> None:
    chunks = split_document(NO_HEADINGS, count_tokens=words, max_tokens=12)
    assert len(chunks) > 1
    assert [c for c in chunks if words(c) > 12] == []


def test_the_fallback_does_not_cut_mid_sentence() -> None:
    chunks = split_document(NO_HEADINGS, count_tokens=words, max_tokens=12)
    assert all(c.rstrip().endswith(".") for c in chunks)


def test_no_chunk_is_empty_or_whitespace_only() -> None:
    for doc in (TWO_SECTIONS, BIG_SECTION, NO_HEADINGS):
        chunks = split_document(doc, count_tokens=words, max_tokens=12)
        assert [c for c in chunks if not c.strip()] == []


def test_every_heading_survives_into_some_chunk() -> None:
    doc = TWO_SECTIONS + "\n" + BIG_SECTION
    chunks = split_document(doc, count_tokens=words, max_tokens=20)
    joined = "\n".join(chunks)
    for heading in ("1. Fees.", "2. Term.", "4. Limitation of Liability."):
        assert heading in joined


def test_an_empty_document_produces_no_chunks() -> None:
    assert split_document("", count_tokens=words, max_tokens=20) == []


# --- production token counter -----------------------------------------------
#
# tiktoken downloads its BPE table on first use and caches it on disk, so the
# very first run of these two tests on a clean machine needs network access.


def test_the_default_counter_counts_more_tokens_for_longer_text() -> None:
    count = tiktoken_counter()
    assert count("12. Dispute Resolution.") > count("Fees.")


def test_the_default_counter_reports_nothing_for_empty_text() -> None:
    assert tiktoken_counter()("") == 0


def test_the_default_counter_is_built_once_per_process() -> None:
    """Loading the encoding is slow; every chunk must not pay for it."""
    assert tiktoken_counter() is tiktoken_counter()


# --- analyze: whole document ------------------------------------------------
#
# classify_chunk is stubbed throughout: what a real model returns belongs in
# tests/system.py. What is under test here is fan-out and the merge.

MULTI_SECTION = (
    "1. Dispute Resolution.\nYou agree to binding arbitration.\n\n"
    "2. Termination.\nWe may close your account at any time.\n"
)


def _finding(category: ClauseCategory, score: int, evidence: str) -> Finding:
    return Finding(
        category=category,
        evidence=evidence,
        score=score,  # type: ignore[arg-type]
        explanation=f"{category.value} at {score}",
    )


def _stub_classify(
    monkeypatch: pytest.MonkeyPatch, per_chunk: list[list[Finding]]
) -> list[str]:
    """Feed each chunk a canned result; record the chunks that were classified."""
    seen: list[str] = []

    async def fake(text: str) -> ChunkClassification:
        index = len(seen)
        seen.append(text)
        return densify(per_chunk[index] if index < len(per_chunk) else [])

    monkeypatch.setattr(classifier, "classify_chunk", fake)
    return seen


async def test_returns_every_category_in_declaration_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_classify(monkeypatch, [])
    scores = await classifier.analyze(MULTI_SECTION)
    assert [s.category for s in scores] == list(ClauseCategory)


async def test_classifies_every_chunk_of_the_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _stub_classify(monkeypatch, [])
    await classifier.analyze(MULTI_SECTION)
    assert len(seen) == len(
        split_document(
            MULTI_SECTION,
            count_tokens=tiktoken_counter(),
            max_tokens=settings.chunk_tokens,
        )
    )


async def test_category_score_is_the_max_across_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clause scored 2 in one chunk must not be diluted by a 1 in another."""
    monkeypatch.setattr(settings, "chunk_tokens", 12)
    _stub_classify(
        monkeypatch,
        [
            [_finding(ClauseCategory.ARBITRATION, 1, "binding arbitration")],
            [_finding(ClauseCategory.ARBITRATION, 2, "no opt-out")],
        ],
    )
    scores = await classifier.analyze(MULTI_SECTION)
    arbitration = next(s for s in scores if s.category is ClauseCategory.ARBITRATION)
    assert arbitration.score == 2


async def test_findings_from_different_chunks_are_all_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chunk_tokens", 12)
    _stub_classify(
        monkeypatch,
        [
            [_finding(ClauseCategory.ARBITRATION, 2, "arbitrator of our choosing")],
            [_finding(ClauseCategory.ARBITRATION, 2, "class action waiver")],
        ],
    )
    scores = await classifier.analyze(MULTI_SECTION)
    arbitration = next(s for s in scores if s.category is ClauseCategory.ARBITRATION)
    assert [f.evidence for f in arbitration.findings] == [
        "arbitrator of our choosing",
        "class action waiver",
    ]


async def test_an_identical_finding_in_two_chunks_collapses_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated boilerplate is one clause, not two."""
    monkeypatch.setattr(settings, "chunk_tokens", 12)
    repeated = _finding(ClauseCategory.LIABILITY, 2, "liability capped at $50")
    _stub_classify(monkeypatch, [[repeated], [repeated]])
    scores = await classifier.analyze(MULTI_SECTION)
    liability = next(s for s in scores if s.category is ClauseCategory.LIABILITY)
    assert len(liability.findings) == 1


async def test_an_empty_document_scores_every_category_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _stub_classify(monkeypatch, [])
    scores = await classifier.analyze("")
    assert seen == []
    assert all(s.score == SCORE_ABSENT and s.findings == [] for s in scores)
