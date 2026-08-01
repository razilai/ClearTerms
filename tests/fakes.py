"""In-memory fakes for the app.db.repos layer.

The repo functions are the only DB touchpoints; patching them lets auth and
forum flows run end-to-end with no database. Fakes build detached ORM
instances, setting created_at explicitly because server defaults only fire at
a real DB. install() patches module attributes, and services resolve repo
functions at call time, so these stay valid once the real repos land.
"""

import inspect
from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from app.db.repos import forum as forum_repo
from app.db.repos import users as users_repo
from app.models import Comment, Post, User
from app.schemas.forum import PostCreate


def _now() -> datetime:
    return datetime.now(UTC)


class FakeStore:
    """Shared in-memory state behind both fake repos."""

    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.posts: dict[int, Post] = {}
        self.comments: dict[int, Comment] = {}
        self.likes: set[tuple[int, int]] = set()  # (user_id, post_id)
        self._next_id = 0

    def next_id(self) -> int:
        self._next_id += 1
        return self._next_id


class _FakeUsersRepo:
    """Async method per function in app.db.repos.users, same signatures."""

    def __init__(self, store: FakeStore) -> None:
        self.store = store

    async def get_by_email(self, session: object, email: str) -> User | None:
        return next(
            (u for u in self.store.users.values() if u.email == email), None
        )

    async def get_by_id(self, session: object, user_id: int) -> User | None:
        return self.store.users.get(user_id)

    async def get_emails(
        self, session: object, user_ids: Iterable[int]
    ) -> dict[int, str]:
        users = self.store.users
        return {uid: users[uid].email for uid in user_ids if uid in users}

    async def update_password_hash(
        self, session: object, user_id: int, password_hash: str
    ) -> None:
        self.store.users[user_id].password_hash = password_hash

    async def create(
        self, session: object, email: str, password_hash: str
    ) -> User:
        user = User(
            id=self.store.next_id(),
            email=email,
            password_hash=password_hash,
            created_at=_now(),
        )
        self.store.users[user.id] = user
        return user


class _FakeForumRepo:
    """Async method per function in app.db.repos.forum, same signatures."""

    def __init__(self, store: FakeStore) -> None:
        self.store = store

    async def create_post(
        self, session: object, user_id: int, data: PostCreate
    ) -> Post:
        post = Post(
            id=self.store.next_id(),
            user_id=user_id,
            document_id=data.document_id,
            category=data.category,
            title=data.title,
            body=data.body,
            created_at=_now(),
        )
        self.store.posts[post.id] = post
        return post

    async def get_post(self, session: object, post_id: int) -> Post | None:
        return self.store.posts.get(post_id)

    async def list_posts(self, session: object) -> list[Post]:
        return sorted(
            self.store.posts.values(), key=lambda p: p.created_at, reverse=True
        )

    async def delete_post(self, session: object, post_id: int) -> None:
        store = self.store
        store.posts.pop(post_id, None)
        store.comments = {
            cid: c for cid, c in store.comments.items() if c.post_id != post_id
        }
        store.likes = {(u, p) for (u, p) in store.likes if p != post_id}

    async def create_comment(
        self, session: object, post_id: int, user_id: int, body: str
    ) -> Comment:
        comment = Comment(
            id=self.store.next_id(),
            post_id=post_id,
            user_id=user_id,
            body=body,
            created_at=_now(),
            edited_at=None,
        )
        self.store.comments[comment.id] = comment
        return comment

    async def get_comment(
        self, session: object, comment_id: int
    ) -> Comment | None:
        return self.store.comments.get(comment_id)

    async def list_comments(self, session: object, post_id: int) -> list[Comment]:
        return sorted(
            (c for c in self.store.comments.values() if c.post_id == post_id),
            key=lambda c: c.created_at,
        )

    async def update_comment(
        self, session: object, comment_id: int, body: str, edited_at: datetime
    ) -> Comment:
        comment = self.store.comments[comment_id]
        comment.body = body
        comment.edited_at = edited_at
        return comment

    async def delete_comment(self, session: object, comment_id: int) -> None:
        self.store.comments.pop(comment_id, None)

    async def get_like(
        self, session: object, user_id: int, post_id: int
    ) -> object | None:
        key = (user_id, post_id)
        return key if key in self.store.likes else None

    async def add_like(self, session: object, user_id: int, post_id: int) -> object:
        self.store.likes.add((user_id, post_id))
        return (user_id, post_id)

    async def remove_like(
        self, session: object, user_id: int, post_id: int
    ) -> None:
        self.store.likes.discard((user_id, post_id))

    async def count_likes(self, session: object, post_id: int) -> int:
        return sum(1 for (_, p) in self.store.likes if p == post_id)

    async def count_likes_by_post(
        self, session: object, post_ids: Iterable[int]
    ) -> dict[int, int]:
        wanted = set(post_ids)
        counts: dict[int, int] = {}
        for _, p in self.store.likes:
            if p in wanted:
                counts[p] = counts.get(p, 0) + 1
        return counts


def install(monkeypatch: pytest.MonkeyPatch, store: FakeStore) -> None:
    """Replace every repo function with its fake counterpart by name."""
    for module, fake in (
        (users_repo, _FakeUsersRepo(store)),
        (forum_repo, _FakeForumRepo(store)),
    ):
        for name, method in inspect.getmembers(fake, inspect.iscoroutinefunction):
            monkeypatch.setattr(module, name, method)
