"""Direct message routes: conversations, messages, read state."""

from fastapi import APIRouter, Depends

from app.api.deps import (
    CurrentUserDep,
    PageParamsDep,
    SessionDep,
    rate_limit_send_message,
    rate_limit_start_conversation,
)
from app.schemas.messages import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    MarkReadResponse,
    MessageCreate,
    MessageOut,
    UnreadTotal,
)
from app.schemas.pagination import Page
from app.services import messages as messages_service

# Handlers delegate to app.services.messages — no business logic here.
router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/unread", response_model=UnreadTotal)
async def unread_total(session: SessionDep, user: CurrentUserDep) -> UnreadTotal:
    return await messages_service.unread_total(session, user.id)


@router.post(
    "/conversations",
    response_model=ConversationOut,
    status_code=201,
    dependencies=[Depends(rate_limit_start_conversation)],
)
async def start_conversation(
    body: ConversationCreate, session: SessionDep, user: CurrentUserDep
) -> ConversationOut:
    # Idempotent: 201 even when the thread already existed, since the caller's
    # intent ("give me the thread with this person") is satisfied either way.
    return await messages_service.start_conversation(
        session, user, body.recipient_email
    )


@router.get("/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    session: SessionDep, user: CurrentUserDep, page: PageParamsDep
) -> Page[ConversationOut]:
    return await messages_service.list_conversations(
        session, user.id, page.limit, page.cursor
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int, session: SessionDep, user: CurrentUserDep
) -> ConversationDetail:
    return await messages_service.get_conversation_detail(
        session, user.id, conversation_id
    )


@router.get(
    "/conversations/{conversation_id}/messages", response_model=Page[MessageOut]
)
async def list_messages(
    conversation_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    page: PageParamsDep,
) -> Page[MessageOut]:
    return await messages_service.list_messages(
        session, user.id, conversation_id, page.limit, page.cursor
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=201,
    dependencies=[Depends(rate_limit_send_message)],
)
async def send_message(
    conversation_id: int,
    body: MessageCreate,
    session: SessionDep,
    user: CurrentUserDep,
) -> MessageOut:
    return await messages_service.send_message(
        session, user, conversation_id, body.body, body.attachment_ids
    )


@router.post("/conversations/{conversation_id}/read", response_model=MarkReadResponse)
async def mark_read(
    conversation_id: int, session: SessionDep, user: CurrentUserDep
) -> MarkReadResponse:
    return await messages_service.mark_read(session, user.id, conversation_id)
