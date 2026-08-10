"""Analysis pipeline orchestration (preference-independent).

Steps: normalize text -> hash -> cache lookup. On miss the caller does none of
the work itself: it submits `analyze_document_job` to app.services.queue and
waits. The job — on a session the queue owns, never the caller's — creates the
Document, hands the normalized text to app.agent (which cleans, chunks, and
takes the per-category max across chunks itself), and persists the returned
scores to the Analysis cache keyed by document_id + model_version.

Owns the seam between the LLM (app.agent) and the rest of the system: the agent
receives plain text and returns structured scores; cache/db/preferences live here.
"""

import hashlib
import unicodedata
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import classifier
from app.core.config import settings
from app.db.repos import documents as documents_repo
from app.db.repos import history as history_repo
from app.db.repos import preferences as preferences_repo
from app.models import Analysis, Document, Finding
from app.services.exceptions import NotFoundError
from app.services.preferences import compute_verdict
from app.services.queue import queue


async def analyze(
    session: AsyncSession, user_id: int, text: str, url: str | None
) -> tuple[str, int]:
    """Full pipeline for POST /analyze. Returns (verdict, document_id).

    normalize -> hash -> cache lookup; on miss submit `analyze_document_job`
    to app.services.queue and re-read the cache through this session once it
    returns; then compute_verdict against the user's preferences and append a
    history entry.

    `analyze_document_job` specifically, never `run_analysis`: run_analysis
    takes a caller-supplied session, and submitting a closure over *this*
    session is the deadlock the queue exists to prevent — the session (and its
    pooled connection, and any locks) would stay open for the whole queue wait.
    """
    normalized = normalize_text(text)
    text_hash = compute_hash(normalized)

    # Read-only until the job returns: the caller must not open a write
    # transaction it would then hold for the whole queue wait.
    document = await documents_repo.get_by_hash(session, text_hash)
    analyses: list[Analysis] = []
    if document is not None:
        # Cache is keyed by (document, model_version): a document analyzed under
        # an older model has a row here but none for the current version, so an
        # empty result is a miss just as a brand-new document is.
        analyses = await documents_repo.get_analyses(
            session, document.id, settings.model_version
        )

    if not analyses:
        document_id = await queue.submit(
            user_id,
            partial(
                analyze_document_job,
                text_hash=text_hash,
                url=url,
                normalized_text=normalized,
                original_text=text,
            ),
        )
        # The worker committed on its own session; re-read through ours so the
        # returned rows belong to this session rather than a closed one.
        analyses = await documents_repo.get_analyses(
            session, document_id, settings.model_version
        )
    else:
        # analyses is only ever populated inside `if document is not None`
        # above, so reaching this branch (analyses non-empty) implies document
        # is not None; mypy can't see that across the two separate `if`s.
        assert document is not None
        document_id = document.id

    prefs = await preferences_repo.get_for_user(session, user_id)
    verdict = compute_verdict(analyses, prefs)
    await history_repo.append(session, user_id, document_id, verdict)
    return verdict, document_id


async def get_analysis_detail(
    session: AsyncSession, user_id: int, document_id: int
) -> tuple[Document, list[Analysis]]:
    """Per-category breakdown for GET /analyses/{id}; raise if not found.

    Returns only the rows for the current model_version — the detail view shows
    one score per category, and old versions linger in the cache after a
    model/prompt bump. Analyses are a shared cache, not per-user rows, so there
    is no ownership check here — auth alone gates the route.
    """
    found = await documents_repo.get_document_with_analyses(session, document_id)
    if found is None:
        raise NotFoundError("analysis")
    document, analyses = found
    current = [a for a in analyses if a.model_version == settings.model_version]
    return document, current


async def run_analysis(session: AsyncSession, document: Document) -> list[Analysis]:
    """Cache-miss path: hand the normalized text to app.agent (which cleans,
    chunks, and takes the per-category max across chunks) and persist the
    returned scores as Analysis rows (model_version from settings).

    Each ClauseScore becomes one Analysis carrying one Finding per quoted
    clause. Only the parents are added: the relationship cascades, so
    SQLAlchemy inserts each Analysis, reads back its id, and fills in the
    children's analysis_id itself.
    """
    scores = await classifier.analyze(document.original_text)
    analyses = [
        Analysis(
            document_id=document.id,
            # ClauseCategory is a StrEnum and the column is String: take .value
            # so the stored label is the slug, not enum coercion's choice.
            category=score.category.value,
            score=score.score,
            model_version=settings.model_version,
            findings=[
                Finding(
                    evidence=finding.evidence,
                    score=finding.score,
                    explanation=finding.explanation,
                )
                for finding in score.findings
            ],
        )
        for score in scores
    ]
    # Returns our rows, or on a concurrent-run race the winner's cached rows.
    return await documents_repo.save_analyses(session, analyses)


async def analyze_document_job(
    session: AsyncSession,
    *,
    text_hash: str,
    url: str | None,
    normalized_text: str,
    original_text: str,
) -> int:
    """The unit of work the queue runs. Returns the document id.

    Takes only plain data plus the session the queue hands it — deliberately no
    reference to the caller's request session, which would otherwise stay open
    (holding a connection, and locks) for the whole queue wait.

    Calls documents_repo.create directly: it is already race-safe via ON CONFLICT
    DO NOTHING + re-read, which matters because two callers can miss the cache
    for the same text and both enqueue. Catching IntegrityError around it instead
    would be both dead code (ON CONFLICT means no unique violation is raised) and
    wrong in principle on Postgres, where a violation aborts the surrounding
    transaction — so the recovery would have to roll back work this job may
    already have done.

    Re-checks the cache: by the time this runs, an identical job submitted just
    before it may already have produced the scores.
    """
    document = await documents_repo.create(
        session, text_hash, url, normalized_text, original_text=original_text
    )
    analyses = await documents_repo.get_analyses(
        session, document.id, settings.model_version
    )
    if not analyses:
        await run_analysis(session, document)
    return document.id


def normalize_text(text: str) -> str:
    """Canonical form used for hashing (whitespace/case/unicode normalization).

    Collapses the trivial ways two copies of the same TOS differ — unicode
    form, whitespace runs, case — so they hash to one cache entry.
    """
    normalized = unicodedata.normalize("NFC", text)
    return " ".join(normalized.split()).casefold()


def compute_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
