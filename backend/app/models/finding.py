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
        # CASCADE is enforced by Postgres: deleting an Analysis (a model_version
        # sweep) drops its findings at the db level. The ORM's delete-orphan
        # (see Analysis.findings) covers the same in Python for session-tracked
        # deletes; both point the same way.
        ForeignKey("analyses.id", ondelete="CASCADE"),
        index=True,
    )
    evidence: Mapped[str] = mapped_column(Text)
    score: Mapped[int]
    explanation: Mapped[str] = mapped_column(Text)
