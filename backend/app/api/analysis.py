from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, SessionDep
from app.core.config import settings
from app.schemas.analysis import (
    AnalysisDetail,
    AnalyzeRequest,
    CategoryScore,
    VerdictResponse,
)
from app.services import analysis as analysis_service

# Handlers delegate to app.services.analysis — no business logic here.
router = APIRouter(tags=["analysis"])


@router.post("/analyze", response_model=VerdictResponse)
async def analyze(
    body: AnalyzeRequest, session: SessionDep, user: CurrentUserDep
) -> VerdictResponse:
    if len(body.text.encode("utf-8")) > settings.max_analyze_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Document too large to analyze",
        )
    # analysis_id carries the document_id: the analysis cache is keyed per
    # document, and GET /analyses/{id} looks up by that id.
    verdict, document_id = await analysis_service.analyze(
        session, user.id, body.text, body.url
    )
    return VerdictResponse(verdict=verdict, analysis_id=document_id)


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail)
async def get_analysis(
    analysis_id: int, session: SessionDep, user: CurrentUserDep
) -> AnalysisDetail:
    document, analyses = await analysis_service.get_analysis_detail(
        session, user.id, analysis_id
    )
    # The detail repo returns every stored version; show only the current model.
    current = [a for a in analyses if a.model_version == settings.model_version]
    return AnalysisDetail(
        id=document.id,
        url=document.url,
        scores=[
            CategoryScore(
                category=a.category, score=a.score, explanation=a.explanation
            )
            for a in current
        ],
        model_version=settings.model_version,
        created_at=document.created_at,
    )
