"""Forum routes: posts, comments, likes."""

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.forum import (
    CommentCreate,
    CommentOut,
    CommentUpdate,
    LikeResponse,
    PostCreate,
    PostDetail,
    PostOut,
)
from app.services import forum as forum_service

# Handlers delegate to app.services.forum — no business logic here.
router = APIRouter(prefix="/forum", tags=["forum"])


@router.post("/posts", response_model=PostOut, status_code=201)
async def create_post(
    body: PostCreate, session: SessionDep, user: CurrentUserDep
) -> PostOut:
    return await forum_service.create_post(session, user, body)


@router.get("/posts", response_model=list[PostOut])
async def list_posts(session: SessionDep, user: CurrentUserDep) -> list[PostOut]:
    return await forum_service.list_posts(session)


@router.get("/posts/{post_id}", response_model=PostDetail)
async def get_post(
    post_id: int, session: SessionDep, user: CurrentUserDep
) -> PostDetail:
    return await forum_service.get_post_detail(session, post_id)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    await forum_service.delete_post(session, user.id, post_id)


@router.post("/posts/{post_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    post_id: int, body: CommentCreate, session: SessionDep, user: CurrentUserDep
) -> CommentOut:
    return await forum_service.add_comment(session, user, post_id, body.body)


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def edit_comment(
    comment_id: int, body: CommentUpdate, session: SessionDep, user: CurrentUserDep
) -> CommentOut:
    return await forum_service.edit_comment(session, user, comment_id, body.body)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: int, session: SessionDep, user: CurrentUserDep
) -> None:
    await forum_service.delete_comment(session, user.id, comment_id)


@router.put("/posts/{post_id}/like", response_model=LikeResponse)
async def toggle_like(
    post_id: int, session: SessionDep, user: CurrentUserDep
) -> LikeResponse:
    return await forum_service.toggle_like(session, user.id, post_id)
