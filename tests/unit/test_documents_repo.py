"""Unit tests: documents repo (caching, filtering, constraints)."""



from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import documents
from tests.unit.factories import MODEL_V1, MODEL_V2, _analysis

# --- documents repo ---------------------------------------------------------
#
# Category slugs are plain String(64) with no FK, so these use literals rather
# than importing the taxonomy: what is under test is filtering and constraints,
# not the label set.


async def test_get_by_hash_returns_document(session: AsyncSession) -> None:
    created = await documents.create(
        session, "hash-a", "https://example.test/tos", "normalized text"
    )

    found = await documents.get_by_hash(session, "hash-a")
    assert found is not None
    assert found.id == created.id
    assert found.url == "https://example.test/tos"
    assert found.normalized_text == "normalized text"


async def test_get_by_hash_returns_none_when_absent(session: AsyncSession) -> None:
    await documents.create(session, "hash-a", None, "normalized text")

    assert await documents.get_by_hash(session, "hash-missing") is None


async def test_create_document_populates_id(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")

    assert doc.id is not None, "flush should populate the PK"


async def test_create_document_duplicate_hash_returns_existing(
    session: AsyncSession,
) -> None:
    # Two concurrent analyses of the same TOS both miss the cache and reach
    # create(); ON CONFLICT makes the loser return the winner's row instead of
    # raising a unique violation. The loser's payload is dropped.
    first = await documents.create(session, "hash-a", None, "normalized text")
    second = await documents.create(session, "hash-a", None, "different text")

    assert second.id == first.id
    assert second.normalized_text == "normalized text"


async def test_save_and_get_analyses_round_trip(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    other = await documents.create(session, "hash-b", None, "other text")
    await documents.save_analyses(
        session,
        [
            _analysis(doc.id, "arbitration", score=2),
            _analysis(doc.id, "data_collection", score=1),
            # Belongs to a different document; must not leak into doc's results.
            _analysis(other.id, "liability", score=2),
        ],
    )

    found = await documents.get_analyses(session, doc.id, MODEL_V1)
    assert {(a.category, a.score) for a in found} == {
        ("arbitration", 2),
        ("data_collection", 1),
    }
    assert all(a.document_id == doc.id for a in found)


async def test_get_analyses_filters_by_model_version(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [
            _analysis(doc.id, "arbitration", score=2, model_version=MODEL_V1),
            _analysis(doc.id, "arbitration", score=0, model_version=MODEL_V2),
        ],
    )

    found = await documents.get_analyses(session, doc.id, MODEL_V1)
    assert [(a.model_version, a.score) for a in found] == [(MODEL_V1, 2)]


async def test_duplicate_analysis_returns_winner(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    first = await documents.save_analyses(
        session, [_analysis(doc.id, "arbitration", score=2)]
    )

    # A concurrent run persists the same (document_id, category, model_version)
    # first; the savepoint absorbs the composite-unique violation and the loser
    # gets back the winner's cached rows (score 2), not its own (score 5).
    second = await documents.save_analyses(
        session, [_analysis(doc.id, "arbitration", score=5)]
    )

    assert [a.score for a in first] == [2]
    assert [(a.category, a.score) for a in second] == [("arbitration", 2)]


async def test_get_document_with_analyses(session: AsyncSession) -> None:
    doc = await documents.create(
        session, "hash-a", "https://example.test/tos", "normalized text"
    )
    await documents.save_analyses(
        session,
        [
            _analysis(doc.id, "arbitration", score=2),
            _analysis(doc.id, "liability", score=1),
        ],
    )

    result = await documents.get_document_with_analyses(session, doc.id)
    assert result is not None
    found_doc, found_analyses = result
    assert found_doc.id == doc.id
    assert found_doc.text_hash == "hash-a"
    assert {a.category for a in found_analyses} == {"arbitration", "liability"}


async def test_get_document_with_analyses_missing_returns_none(
    session: AsyncSession,
) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")

    assert await documents.get_document_with_analyses(session, doc.id + 1000) is None
