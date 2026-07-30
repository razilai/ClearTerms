from datetime import datetime

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
