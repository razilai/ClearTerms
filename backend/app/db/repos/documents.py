from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, Document


async def get_urls(
    session: AsyncSession, document_ids: Iterable[int]
) -> dict[int, str | None]:
    """Map document ids to their url; for the history list's per-entry join."""
    result = await session.execute(
        select(Document.id, Document.url).where(Document.id.in_(set(document_ids)))
    )
    return {id_: url for id_, url in result.all()}


async def get_by_hash(session: AsyncSession, text_hash: str) -> Document | None:
    result = await session.execute(
        select(Document).where(Document.text_hash == text_hash)
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    text_hash: str,
    url: str | None,
    normalized_text: str,
    original_text: str | None = None,
) -> Document:
    """Persist a document. ``original_text`` is what the agent later reads.

    It defaults to ``normalized_text`` only so existing callers keep working;
    production must pass the text as submitted, since the normalized form has
    no line breaks or capitals for the chunker to find sections with.
    """
    document = Document(
        text_hash=text_hash,
        url=url,
        normalized_text=normalized_text,
        original_text=normalized_text if original_text is None else original_text,
    )
    session.add(document)
    # Flush, don't commit: the caller owns the transaction boundary. This
    # populates document.id and surfaces the unique-text_hash violation here.
    await session.flush()
    return document


async def get_analyses(
    session: AsyncSession, document_id: int, model_version: str
) -> list[Analysis]:
    result = await session.execute(
        select(Analysis).where(
            Analysis.document_id == document_id,
            Analysis.model_version == model_version,
        )
    )
    return list(result.scalars().all())


async def save_analyses(session: AsyncSession, analyses: list[Analysis]) -> None:
    """Persist prepared Analysis rows (services build them from agent output)."""
    session.add_all(analyses)
    # Flush so a composite-unique violation surfaces here rather than at the
    # caller's commit, far from the code that built these rows.
    await session.flush()


async def get_document_with_analyses(
    session: AsyncSession, document_id: int
) -> tuple[Document, list[Analysis]] | None:
    result = await session.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        return None

    # No model_version filter: this is the detail view, which shows everything
    # stored for the document.
    analyses = await session.execute(
        select(Analysis).where(Analysis.document_id == document_id)
    )
    return document, list(analyses.scalars().all())
