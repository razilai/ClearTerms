"""Unit tests: findings cascade through Analysis.findings."""



import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import documents
from app.models import Finding
from tests.unit.factories import MODEL_V1, _analysis, _finding

# --- findings ---------------------------------------------------------------
#
# Findings are written and read through Analysis.findings; nothing addresses the
# table directly. expunge_all() before each read so the assertions go through a
# real query rather than the identity map handing back the objects just added.


async def test_save_analyses_cascades_findings_in_reported_order(
    session: AsyncSession,
) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [
            _analysis(
                doc.id,
                "arbitration",
                score=2,
                findings=[
                    _finding("waive your right to a jury"),
                    _finding("class action waiver"),
                ],
            ),
            _analysis(doc.id, "liability", score=1, findings=[_finding("as is")]),
            # densify emits all six categories; absent ones carry no findings.
            _analysis(doc.id, "termination", score=0),
        ],
    )
    session.expunge_all()

    result = await documents.get_document_with_analyses(session, doc.id)
    assert result is not None
    _, analyses = result
    by_category = {a.category: a for a in analyses}

    # Grouped under the right parent at all == analysis_id was populated by the
    # cascade; the order == the relationship's order_by held through the round
    # trip, which densify's contract depends on.
    assert [f.evidence for f in by_category["arbitration"].findings] == [
        "waive your right to a jury",
        "class action waiver",
    ]
    assert [f.evidence for f in by_category["liability"].findings] == ["as is"]
    assert by_category["termination"].findings == []


async def test_get_analyses_leaves_findings_unloaded(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [_analysis(doc.id, "arbitration", score=2, findings=[_finding("jury waiver")])],
    )
    session.expunge_all()

    found = await documents.get_analyses(session, doc.id, MODEL_V1)
    # lazy="raise": the verdict path needs scores only, so reaching for findings
    # here is an error rather than a silent query per category.
    with pytest.raises(InvalidRequestError):
        _ = found[0].findings


async def test_deleting_an_analysis_deletes_its_findings(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [_analysis(doc.id, "arbitration", score=2, findings=[_finding("jury waiver")])],
    )
    session.expunge_all()

    result = await documents.get_document_with_analyses(session, doc.id)
    assert result is not None
    _, analyses = result
    await session.delete(analyses[0])
    await session.flush()

    # delete-orphan cascades in Python, so this holds without SQLite's
    # PRAGMA foreign_keys=ON, which the app never sets.
    remaining = await session.execute(select(Finding))
    assert remaining.scalars().all() == []
