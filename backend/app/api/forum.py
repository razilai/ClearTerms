"""Forum routes: posts, comments, votes, attachments."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, UploadFile

from app.api.deps import CurrentUserDep, PageParamsDep, SessionDep
from app.schemas.forum import (
    AttachmentOut,
    CommentCreate,
    CommentOut,
    CommentUpdate,
    PostCreate,
    PostDetail,
    PostOut,
    VoteRequest,
    VoteResponse,
)
from app.schemas.pagination import Page
from app.services import forum as forum_service

# Handlers delegate to app.services.forum — no business logic here.
router = APIRouter(prefix="/forum", tags=["forum"])


@router.post("/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    file: Annotated[UploadFile, File()],
    session: SessionDep,
    user: CurrentUserDep,
    background_tasks: BackgroundTasks,
) -> AttachmentOut:
    return await forum_service.upload_attachment(session, user, file, background_tasks)


@router.get("/attachments/{attachment_id}", response_model=AttachmentOut)
async def get_attachment(
    attachment_id: int, session: SessionDep, user: CurrentUserDep
) -> AttachmentOut:
    return await forum_service.get_attachment(session, attachment_id)


@router.post("/posts", response_model=PostOut, status_code=201)
async def create_post(
    body: PostCreate, session: SessionDep, user: CurrentUserDep
) -> PostOut:
    return await forum_service.create_post(session, user, body)


@router.get("/posts", response_model=Page[PostOut])
async def list_posts(
    session: SessionDep, user: CurrentUserDep, page: PageParamsDep
) -> Page[PostOut]:
    return await forum_service.list_posts(session, user.id, page.limit, page.cursor)


@router.get("/posts/{post_id}", response_model=PostDetail)
async def get_post(
    post_id: int, session: SessionDep, user: CurrentUserDep
) -> PostDetail:
    return await forum_service.get_post_detail(session, user.id, post_id)


@router.get("/posts/{post_id}/comments", response_model=Page[CommentOut])
async def list_comments(
    post_id: int, session: SessionDep, user: CurrentUserDep, page: PageParamsDep
) -> Page[CommentOut]:
    return await forum_service.list_post_comments(
        session, user.id, post_id, page.limit, page.cursor
    )


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    await forum_service.delete_post(session, user.id, post_id)


@router.post("/posts/{post_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    post_id: int, body: CommentCreate, session: SessionDep, user: CurrentUserDep
) -> CommentOut:
    return await forum_service.add_comment(
        session, user, post_id, body.body, body.attachment_ids
    )


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


@router.put("/posts/{post_id}/vote", response_model=VoteResponse)
async def vote_post(
    post_id: int, body: VoteRequest, session: SessionDep, user: CurrentUserDep
) -> VoteResponse:
    return await forum_service.vote_post(session, user.id, post_id, body.value)


@router.put("/comments/{comment_id}/vote", response_model=VoteResponse)
async def vote_comment(
    comment_id: int, body: VoteRequest, session: SessionDep, user: CurrentUserDep
) -> VoteResponse:
    return await forum_service.vote_comment(session, user.id, comment_id, body.value)
