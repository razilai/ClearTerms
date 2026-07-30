from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.analysis import AnalysisDetail, AnalyzeRequest, VerdictResponse

# Handlers delegate to app.services.analysis — no business logic here.
router = APIRouter(tags=["analysis"])


@router.post("/analyze", response_model=VerdictResponse)
async def analyze(
    body: AnalyzeRequest, session: SessionDep, user: CurrentUserDep
) -> VerdictResponse:
    # TODO: reject bodies over settings.max_analyze_bytes (413)
    raise NotImplementedError


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail)
async def get_analysis(
    analysis_id: int, session: SessionDep, user: CurrentUserDep
) -> AnalysisDetail:
    raise NotImplementedError
