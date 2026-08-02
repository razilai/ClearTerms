# TOS Clause Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `backend/app/agent/` so that one chunk of terms-of-service text goes in and a score of 0–2 for each of the six clause categories comes out, in a single LLM forward pass.

**Architecture:** A PydanticAI agent runs against a local Ollama server using schema-constrained decoding. The model emits only the categories it finds, each with a verbatim quote from the chunk; an output validator checks those quotes against the source text and the agent then expands the sparse result to all six categories. Pure transforms (normalization, quote matching, dedupe, densify) live in their own modules so they are testable without an LLM.

**Tech Stack:** Python 3.11+, PydanticAI 2.21, Pydantic v2, Ollama (`qwen2.5:7b-instruct`), pytest.

**Design spec:** `docs/superpowers/specs/2026-08-02-tos-clause-classifier-design.md`

## Global Constraints

- Scope is `backend/app/agent/` only. Do not touch `app/services/`, `app/api/`, `app/db/`, or `app/models/`. Chunking, caching, per-category max across chunks, and verdict computation are owned by `app/services/analysis.py` and are out of scope.
- Layer rule from `backend/README.md`: `app/agent/` must not import from `app.services`, `app.db`, `app.api`, or `app.models`. It may import from `app.core`.
- `app/agent/categories.py` is the single source of truth for category text. Do not duplicate category copy into `prompts.toml`.
- `display_name` and `description` on `CategorySpec` are product voice for humans and **must never be sent to the model**. Only `detection`, `standard`, `aggressive`, and `boundaries` go into the prompt.
- Category slugs are frozen. Do not add, rename, or remove a `ClauseCategory` member.
- The model-facing schema stays flat: enums, ints, strings, one list of one object type. No unions, no `$ref` nesting. Ollama constrains decoding against the schema but does not implement OpenAI `strict` mode, and adherence degrades on complex schemas.
- Unit tests must not require a running Ollama server. Anything needing a live model belongs in `tests/integration.py`.
- All tests live in `tests/unit.py`. Run from the `backend/` directory.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/pyproject.toml` (modify) | Add pytest `python_files` so the team's `tests/*.py` layout is discovered. |
| `backend/app/agent/output.py` (modify) | Model-facing and agent-facing schemas, plus the pure `dedupe`/`densify` transforms between them. |
| `backend/app/agent/evidence.py` (create) | Text normalization and verbatim-quote matching. Pure, no PydanticAI import. |
| `backend/app/agent/prompts/prompts.toml` (modify) | System-prompt template and the one few-shot example. Template only — no category copy. |
| `backend/app/agent/classifier.py` (modify) | Prompt loading and rendering, the evidence validator, agent construction, `classify_chunk`. |
| `tests/unit.py` (modify) | Unit tests for every pure transform plus agent construction. |

---

### Task 1: Enable pytest discovery

`tests/unit.py` does not match pytest's default `python_files` pattern of `test_*.py`, so the existing tests are collected zero times and silently never run. Every later task in this plan depends on being able to run tests, so this comes first.

`backend/pyproject.toml` is shared with teammates. This is a one-line addition that makes their `tests/` layout work as intended; it changes no existing setting.

**Files:**
- Modify: `backend/pyproject.toml` (the `[tool.pytest.ini_options]` table)

**Interfaces:**
- Consumes: nothing
- Produces: a working `uv run pytest` from `backend/`

- [ ] **Step 1: Confirm the problem**

Run from `backend/`:

```bash
cd backend && uv run pytest --collect-only -q
```

Expected: `no tests collected`

- [ ] **Step 2: Add the discovery pattern**

In `backend/pyproject.toml`, change the `[tool.pytest.ini_options]` table to:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["../tests"]
# The team's test files are named by kind (unit, integration, system, ...),
# which does not match pytest's default `test_*.py` discovery pattern.
python_files = ["unit.py", "integration.py", "system.py", "security.py", "stress.py"]
```

- [ ] **Step 3: Verify collection works**

```bash
cd backend && uv run pytest -q
```

Expected: `5 passed` — the existing `categories.py` tests now run.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "test: collect the tests/ files pytest was silently skipping"
```

---

### Task 2: Output schemas

Two distinct model registers. `Finding`/`ChunkFindings` are what the LLM emits — sparse, only the categories actually found. `ClauseScore`/`ChunkClassification` are what the agent returns — dense, all six.

`score: Literal[1, 2]` on `Finding` is the mechanism that makes sparseness structural: the model cannot emit a zero, so "absent" and "omitted" are one representation rather than two.

Field order inside `Finding` is load-bearing. Under constrained decoding the model generates fields in schema order and cannot backtrack, so `evidence` is declared before `score` — it quotes the clause, then judges the quote it just wrote.

**Files:**
- Modify: `backend/app/agent/output.py`
- Test: `tests/unit.py`

**Interfaces:**
- Consumes: `ClauseCategory` from `app.agent.categories`
- Produces: `Finding`, `ChunkFindings`, `ClauseScore`, `ChunkClassification`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit.py`:

```python
import pytest
from pydantic import ValidationError

from app.agent.output import ChunkFindings, ClauseScore, Finding


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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest ../tests/unit.py -q -k "finding or clause_score or chunk_findings"
```

Expected: FAIL — `ImportError: cannot import name 'Finding' from 'app.agent.output'`

- [ ] **Step 3: Write the implementation**

Replace the whole contents of `backend/app/agent/output.py` with:

```python
"""Structured output schemas for the classifier.

Two registers, deliberately distinct.

``Finding``/``ChunkFindings`` are what the model emits: sparse, carrying only
the categories the chunk actually addresses. ``score`` is ``Literal[1, 2]`` so a
zero is unrepresentable — absence is expressed by omitting the category. That
saves roughly five-sixths of the output tokens on a typical chunk and stops a
small model inventing prose to justify zeros.

``ClauseScore``/``ChunkClassification`` are what the agent returns: dense, all
six categories, zeros filled in by ``densify``.

Field order inside ``Finding`` is load-bearing. Under constrained decoding the
model emits fields in schema order and cannot backtrack, so ``evidence`` comes
before ``score``: quote the clause, then judge the quote.
"""

from typing import Literal

from pydantic import BaseModel

from app.agent.categories import ClauseCategory


class Finding(BaseModel):
    """One category the model found in a chunk. Model-facing schema."""

    category: ClauseCategory
    evidence: str
    score: Literal[1, 2]
    explanation: str


class ChunkFindings(BaseModel):
    """Raw model output: only the categories the chunk addresses."""

    findings: list[Finding]


class ClauseScore(BaseModel):
    """One category after densifying. Agent-facing schema."""

    category: ClauseCategory
    score: int
    evidence: str | None = None
    explanation: str | None = None


class ChunkClassification(BaseModel):
    """What ``classify_chunk`` returns: every category, always."""

    scores: list[ClauseScore]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest ../tests/unit.py -q
```

Expected: PASS, 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/output.py tests/unit.py
git commit -m "feat(agent): sparse model-facing and dense agent-facing schemas"
```

---

### Task 3: Dedupe and densify

The model can report the same category twice in one chunk (a section mentioning arbitration in two paragraphs). `dedupe` collapses that to the highest score, matching the max-across-chunks reduction `services` applies one level up. `densify` then expands the sparse list to one `ClauseScore` per category in `ClauseCategory` declaration order.

**Files:**
- Modify: `backend/app/agent/output.py`
- Test: `tests/unit.py`

**Interfaces:**
- Consumes: `Finding`, `ChunkFindings`, `ClauseScore`, `ChunkClassification` from Task 2; `SCORE_ABSENT` from `app.agent.categories`
- Produces: `dedupe(findings: list[Finding]) -> list[Finding]`, `densify(findings: list[Finding]) -> ChunkClassification`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit.py`:

```python
from app.agent.categories import SCORE_ABSENT
from app.agent.output import densify, dedupe


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


def test_densify_fills_absent_categories_with_zero_and_no_evidence() -> None:
    result = densify([_finding(ClauseCategory.ARBITRATION)])
    absent = [s for s in result.scores if s.category is not ClauseCategory.ARBITRATION]
    assert all(s.score == SCORE_ABSENT for s in absent)
    assert all(s.evidence is None and s.explanation is None for s in absent)


def test_densify_preserves_reported_findings() -> None:
    result = densify([_finding(ClauseCategory.LIABILITY, score=1)])
    liability = next(s for s in result.scores if s.category is ClauseCategory.LIABILITY)
    assert liability.score == 1
    assert liability.evidence == "evidence for liability"
    assert liability.explanation == "explanation for liability"


def test_densify_of_nothing_is_six_zeros() -> None:
    result = densify([])
    assert len(result.scores) == len(ClauseCategory)
    assert all(s.score == SCORE_ABSENT for s in result.scores)


def test_evidence_is_present_exactly_when_score_is_nonzero() -> None:
    result = densify([_finding(ClauseCategory.TERMINATION, score=1)])
    for score in result.scores:
        assert (score.evidence is not None) == (score.score > SCORE_ABSENT)


def test_dedupe_keeps_the_highest_score_per_category() -> None:
    findings = [
        _finding(ClauseCategory.ARBITRATION, score=1),
        _finding(ClauseCategory.ARBITRATION, score=2),
    ]
    deduped = dedupe(findings)
    assert len(deduped) == 1
    assert deduped[0].score == 2


def test_densify_dedupes_before_expanding() -> None:
    findings = [
        _finding(ClauseCategory.DATA_COLLECTION, score=2),
        _finding(ClauseCategory.DATA_COLLECTION, score=1),
    ]
    result = densify(findings)
    data = next(s for s in result.scores if s.category is ClauseCategory.DATA_COLLECTION)
    assert data.score == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest ../tests/unit.py -q -k "densify or dedupe or evidence_is_present"
```

Expected: FAIL — `ImportError: cannot import name 'densify' from 'app.agent.output'`

- [ ] **Step 3: Write the implementation**

Replace the existing `from app.agent.categories import ClauseCategory` line at the top of `backend/app/agent/output.py` with:

```python
from app.agent.categories import SCORE_ABSENT, ClauseCategory
```

Append to `backend/app/agent/output.py`:

```python
def dedupe(findings: list[Finding]) -> list[Finding]:
    """Collapse repeated categories to the highest-scoring finding.

    A chunk can address the same category in more than one paragraph. Taking
    the max here mirrors the max-across-chunks reduction ``services`` applies
    one level up.
    """
    best: dict[ClauseCategory, Finding] = {}
    for finding in findings:
        current = best.get(finding.category)
        if current is None or finding.score > current.score:
            best[finding.category] = finding
    return list(best.values())


def densify(findings: list[Finding]) -> ChunkClassification:
    """Expand sparse findings to one ``ClauseScore`` per category.

    Categories the model did not report score ``SCORE_ABSENT`` with no evidence
    and no explanation. Output is always in ``ClauseCategory`` declaration
    order so downstream consumers can rely on it.
    """
    by_category = {finding.category: finding for finding in dedupe(findings)}
    scores: list[ClauseScore] = []
    for category in ClauseCategory:
        found = by_category.get(category)
        if found is None:
            scores.append(ClauseScore(category=category, score=SCORE_ABSENT))
        else:
            scores.append(
                ClauseScore(
                    category=category,
                    score=found.score,
                    evidence=found.evidence,
                    explanation=found.explanation,
                )
            )
    return ChunkClassification(scores=scores)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest ../tests/unit.py -q
```

Expected: PASS, 18 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/output.py tests/unit.py
git commit -m "feat(agent): dedupe and densify sparse findings to all six categories"
```

---

### Task 4: Evidence normalization and matching

Models routinely re-type a quote with straightened quote glyphs, an en dash flattened to a hyphen, or a line break collapsed to a space. A raw `evidence in chunk` test would reject quotes that are substantively correct, so both sides are normalized before comparison.

This module stays free of PydanticAI imports so it is trivially testable and reusable.

**Files:**
- Create: `backend/app/agent/evidence.py`
- Test: `tests/unit.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `normalize(text: str) -> str`, `is_verbatim(evidence: str, chunk: str) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit.py`:

```python
from app.agent.evidence import is_verbatim, normalize

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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest ../tests/unit.py -q -k "normalize or verbatim"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.evidence'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/agent/evidence.py`:

```python
"""Verbatim-evidence checking for classifier output.

The classifier requires the model to quote the words that justify a score, so
that a hallucinated finding is detectable — a quote either appears in the chunk
or it does not, whereas a paraphrase can never be checked.

Enforcing that literally would fail on quotes that are substantively correct:
models retype curly quotes as straight ones, flatten en and em dashes, and fold
a line break into a space. Both sides are normalized before comparison so those
differences do not count against the model, while an invented or paraphrased
quote still fails.
"""

import re

_GLYPHS = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
    }
)

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Straighten quote and dash glyphs, collapse whitespace runs, casefold."""
    return _WHITESPACE.sub(" ", text.translate(_GLYPHS)).strip().casefold()


def is_verbatim(evidence: str, chunk: str) -> bool:
    """True if ``evidence`` appears in ``chunk`` once both are normalized.

    Empty or whitespace-only evidence is rejected: it would otherwise match
    every chunk, since the empty string is a substring of anything.
    """
    normalized = normalize(evidence)
    if not normalized:
        return False
    return normalized in normalize(chunk)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest ../tests/unit.py -q
```

Expected: PASS, 29 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/evidence.py tests/unit.py
git commit -m "feat(agent): normalized verbatim-evidence matching"
```

---

### Task 5: Prompt template and rendering

The TOML file holds the template and the single few-shot example. Category text is **not** duplicated into it — it is rendered from `CATEGORY_SPECS` at load time so `categories.py` stays the single source of truth.

Only the neutral prompt fields go to the model. `display_name` and `description` are product voice and are deliberately excluded; loaded framing biases a small model toward finding aggression everywhere.

The rendered prompt is a stable prefix across every chunk, so Ollama reuses its KV cache for it.

**Files:**
- Modify: `backend/app/agent/prompts/prompts.toml`
- Modify: `backend/app/agent/classifier.py`
- Test: `tests/unit.py`

**Interfaces:**
- Consumes: `CATEGORY_SPECS`, `SCORE_SCALE`, `SCORE_STANDARD`, `SCORE_AGGRESSIVE`, `ClauseCategory` from `app.agent.categories`
- Produces: `load_prompts() -> dict[str, Any]`, `render_score_scale() -> str`, `render_categories() -> str`, `render_system_prompt() -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit.py`:

```python
from app.agent.classifier import (
    load_prompts,
    render_categories,
    render_score_scale,
    render_system_prompt,
)


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
```

Add `SCORE_SCALE` and `CATEGORY_SPECS` to the existing `app.agent.categories` import at the top of `tests/unit.py` if they are not already imported.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest ../tests/unit.py -q -k "prompt or example or score_scale or categories"
```

Expected: FAIL — `ImportError: cannot import name 'render_system_prompt' from 'app.agent.classifier'`

- [ ] **Step 3: Write the prompt file**

Replace the whole contents of `backend/app/agent/prompts/prompts.toml` with:

```toml
# Prompt template and few-shot example for the TOS clause classifier.
#
# Category text is NOT duplicated here. `classifier.render_system_prompt`
# injects it from `app.agent.categories`, which stays the single source of
# truth. Only the neutral fields (detection / standard / aggressive /
# boundaries) are rendered; display_name and description are product voice for
# humans and must not reach the model.

[system]
prompt = """
You classify one excerpt from a terms-of-service document.

Report every category listed below that the excerpt actually addresses. For
each one, quote the exact words from the excerpt that show it, then score it.

Scoring scale:
{score_scale}

Report only categories the excerpt addresses. Leaving a category out is how you
say it is absent — there is no score of 0 for you to report.

The `evidence` field must be copied word for word from the excerpt. Do not
paraphrase it, shorten it, or tidy up its punctuation. If you cannot quote the
words, do not report the category.

Judge the excerpt against what mainstream consumer services do, not against
what would be ideal for the user. Most clauses are ordinary and score 1.

Categories:
{categories}

Example excerpt:
{example_text}

Example output:
{example_output}
"""

[[few_shot.examples]]
text = """
9. Changes to these Terms. We may revise these Terms at any time by posting the revised version on our website. Revisions take effect immediately upon posting, and your continued use of the Service after that time constitutes your acceptance of them.

10. Cancellation. You may cancel your subscription at any time from the account settings page. We will send you an email reminder seven days before each annual renewal charge.
"""
findings = [
  { category = "unilateral_changes", evidence = "Revisions take effect immediately upon posting, and your continued use of the Service after that time constitutes your acceptance of them.", score = 2, explanation = "Changes bind the user the moment they are posted, with no direct notice and no window to reject them; continued use is deemed acceptance." },
  { category = "termination", evidence = "You may cancel your subscription at any time from the account settings page. We will send you an email reminder seven days before each annual renewal charge.", score = 1, explanation = "Self-serve cancellation with an advance reminder before the renewal charge — ordinary consumer terms." },
]
```

- [ ] **Step 4: Write the rendering code**

Replace the contents of `backend/app/agent/classifier.py` with:

```python
"""TOS chunk classifier: PydanticAI agent against Ollama.

Plain text in, structured scores out. No cache, db, or preference awareness.
"""

import json
import tomllib
from functools import lru_cache
from importlib import resources
from typing import Any

from app.agent.categories import (
    CATEGORY_SPECS,
    SCORE_AGGRESSIVE,
    SCORE_SCALE,
    SCORE_STANDARD,
    ClauseCategory,
)

PROMPTS_PACKAGE = "app.agent.prompts"
PROMPTS_FILE = "prompts.toml"


@lru_cache
def load_prompts() -> dict[str, Any]:
    """Load the prompt template and few-shot examples from package data."""
    text = (
        resources.files(PROMPTS_PACKAGE).joinpath(PROMPTS_FILE).read_text("utf-8")
    )
    return tomllib.loads(text)


def render_score_scale() -> str:
    """Render the 0-2 scale as prompt lines."""
    return "\n".join(
        f"- {score}: {meaning}" for score, meaning in sorted(SCORE_SCALE.items())
    )


def render_categories() -> str:
    """Render the neutral half of every ``CategorySpec``.

    ``display_name`` and ``description`` are deliberately excluded: they carry
    the product voice, and loaded framing biases a small model toward finding
    aggression everywhere.
    """
    blocks: list[str] = []
    for category in ClauseCategory:
        spec = CATEGORY_SPECS[category]
        boundaries = "\n".join(f"  - {rule}" for rule in spec.boundaries)
        blocks.append(
            f"### {category.value}\n"
            f"What counts: {spec.detection}\n"
            f"Score {SCORE_STANDARD} when: {spec.standard}\n"
            f"Score {SCORE_AGGRESSIVE} when: {spec.aggressive}\n"
            f"Boundaries:\n{boundaries}"
        )
    return "\n\n".join(blocks)


@lru_cache
def render_system_prompt() -> str:
    """Build the system prompt: template + score scale + specs + example.

    Stable across every chunk, so Ollama reuses its KV cache for the prefix.
    """
    prompts = load_prompts()
    example = prompts["few_shot"]["examples"][0]
    return prompts["system"]["prompt"].format(
        score_scale=render_score_scale(),
        categories=render_categories(),
        example_text=example["text"].strip(),
        example_output=json.dumps({"findings": example["findings"]}, indent=2),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && uv run pytest ../tests/unit.py -q
```

Expected: PASS, 40 passed.

- [ ] **Step 6: Check the prompt size against the budget**

The spec budgets roughly 1.3k tokens of system prompt so a 3k-token chunk fits comfortably.

```bash
cd backend && uv run python -c "
from app.agent.classifier import render_system_prompt
p = render_system_prompt()
print('chars:', len(p), '~tokens:', len(p) // 4)
"
```

Expected: roughly 5,000–7,000 characters, about 1,200–1,750 tokens. If it comes out above ~2,500 tokens, stop and report it rather than trimming `categories.py` — the specs are frozen team-facing text.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/prompts/prompts.toml backend/app/agent/classifier.py tests/unit.py
git commit -m "feat(agent): system prompt rendered from the category specs"
```

---

### Task 6: Evidence validator

The retry-then-drop policy, written as a pure function so it is testable without an LLM. The agent wiring in Task 7 is a thin adapter over it.

On the first failing attempt it raises `ModelRetry` naming the offending categories. If the retry still fails, the offending findings are dropped — they densify to score 0 — and the rest of the chunk's findings survive. Dropping rather than raising keeps one stubborn quote from discarding an entire chunk, and avoids forcing `services` to decide whether a partly failed document is cacheable.

**Files:**
- Modify: `backend/app/agent/classifier.py`
- Test: `tests/unit.py`

**Interfaces:**
- Consumes: `Finding` from Task 2, `is_verbatim` from Task 4
- Produces: `MAX_EVIDENCE_RETRIES: int`, `check_evidence(findings: list[Finding], chunk: str, retry: int) -> list[Finding]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit.py`:

```python
from pydantic_ai import ModelRetry

from app.agent.classifier import MAX_EVIDENCE_RETRIES, check_evidence

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
    assert arbitration.evidence is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest ../tests/unit.py -q -k "check_evidence or retry_message or dropping or dropped"
```

Expected: FAIL — `ImportError: cannot import name 'check_evidence' from 'app.agent.classifier'`

- [ ] **Step 3: Write the implementation**

Add to the imports at the top of `backend/app/agent/classifier.py`:

```python
import logging

from pydantic_ai import ModelRetry

from app.agent.evidence import is_verbatim
from app.agent.output import Finding
```

Add after the imports:

```python
logger = logging.getLogger(__name__)

MAX_EVIDENCE_RETRIES = 1
```

Append to `backend/app/agent/classifier.py`:

```python
def check_evidence(
    findings: list[Finding], chunk: str, retry: int
) -> list[Finding]:
    """Enforce that every finding quotes the chunk verbatim.

    Constrained decoding guarantees the output is schema-shaped; it says
    nothing about whether the quote is real. This is that check.

    On the first failing attempt the model is asked to try again, with the
    offending categories named. If it fails again, the offending findings are
    dropped — they densify to a score of 0 — so that one stubborn quote does
    not cost the chunk its other findings.
    """
    bad = [f for f in findings if not is_verbatim(f.evidence, chunk)]
    if not bad:
        return findings

    if retry < MAX_EVIDENCE_RETRIES:
        names = ", ".join(sorted(f.category.value for f in bad))
        raise ModelRetry(
            f"The evidence given for these categories does not appear in the "
            f"excerpt: {names}. Copy the exact words from the excerpt, or leave "
            f"the category out."
        )

    for finding in bad:
        logger.warning(
            "dropping %s: evidence not found in chunk", finding.category.value
        )
    dropped = {id(f) for f in bad}
    return [f for f in findings if id(f) not in dropped]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest ../tests/unit.py -q
```

Expected: PASS, 47 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/classifier.py tests/unit.py
git commit -m "feat(agent): retry-then-drop evidence validation"
```

---

### Task 7: Agent construction and `classify_chunk`

The remaining wiring. `NativeOutput` is used instead of PydanticAI's default tool calling: it sends the schema in `response_format` and Ollama constrains decoding against it, so an invalid category value or a non-integer score is never sampleable. Tool calling is ordinary generation validated after the fact, and each failure costs another full forward pass — a path 7B models hit often on a six-way enum.

`base_url` must carry a `/v1` suffix. `OllamaProvider` passes it straight to `AsyncOpenAI` with no path manipulation, and `settings.ollama_base_url` is the bare host.

`temperature=0` because analyses are cached on `text_hash + model_version`; the same document must not score differently across runs.

Unit tests here cover construction only — no network. Behaviour against a live model belongs in `tests/integration.py`.

**Files:**
- Modify: `backend/app/agent/classifier.py`
- Test: `tests/unit.py`

**Interfaces:**
- Consumes: `check_evidence`, `render_system_prompt` from Tasks 5 and 6; `ChunkFindings`, `ChunkClassification`, `densify` from Tasks 2 and 3; `settings` from `app.core.config`
- Produces: `build_agent() -> Agent[str, ChunkFindings]`, `async classify_chunk(text: str) -> ChunkClassification`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit.py`:

```python
from pydantic_ai import Agent

from app.agent.classifier import build_agent
from app.agent.output import ChunkClassification


def test_build_agent_returns_an_agent() -> None:
    assert isinstance(build_agent(), Agent)


def test_build_agent_is_cached() -> None:
    """One agent per process — rebuilding re-renders the prompt every call."""
    assert build_agent() is build_agent()


def test_classify_chunk_is_async() -> None:
    import inspect

    from app.agent.classifier import classify_chunk

    assert inspect.iscoroutinefunction(classify_chunk)


def test_classify_chunk_returns_all_six_categories(monkeypatch) -> None:
    """The dense contract holds regardless of what the model reported."""
    from app.agent import classifier

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

    import asyncio

    result = asyncio.run(classifier.classify_chunk("You agree to binding arbitration."))
    assert isinstance(result, ChunkClassification)
    assert [s.category for s in result.scores] == list(ClauseCategory)
    arbitration = next(
        s for s in result.scores if s.category is ClauseCategory.ARBITRATION
    )
    assert arbitration.score == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest ../tests/unit.py -q -k "build_agent or classify_chunk"
```

Expected: FAIL — `ImportError: cannot import name 'build_agent' from 'app.agent.classifier'`

- [ ] **Step 3: Write the implementation**

Add to the imports at the top of `backend/app/agent/classifier.py`:

```python
from pydantic_ai import Agent, NativeOutput, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings

from app.agent.output import ChunkClassification, ChunkFindings, densify
from app.core.config import settings
```

Append to `backend/app/agent/classifier.py`:

```python
@lru_cache
def build_agent() -> Agent[str, ChunkFindings]:
    """Construct the classifier agent. Cached — one per process.

    ``deps_type=str`` carries the chunk text so the output validator can check
    quoted evidence against the source.

    ``NativeOutput`` sends the schema in ``response_format`` so Ollama
    constrains decoding against it, rather than PydanticAI's default tool
    calling, which validates after the fact and pays a full forward pass per
    failure.
    """
    model = OpenAIChatModel(
        settings.agent_model,
        provider=OllamaProvider(base_url=f"{settings.ollama_base_url.rstrip('/')}/v1"),
    )
    agent = Agent(
        model,
        deps_type=str,
        output_type=NativeOutput(ChunkFindings),
        instructions=render_system_prompt(),
        retries=MAX_EVIDENCE_RETRIES,
        model_settings=ModelSettings(temperature=0.0),
    )

    @agent.output_validator
    def _validate_evidence(
        ctx: RunContext[str], output: ChunkFindings
    ) -> ChunkFindings:
        return ChunkFindings(
            findings=check_evidence(output.findings, ctx.deps, ctx.retry)
        )

    return agent


async def classify_chunk(text: str) -> ChunkClassification:
    """Classify one TOS chunk against all clause categories.

    Returns a score for every category, including the ones the model did not
    report. ``deps`` is the raw chunk, so evidence is checked against exactly
    the text the model was shown.
    """
    result = await build_agent().run(f"Excerpt:\n{text}", deps=text)
    return densify(result.output.findings)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest ../tests/unit.py -q
```

Expected: PASS, 51 passed.

- [ ] **Step 5: Verify the layer rules still hold**

`app/agent/` must not import from services, db, api, or models.

```bash
cd backend && grep -rnE "from app\.(services|db|api|models)" app/agent/ || echo "layer rules OK"
```

Expected: `layer rules OK`

- [ ] **Step 6: Lint and type-check**

```bash
cd backend && uv run ruff check app/agent/ && uv run mypy app/agent/
```

Expected: both clean. If `mypy` objects to the `Agent[str, ChunkFindings]` annotation on `build_agent`, report the exact message rather than loosening the type to `Agent` — the parametrisation documents the deps contract.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/classifier.py tests/unit.py
git commit -m "feat(agent): Ollama agent construction and classify_chunk"
```

---

## Deferred to integration testing

These need a running Ollama with `qwen2.5:7b-instruct` pulled, and belong in `tests/integration.py`, not `tests/unit.py`. The Ollama binary is installed on this machine but the server was not responding when this plan was written.

- Whether `NativeOutput` round-trips `Literal[1, 2]` cleanly through Ollama's JSON-schema handling, or whether it must be widened to a plain `int` with a Pydantic-side constraint. This is the one open item from the spec.
- Whether the model honours sparseness in practice, or reports categories the excerpt does not address.
- Whether `evidence` comes back verbatim often enough that the retry path stays rare.
- End-to-end latency per chunk, which determines the concurrency limit `services` should use against `OLLAMA_NUM_PARALLEL`.
