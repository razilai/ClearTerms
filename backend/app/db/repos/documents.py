from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    Race-safe: two requests analyzing the same TOS concurrently both miss the
    ``get_by_hash`` lookup and reach here. ``ON CONFLICT (text_hash) DO NOTHING``
    lets the loser insert nothing instead of raising a unique violation that
    would poison the transaction; RETURNING is then empty, so we re-read the
    winner's committed row. (Postgres serializes the two inserts on the unique
    index, so by the time the loser proceeds the winner's row is visible.)
    """
    stmt = (
        pg_insert(Document)
        .values(
            text_hash=text_hash,
            url=url,
            normalized_text=normalized_text,
            original_text=normalized_text if original_text is None else original_text,
        )
        .on_conflict_do_nothing(index_elements=["text_hash"])
        .returning(Document)
    )
    result = await session.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        # Lost the race: another transaction already inserted this hash. Its row
        # is committed and visible now (see docstring), so this always resolves.
        document = await get_by_hash(session, text_hash)
        if document is None:  # pragma: no cover - invariant, kept for the type
            raise RuntimeError(f"document vanished after conflict on {text_hash}")
    return document


async def get_analyses(
    session: AsyncSession, document_id: int, model_version: str
) -> list[Analysis]:
    """Scores only — findings are left unloaded on purpose.

    This is the POST /analyze cache lookup, which only needs one number per
    category to compute a verdict. Analysis.findings is lazy="raise", so a
    caller that wants them here gets an error rather than a silent query per
    category; use get_document_with_analyses instead.
    """
    result = await session.execute(
        select(Analysis).where(
            Analysis.document_id == document_id,
            Analysis.model_version == model_version,
        )
    )
    return list(result.scalars().all())


async def save_analyses(
    session: AsyncSession, analyses: list[Analysis]
) -> list[Analysis]:
    """Persist prepared Analysis rows (services build them from agent output).

    Returns the rows now cached for this (document, model_version): normally the
    ones passed in, but on a race the winner's instead — see below.

    Race-safe: two requests can both miss the analysis cache and run the agent
    on the same document concurrently, then both try to insert the same
    ``(document_id, category, model_version)``. The insert runs inside a
    SAVEPOINT so the unique violation rolls back only these rows, not the
    caller's whole transaction (which Postgres would otherwise abort). On
    conflict we discard our rows and return the winner's committed cache.
    """
    if not analyses:
        return []
    document_id = analyses[0].document_id
    model_version = analyses[0].model_version
    try:
        async with session.begin_nested():
            session.add_all(analyses)
            await session.flush()
    except IntegrityError:
        # The savepoint rollback discards these just-added rows and detaches them
        # from the session (so they won't be re-inserted on a later flush); read
        # back the winner's committed cache instead.
        return await get_analyses(session, document_id, model_version)
    return analyses


async def get_document_with_analyses(
    session: AsyncSession, document_id: int
) -> tuple[Document, list[Analysis]] | None:
    result = await session.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        return None

    # No model_version filter: this is the detail view, which shows everything
    # stored for the document.
    #
    # selectinload because findings are lazy="raise": the detail response reads
    # them, so they must be loaded up front. It issues one extra SELECT over all
    # the analysis ids rather than one per row, and applies the relationship's
    # order_by, so findings come back in the order densify reported them.
    analyses = await session.execute(
        select(Analysis)
        .where(Analysis.document_id == document_id)
        .options(selectinload(Analysis.findings))
    )
    return document, list(analyses.scalars().all())
