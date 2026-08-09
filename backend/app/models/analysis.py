from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.finding import Finding


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("document_id", "category", "model_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    category: Mapped[str] = mapped_column(String(64))
    # The per-category max across this document's findings, denormalized so
    # compute_verdict never has to load them.
    score: Mapped[int]
    model_version: Mapped[str] = mapped_column(String(64))

    # The one relationship() in the models. Elsewhere foreign keys stay plain
    # int columns and joins are written out in the repos, because those point at
    # independent entities — a user outlives any post. A Finding is not
    # independent: it means nothing apart from its Analysis, shares its cache
    # key, and dies with it. That is composition, so the ORM may own the link.
    #
    # - delete-orphan cascades in Python for session-tracked deletes; the FK's
    #   ondelete="CASCADE" (see Finding) is the db-level backstop on Postgres.
    # - order_by keeps insert order on read; densify's finding order is part of
    #   the agent contract, and callers should not have to remember to sort.
    # - lazy="raise" because implicit lazy loads are unusable under async — they
    #   surface as MissingGreenlet far from the cause. Read paths that want
    #   findings must ask: selectinload(Analysis.findings).
    findings: Mapped[list[Finding]] = relationship(
        cascade="all, delete-orphan",
        order_by=Finding.id,
        lazy="raise",
    )
