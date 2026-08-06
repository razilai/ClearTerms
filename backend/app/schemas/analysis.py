from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    text: str
    url: str | None = None


class CategoryScore(BaseModel):
    category: str
    score: int
    explanation: str | None = None


class VerdictResponse(BaseModel):
    verdict: str
    analysis_id: int


class AnalysisDetail(BaseModel):
    id: int
    url: str | None
    scores: list[CategoryScore]
    model_version: str
    created_at: datetime


# moved from agent/output.py here to stay consistant with pydantic schemas


class ClauseCategory(StrEnum):
    UNILATERAL_CHANGES = "unilateral_changes"
    ARBITRATION = "arbitration"
    LIABILITY = "liability"
    CONTENT_LICENSING = "content_licensing"
    DATA_COLLECTION = "data_collection"
    TERMINATION = "termination"


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
    """One category after densifying. Agent-facing schema.

    ``findings`` holds every clause the chunk contained for this category, not
    just the worst one: a TOS with four separate predatory arbitration
    provisions should be able to show all four. ``score`` is their max, kept
    because the verdict math in ``services`` needs one number per category and
    should not have to recompute it.
    """

    category: ClauseCategory
    score: int
    findings: list[Finding] = []


class ChunkClassification(BaseModel):
    """What ``classify_chunk`` returns: every category, always."""

    scores: list[ClauseScore]
