"""Analysis pipeline orchestration (preference-independent).

Steps: normalize text -> hash -> cache lookup. On miss: clean, chunk by TOS
section headings (fallback ~3k-token windows, ~200-token overlap), call
app.agent to classify each chunk against all clause categories, take per-category
max across chunks, persist to the Analysis cache keyed by text_hash + model_version.

Owns the seam between the LLM (app.agent) and the rest of the system: the agent
receives plain text and returns structured scores; cache/db/preferences live here.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, Document


async def analyze(
    session: AsyncSession, user_id: int, text: str, url: str | None
) -> tuple[str, int]:
    """Full pipeline for POST /analyze. Returns (verdict, document_id).

    normalize -> hash -> cache lookup; on miss submit run_analysis via
    app.services.queue; then compute_verdict against the user's preferences
    and append a history entry.
    """
    raise NotImplementedError


async def get_analysis_detail(
    session: AsyncSession, user_id: int, document_id: int
) -> tuple[Document, list[Analysis]]:
    """Per-category breakdown for GET /analyses/{id}; raise if not found."""
    raise NotImplementedError


async def run_analysis(session: AsyncSession, document: Document) -> list[Analysis]:
    """Cache-miss path: clean, chunk, fan out to app.agent.classifier per chunk,
    per-category max across chunks, persist Analysis rows (model_version from
    settings)."""
    raise NotImplementedError


def normalize_text(text: str) -> str:
    """Canonical form used for hashing (whitespace/case/unicode normalization)."""
    raise NotImplementedError


def compute_hash(normalized: str) -> str:
    raise NotImplementedError


def chunk_text(cleaned: str) -> list[str]:
    """Split by TOS section headings; fallback to settings.chunk_tokens windows
    with settings.chunk_overlap_tokens overlap."""
    raise NotImplementedError
