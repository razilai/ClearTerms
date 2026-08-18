"""Direct messaging API contracts.

The list responses are Page[ConversationOut] and Page[MessageOut]
(app.schemas.pagination) — items + next_cursor — so there is no wrapper here.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.auth import LowercaseEmail


class ConversationCreate(BaseModel):
    """Open the thread with one other user, or return the existing one.

    The recipient is named by email because that is the only user identifier
    the API exposes anywhere — forum and message reads carry an email, never a
    user id. Lowercased at the boundary so it matches the stored form.
    """

    recipient_email: LowercaseEmail = Field(max_length=settings.max_email_chars)


class MessageCreate(BaseModel):
    # body is a TEXT column, so the cap is product policy, not storage.
    body: str = Field(min_length=1, max_length=settings.max_message_body_chars)


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    sender_email: str
    body: str
    created_at: datetime
    # Set once the *other* party has opened the thread. Always None on messages
    # the viewer received, since reading them is what clears it.
    read_at: datetime | None = None


class ConversationOut(BaseModel):
    id: int
    # The participant who is not the viewer. The inbox lists who you are
    # talking to, so the service picks the far side of the pair rather than
    # leaking both user_a/user_b columns.
    other_email: str
    last_message_at: datetime
    created_at: datetime
    # Newest message, for the inbox preview. None on a thread with no messages
    # yet — a conversation can exist before anyone has said anything.
    last_message: MessageOut | None = None
    # Messages waiting for the viewer; 0 when the thread is clear.
    unread_count: int = 0


class ConversationDetail(ConversationOut):
    # First keyset page of messages, newest first. messages_next_cursor is set
    # when older ones exist; fetch them from
    # GET /messages/conversations/{id}/messages?cursor=.
    messages: list[MessageOut]
    messages_next_cursor: str | None = None


class UnreadTotal(BaseModel):
    """Notification badge: unread messages across every conversation.

    A single number that must not depend on which inbox page is on screen.
    """

    unread_count: int


class MarkReadResponse(BaseModel):
    """How many messages this call flipped to read — 0 if already clear."""

    marked_count: int
