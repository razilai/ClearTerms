from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Finding(Base):
    """One clause the model quoted, under the Analysis for its category.

    The category lives on the parent Analysis, not here: duplicating it would
    give two places to disagree about what a finding is about. ``score`` does
    repeat information — the parent holds the max across its findings — but
    that is deliberate. Per-clause severity is real (one aggressive arbitration
    provision alongside two standard ones), while the parent's max is a
    denormalization so ``compute_verdict`` never has to load findings at all.

    No model_version column either: findings inherit the cache key through
    ``analysis_id``, so bumping ``settings.model_version`` writes a new Analysis
    row with its own findings and leaves the old pair intact.

    Built and read through ``Analysis.findings``, which owns the ordering and
    the cascade — see the relationship there.
    """

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        # CASCADE is declared for the day analyses are pruned (a model_version
        # sweep) and for Postgres. SQLite does not enforce it unless
        # PRAGMA foreign_keys=ON, which this app does not set.
        ForeignKey("analyses.id", ondelete="CASCADE"),
        index=True,
    )
    evidence: Mapped[str] = mapped_column(Text)
    score: Mapped[int]
    explanation: Mapped[str] = mapped_column(Text)
