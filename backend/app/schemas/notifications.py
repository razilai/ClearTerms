"""Wire contracts for the notification feed."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.pagination import Page

# What happened. The frontend turns this plus ``value`` into display text; the
# backend never ships a rendered sentence, so copy changes stay frontend-only.
NotificationKind = Literal["dm", "post_comment", "post_vote", "comment_vote"]


class NotificationOut(BaseModel):
    id: int
    kind: NotificationKind
    # Actors are always named, votes included — see the design doc; this is the
    # first place the forum reveals who voted.
    actor_email: str
    # +1 / -1 for the vote kinds, None otherwise.
    value: int | None = None
    # Navigation target: post_id for the three forum kinds, conversation_id for
    # a dm. Exactly one of the two is set.
    post_id: int | None = None
    post_title: str | None = None
    conversation_id: int | None = None
    created_at: datetime
    read_at: datetime | None = None


class NotificationPage(Page[NotificationOut]):
    """A page plus the total unread count.

    Bundled into one response because the frontend needs both on every poll —
    the items to toast and the count for the bell — and a second endpoint would
    double the request rate for no gain.
    """

    unread_count: int


class MarkAllReadResponse(BaseModel):
    marked_count: int
