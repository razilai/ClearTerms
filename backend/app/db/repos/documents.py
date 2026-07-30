from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, Document


async def get_by_hash(session: AsyncSession, text_hash: str) -> Document | None:
    raise NotImplementedError


async def create(
    session: AsyncSession, text_hash: str, url: str | None, normalized_text: str
) -> Document:
    raise NotImplementedError


async def get_analyses(
    session: AsyncSession, document_id: int, model_version: str
) -> list[Analysis]:
    raise NotImplementedError


async def save_analyses(session: AsyncSession, analyses: list[Analysis]) -> None:
    """Persist prepared Analysis rows (services build them from agent output)."""
    raise NotImplementedError


async def get_document_with_analyses(
    session: AsyncSession, document_id: int
) -> tuple[Document, list[Analysis]] | None:
    raise NotImplementedError
