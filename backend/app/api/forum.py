"""Phase 2: forum routes. Scaffolded now; bodies land in phase 2."""

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

# Handlers delegate to app.services.forum — no business logic here.
router = APIRouter(prefix="/forum", tags=["forum"])


@router.post("/posts", response_model=PostOut, status_code=201)
async def create_post(
    body: PostCreate, session: SessionDep, user: CurrentUserDep
) -> PostOut:
    raise NotImplementedError


@router.get("/posts", response_model=list[PostOut])
async def list_posts(session: SessionDep, user: CurrentUserDep) -> list[PostOut]:
    raise NotImplementedError


@router.get("/posts/{post_id}", response_model=PostDetail)
async def get_post(
    post_id: int, session: SessionDep, user: CurrentUserDep
) -> PostDetail:
    raise NotImplementedError


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    raise NotImplementedError


@router.post("/posts/{post_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    post_id: int, body: CommentCreate, session: SessionDep, user: CurrentUserDep
) -> CommentOut:
    raise NotImplementedError


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def edit_comment(
    comment_id: int, body: CommentUpdate, session: SessionDep, user: CurrentUserDep
) -> CommentOut:
    raise NotImplementedError


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: int, session: SessionDep, user: CurrentUserDep
) -> None:
    raise NotImplementedError


@router.put("/posts/{post_id}/like", response_model=LikeResponse)
async def toggle_like(
    post_id: int, session: SessionDep, user: CurrentUserDep
) -> LikeResponse:
    raise NotImplementedError
