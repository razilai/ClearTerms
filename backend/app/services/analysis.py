"""Analysis pipeline orchestration (preference-independent).

Steps: normalize text -> hash -> cache lookup. On miss: create the Document,
hand the normalized text to app.agent (which cleans, chunks, and takes the
per-category max across chunks itself), and persist the returned scores to the
Analysis cache keyed by document_id + model_version.

Owns the seam between the LLM (app.agent) and the rest of the system: the agent
receives plain text and returns structured scores; cache/db/preferences live here.
"""

import hashlib
import unicodedata

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import classifier
from app.core.config import settings
from app.db.repos import documents as documents_repo
from app.db.repos import history as history_repo
from app.db.repos import preferences as preferences_repo
from app.models import Analysis, Document
from app.services.exceptions import NotFoundError
from app.services.preferences import compute_verdict
from app.services.queue import queue


async def analyze(
    session: AsyncSession, user_id: int, text: str, url: str | None
) -> tuple[str, int]:
    """Full pipeline for POST /analyze. Returns (verdict, document_id).

    normalize -> hash -> cache lookup; on miss submit run_analysis via
    app.services.queue; then compute_verdict against the user's preferences
    and append a history entry.
    """
    normalized = normalize_text(text)
    text_hash = compute_hash(normalized)

    document = await documents_repo.get_by_hash(session, text_hash)
    if document is None:
        document = await documents_repo.create(
            session, text_hash, url, normalized, original_text=text
        )

    # Cache is keyed by (document, model_version): a document analyzed under an
    # older model has a row here but none for the current version, so an empty
    # result is a miss just as a brand-new document is.
    analyses = await documents_repo.get_analyses(
        session, document.id, settings.model_version
    )
    if not analyses:
        doc = document  # bind for the closure so the job captures this document
        analyses = await queue.submit(user_id, lambda: run_analysis(session, doc))

    prefs = await preferences_repo.get_for_user(session, user_id)
    verdict = compute_verdict(analyses, prefs)
    await history_repo.append(session, user_id, document.id, verdict)
    return verdict, document.id


async def get_analysis_detail(
    session: AsyncSession, user_id: int, document_id: int
) -> tuple[Document, list[Analysis]]:
    """Per-category breakdown for GET /analyses/{id}; raise if not found.

    Analyses are a shared cache, not per-user rows, so there is no ownership
    check here — auth alone gates the route.
    """
    found = await documents_repo.get_document_with_analyses(session, document_id)
    if found is None:
        raise NotFoundError("analysis")
    return found


async def run_analysis(session: AsyncSession, document: Document) -> list[Analysis]:
    """Cache-miss path: hand the normalized text to app.agent (which cleans,
    chunks, and takes the per-category max across chunks) and persist the
    returned scores as Analysis rows (model_version from settings)."""
    scores = await classifier.analyze(document.original_text)
    analyses = [
        Analysis(
            document_id=document.id,
            category=score.category,
            score=score.score,
            explanation=score.explanation,
            model_version=settings.model_version,
        )
        for score in scores
    ]
    await documents_repo.save_analyses(session, analyses)
    return analyses


def normalize_text(text: str) -> str:
    """Canonical form used for hashing (whitespace/case/unicode normalization).

    Collapses the trivial ways two copies of the same TOS differ — unicode
    form, whitespace runs, case — so they hash to one cache entry.
    """
    normalized = unicodedata.normalize("NFC", text)
    return " ".join(normalized.split()).casefold()


def compute_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
