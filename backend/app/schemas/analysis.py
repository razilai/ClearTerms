from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    text: str
    url: str | None = None


class FindingOut(BaseModel):
    """One quoted clause on the wire — mirrors an ``app.models.Finding`` row.

    Deliberately not the ``Finding`` defined below. That one is a prompt
    contract: its JSON schema is what constrains Ollama's decoding, its field
    order is load-bearing, and its ``Literal[1, 2]`` score exists to make zero
    unrepresentable. This one answers to the frontend instead, and the two are
    free to diverge.
    """

    evidence: str
    score: int
    explanation: str


class CategoryScore(BaseModel):
    # ``category``/``score`` stay str/int rather than ClauseCategory/Literal:
    # this mirrors the ``Analysis`` row's plain columns, so a detail response for
    # a document scored under an older, since-renamed slug still serializes
    # instead of 500ing on a value the current enum no longer names.
    category: str
    score: int
    # Every clause found for this category, not just the worst — ``score`` is
    # their max. Defaults to empty so an absent category serializes as [], not
    # null, and callers can iterate without a null check.
    findings: list[FindingOut] = []


class VerdictResponse(BaseModel):
    verdict: str
    analysis_id: int


# Final output of GET /analyses/{id}. ``id`` is the document id (the cache is
# keyed per document, so analysis_id == document_id); kept in the body so the
# response is self-describing and the frontend can link/key on it without
# threading the path param back through.
class AnalysisDetail(BaseModel):
    id: int
    url: str | None
    scores: list[CategoryScore]
    model_version: str
    created_at: datetime


# Canonical definition of the clause taxonomy. Lives here (a pure leaf) so the
# model-facing Finding schema below and the wire contracts stay free of
# app.agent.categories' import-time TOML loading; that module re-exports this
# and owns the surrounding prose/score anchors.
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
