from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RateLimit(Base):
    """One fixed-window counter row.

    The primary key encodes the whole window: ``{scope}:{identifier}:{window}``,
    where ``window`` is ``floor(now / window_seconds)``. A new window is a new
    key, so rows are never mutated across windows — a counter is only ever
    incremented within its own window and then abandoned. ``expires_at`` is the
    end of that window; a periodic sweep (see services.rate_limit.sweep_expired)
    deletes rows past it so abandoned counters don't accumulate.
    """

    __tablename__ = "rate_limits"

    bucket: Mapped[str] = mapped_column(String(255), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
