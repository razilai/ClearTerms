"""Structured output schema enforced by PydanticAI on the classifier."""

from pydantic import BaseModel

from app.agent.categories import ClauseCategory


class ClauseScore(BaseModel):
    category: ClauseCategory
    score: int
    explanation: str


class ChunkClassification(BaseModel):
    scores: list[ClauseScore]
