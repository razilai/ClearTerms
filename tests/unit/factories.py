"""Shared factories for the unit tier: ORM rows and preference items."""


from app.models import Analysis, Finding, Preference
from app.schemas.preferences import PreferenceItem

MODEL_V1 = "test-model-v1"
MODEL_V2 = "test-model-v2"


def _analysis(
    document_id: int,
    category: str,
    *,
    score: int = 1,
    model_version: str = MODEL_V1,
    findings: list[Finding] | None = None,
) -> Analysis:
    return Analysis(
        document_id=document_id,
        category=category,
        score=score,
        model_version=model_version,
        findings=[] if findings is None else findings,
    )


def _finding(evidence: str, *, score: int = 2, explanation: str = "why") -> Finding:
    """A Finding with no analysis_id — the relationship cascade fills it in."""
    return Finding(evidence=evidence, score=score, explanation=explanation)


def _preference(user_id: int, category: str, enabled: bool = True) -> Preference:
    return Preference(user_id=user_id, category=category, enabled=enabled)


def _items(*pairs: tuple[str, bool]) -> list[PreferenceItem]:
    return [PreferenceItem(category=c, enabled=e) for c, e in pairs]
