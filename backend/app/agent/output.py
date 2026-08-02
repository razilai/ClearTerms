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
