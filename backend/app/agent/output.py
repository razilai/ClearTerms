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

from app.agent.categories import SCORE_ABSENT, ClauseCategory


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
