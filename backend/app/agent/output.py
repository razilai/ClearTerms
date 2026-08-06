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

from app.agent.categories import SCORE_ABSENT
from app.schemas.analysis import (
    ChunkClassification,
    ClauseCategory,
    ClauseScore,
    Finding,
)


def drop_duplicate_findings(findings: list[Finding]) -> list[Finding]:
    """Remove byte-identical repeats, preserving order.

    A chunk addressing the same category in two paragraphs is real and both
    findings are kept. Two findings identical in every field are not two
    clauses — they are the model emitting the same one twice.
    """
    seen: set[tuple[str, str, int, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (
            finding.category.value,
            finding.evidence,
            finding.score,
            finding.explanation,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def densify(findings: list[Finding]) -> ChunkClassification:
    """Expand sparse findings to one ``ClauseScore`` per category.

    Every finding survives — a category found three times keeps all three, in
    the order the model reported them. ``score`` is their max; categories the
    model did not report score ``SCORE_ABSENT`` with an empty findings list.
    Output is always in ``ClauseCategory`` declaration order so downstream
    consumers can rely on it.
    """
    by_category: dict[ClauseCategory, list[Finding]] = {c: [] for c in ClauseCategory}
    for finding in drop_duplicate_findings(findings):
        by_category[finding.category].append(finding)

    return ChunkClassification(
        scores=[
            ClauseScore(
                category=category,
                score=max(
                    (f.score for f in by_category[category]), default=SCORE_ABSENT
                ),
                findings=by_category[category],
            )
            for category in ClauseCategory
        ]
    )
