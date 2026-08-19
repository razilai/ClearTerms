"""Notification routes: the feed and its read state."""

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, PageParamsDep, SessionDep
from app.schemas.notifications import MarkAllReadResponse, NotificationPage
from app.services import notifications as notifications_service

# Handlers delegate to app.services.notifications — no business logic here.
router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    session: SessionDep, user: CurrentUserDep, page: PageParamsDep
) -> NotificationPage:
    # One response carries both the page and the unread total: the frontend
    # polls this every 30s and needs the items to toast and the count for the
    # bell, and splitting them would double the request rate.
    return await notifications_service.list_notifications(
        session, user.id, page.limit, page.cursor
    )


@router.post("/read", response_model=MarkAllReadResponse)
async def mark_all_read(
    session: SessionDep, user: CurrentUserDep
) -> MarkAllReadResponse:
    return await notifications_service.mark_all_read(session, user.id)


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: int, session: SessionDep, user: CurrentUserDep
) -> None:
    # Someone else's id is a 404, not a 403 — see the service docstring.
    await notifications_service.mark_read(session, user.id, notification_id)
