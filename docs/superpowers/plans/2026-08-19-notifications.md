# Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify a user with a popup toast and an unread bell badge when another user DMs them, comments on their post, or votes on their post or comment.

**Architecture:** A durable `notifications` table holds one row per event. The forum and messages services call `notifications_service.emit()` on the caller's session, so a rolled-back action leaves no phantom notification. A single unique constraint plus a per-kind choice of what `target_id` means gives exactly the wanted collapse policy (votes dedupe, DMs and comments do not). The frontend polls `GET /notifications` every 30 seconds, diffs against a watermark ref, and toasts what is new.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async + asyncpg · Alembic · Pydantic v2 · PostgreSQL 16 · React + TypeScript + Mantine + TanStack Query

**Spec:** `docs/superpowers/specs/2026-08-19-notifications-design.md`

## Global Constraints

- Layer rules hold: `api → services → {db, agent}`. The api layer never touches repos.
- Services raise domain exceptions from `app/services/exceptions.py`, never `fastapi.HTTPException`.
- Services return API schemas, not ORM rows, whenever a join is needed for the response.
- Repos `flush()`, never `commit()` — the caller owns the transaction boundary.
- Async throughout.
- Kind values are exactly `"dm"`, `"post_comment"`, `"post_vote"`, `"comment_vote"`.
- Notification ownership violations return **404, not 403** (ids are sequential; a 403 confirms the row exists). This matches `messages.py::_require_participant`.
- `emit()` is silent when `actor_id == recipient_id`.
- Backend commands run from `backend/`. Passing a test path requires `-c pyproject.toml`, otherwise pytest's rootdir shifts to the repo root and drops this project's config.
- Frontend typecheck gate is `npm run build` from `frontend/`.
- Tests need Docker (testcontainers Postgres).

---

### Task 1: Notification model and migration

**Files:**
- Create: `backend/app/models/notification.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/<hash>_notifications.py` (generated)
- Test: `tests/unit/test_notifications.py`

**Interfaces:**
- Consumes: nothing
- Produces: `app.models.Notification` with columns `id: int`, `recipient_id: int`, `actor_id: int`, `kind: str`, `target_id: int`, `value: int | None`, `post_id: int | None`, `comment_id: int | None`, `conversation_id: int | None`, `created_at: datetime`, `read_at: datetime | None`. Unique constraint named `uq_notifications_event` on `(recipient_id, actor_id, kind, target_id)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_notifications.py`:

```python
"""Unit tests for the notifications model, repo and emit policy."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import users
from app.models import Notification


async def _two_users(session: AsyncSession) -> tuple[int, int]:
    ada = await users.create(session, "ada@example.com", "pw")
    bob = await users.create(session, "bob@example.com", "pw")
    return ada.id, bob.id


async def test_duplicate_event_violates_the_unique_constraint(
    session: AsyncSession,
) -> None:
    """A blind second insert on the same key must fail — this constraint is
    what the emit upsert relies on to collapse repeated votes."""
    ada, bob = await _two_users(session)
    for _ in range(2):
        session.add(
            Notification(
                recipient_id=ada,
                actor_id=bob,
                kind="post_vote",
                target_id=7,
                value=1,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/unit/test_notifications.py -v
```

Expected: FAIL with `ImportError: cannot import name 'Notification' from 'app.models'`.

- [ ] **Step 3: Write the model**

Create `backend/app/models/notification.py`:

```python
"""An event another user caused that the recipient should be told about."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # The dedupe key. What collapses is decided entirely by what each kind
        # stores in target_id: a vote points at the thing voted on (so one
        # actor voting twice is one row), while a DM points at the message and
        # a comment at the comment (so each one notifies separately). Every
        # column here is non-null, which keeps Postgres' NULL-distinct rule out
        # of the picture.
        UniqueConstraint(
            "recipient_id",
            "actor_id",
            "kind",
            "target_id",
            name="uq_notifications_event",
        ),
        # Serves the newest-first keyset page and, on its leading column, the
        # unread count.
        Index(
            "ix_notifications_recipient_created_id",
            "recipient_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # 'dm' | 'post_comment' | 'post_vote' | 'comment_vote'. Kept a plain string
    # rather than a db enum so adding a kind is a code change, not a migration.
    kind: Mapped[str] = mapped_column(String(32))
    # Untyped on purpose: its referent varies by kind, so it cannot be a FK.
    target_id: Mapped[int] = mapped_column(Integer)
    # +1 / -1 for the vote kinds, so the toast can say liked vs disliked.
    value: Mapped[int | None] = mapped_column(Integer)
    # These three exist for ON DELETE CASCADE, not for reads: target_id cannot
    # be a foreign key, so without them deleting a post or comment would strand
    # notifications pointing at it. Reads use post_id and conversation_id for
    # navigation; comment_id is carried only so the cascade can find the row.
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE")
    )
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # None until the recipient acknowledges it; drives the bell badge.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Register the model**

In `backend/app/models/__init__.py`, add the import in alphabetical position (after `from app.models.message import Message`):

```python
from app.models.notification import Notification
```

and add `"Notification"` to `__all__`, between `"Message"` and `"Post"`.

- [ ] **Step 5: Run test to verify it passes**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/unit/test_notifications.py -v
```

Expected: PASS. (The test tier builds the schema from ORM metadata, so it passes before the migration exists.)

- [ ] **Step 6: Generate the migration**

```bash
cd backend
docker compose -f ../docker-compose.yml up -d db
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "notifications"
```

Read the generated file. It must contain `op.create_table("notifications", ...)` with three `ondelete="CASCADE"` foreign keys, the unique constraint `uq_notifications_event`, and `ix_notifications_recipient_created_id`. It must contain **nothing else** — any unrelated drop or alter means the db was out of sync before you started; stop and report that rather than applying it.

- [ ] **Step 7: Apply and verify the migration is complete**

```bash
cd backend && uv run alembic upgrade head && uv run alembic revision --autogenerate -m "should be empty"
```

Expected: the second command produces a migration whose `upgrade()` body is just `pass`. Delete that empty file:

```bash
rm backend/alembic/versions/*_should_be_empty.py
```

- [ ] **Step 8: Lint, typecheck, commit**

```bash
cd backend && uv run ruff check . && uv run mypy .
git add backend/app/models/notification.py backend/app/models/__init__.py backend/alembic/versions tests/unit/test_notifications.py
git commit -m "feat: notifications table"
```

---

### Task 2: Notifications repo

**Files:**
- Create: `backend/app/db/repos/notifications.py`
- Modify: `backend/app/db/repos/forum.py` (append `get_post_titles`)
- Test: `tests/unit/test_notifications.py` (append)

**Interfaces:**
- Consumes: `app.models.Notification` (Task 1)
- Produces:
  - `notifications_repo.upsert(session, *, recipient_id: int, actor_id: int, kind: str, target_id: int, value: int | None = None, post_id: int | None = None, comment_id: int | None = None, conversation_id: int | None = None) -> None`
  - `notifications_repo.list_for_user(session, user_id: int, limit: int, cursor: tuple[datetime, int] | None = None) -> list[Notification]`
  - `notifications_repo.count_unread(session, user_id: int) -> int`
  - `notifications_repo.get(session, notification_id: int) -> Notification | None`
  - `notifications_repo.mark_read(session, notification_id: int, when: datetime) -> None`
  - `notifications_repo.mark_all_read(session, user_id: int, when: datetime) -> int`
  - `forum_repo.get_post_titles(session, post_ids: Iterable[int]) -> dict[int, str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_notifications.py`:

```python
from datetime import UTC, datetime

from app.db.repos import notifications as notifications_repo


async def test_upsert_collapses_a_repeated_event_and_resurfaces_it(
    session: AsyncSession,
) -> None:
    """Second upsert on the same key updates in place: value is rewritten and
    read_at cleared, so a like -> dislike flip re-notifies rather than adding
    a row."""
    ada, bob = await _two_users(session)
    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_vote", target_id=7, value=1
    )
    first = (await notifications_repo.list_for_user(session, ada, 10))[0]
    await notifications_repo.mark_read(session, first.id, datetime.now(tz=UTC))
    assert await notifications_repo.count_unread(session, ada) == 0

    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_vote", target_id=7, value=-1
    )
    rows = await notifications_repo.list_for_user(session, ada, 10)
    assert len(rows) == 1
    assert rows[0].id == first.id
    assert rows[0].value == -1
    assert rows[0].read_at is None
    assert await notifications_repo.count_unread(session, ada) == 1


async def test_distinct_targets_are_distinct_notifications(
    session: AsyncSession,
) -> None:
    """Different target_id means a different event — this is what makes two
    comments from one actor produce two notifications."""
    ada, bob = await _two_users(session)
    for target in (1, 2):
        await notifications_repo.upsert(
            session,
            recipient_id=ada,
            actor_id=bob,
            kind="post_comment",
            target_id=target,
        )
    assert len(await notifications_repo.list_for_user(session, ada, 10)) == 2


async def test_mark_all_read_only_touches_the_owner_and_is_idempotent(
    session: AsyncSession,
) -> None:
    ada, bob = await _two_users(session)
    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_comment", target_id=1
    )
    await notifications_repo.upsert(
        session, recipient_id=bob, actor_id=ada, kind="post_comment", target_id=2
    )
    now = datetime.now(tz=UTC)
    assert await notifications_repo.mark_all_read(session, ada, now) == 1
    assert await notifications_repo.mark_all_read(session, ada, now) == 0
    assert await notifications_repo.count_unread(session, bob) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/unit/test_notifications.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.db.repos.notifications'`.

- [ ] **Step 3: Write the repo**

Create `backend/app/db/repos/notifications.py`:

```python
"""Notification data access.

The upsert is the whole design: one INSERT ... ON CONFLICT keyed on
uq_notifications_event, so whether a repeated event collapses is decided by
what the caller puts in target_id, not by branching here.
"""

from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


async def upsert(
    session: AsyncSession,
    *,
    recipient_id: int,
    actor_id: int,
    kind: str,
    target_id: int,
    value: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    conversation_id: int | None = None,
) -> None:
    """Record the event, or refresh the existing row for the same event.

    On conflict the row is bumped to now, its value rewritten (a like -> dislike
    flip re-notifies with the new verb) and read_at cleared so it resurfaces.
    The foreign keys are not in the update set: they describe the same event
    and cannot have changed.

    ``func.now()`` is Postgres' transaction timestamp, not the wall clock, so
    an insert and a later conflicting update in the *same* transaction land on
    the same created_at. That is exactly right for real requests, which are one
    transaction each — but it means a test running both inside the per-test
    transaction must assert on value and read_at, never on created_at moving.
    """
    stmt = (
        pg_insert(Notification)
        .values(
            recipient_id=recipient_id,
            actor_id=actor_id,
            kind=kind,
            target_id=target_id,
            value=value,
            post_id=post_id,
            comment_id=comment_id,
            conversation_id=conversation_id,
        )
        .on_conflict_do_update(
            constraint="uq_notifications_event",
            set_={"value": value, "created_at": func.now(), "read_at": None},
        )
    )
    await session.execute(stmt)
    await session.flush()


async def list_for_user(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[Notification]:
    """One keyset page of a user's notifications, newest first.

    Fetches ``limit + 1`` so the caller can detect a further page; uses
    ``ix_notifications_recipient_created_id``.
    """
    stmt = select(Notification).where(Notification.recipient_id == user_id)
    if cursor is not None:
        stmt = stmt.where(tuple_(Notification.created_at, Notification.id) < cursor)
    stmt = stmt.order_by(
        Notification.created_at.desc(), Notification.id.desc()
    ).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_unread(session: AsyncSession, user_id: int) -> int:
    """Every unacknowledged notification, regardless of which page is on screen."""
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == user_id, Notification.read_at.is_(None))
    )
    return result.scalar_one()


async def get(session: AsyncSession, notification_id: int) -> Notification | None:
    return await session.get(Notification, notification_id)


async def mark_read(
    session: AsyncSession, notification_id: int, when: datetime
) -> None:
    """Acknowledge one notification. Already-read rows keep their read_at."""
    await session.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.read_at.is_(None))
        .values(read_at=when)
    )
    await session.flush()


async def mark_all_read(session: AsyncSession, user_id: int, when: datetime) -> int:
    """Acknowledge everything this user has. Returns how many rows changed."""
    result = await session.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user_id, Notification.read_at.is_(None)
        )
        .values(read_at=when)
    )
    await session.flush()
    return cast("CursorResult[object]", result).rowcount
```

- [ ] **Step 4: Add the post-title lookup**

Append to `backend/app/db/repos/forum.py` (end of the post-operations section, after `list_posts`):

```python
async def get_post_titles(
    session: AsyncSession, post_ids: Iterable[int]
) -> dict[int, str]:
    """Map post id -> title, for callers that render a post reference without
    loading the whole row (the notification feed). One query for the page,
    rather than an N+1."""
    ids = list(post_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(Post.id, Post.title).where(Post.id.in_(ids))
    )
    return {post_id: title for post_id, title in result.all()}
```

`Iterable` and `select` are already imported at the top of that file.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/unit/test_notifications.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 6: Lint, typecheck, commit**

```bash
cd backend && uv run ruff check . && uv run mypy .
git add backend/app/db/repos/notifications.py backend/app/db/repos/forum.py tests/unit/test_notifications.py
git commit -m "feat: notifications repo"
```

---

### Task 3: Schemas and notifications service

**Files:**
- Create: `backend/app/schemas/notifications.py`
- Create: `backend/app/services/notifications.py`
- Test: `tests/unit/test_notifications.py` (append)

**Interfaces:**
- Consumes: `notifications_repo` (Task 2), `forum_repo.get_post_titles` (Task 2), `users_repo.get_emails(session, ids) -> dict[int, str]`
- Produces:
  - `NotificationKind = Literal["dm", "post_comment", "post_vote", "comment_vote"]`
  - `NotificationOut` with fields `id`, `kind`, `actor_email`, `value`, `post_id`, `post_title`, `conversation_id`, `created_at`, `read_at`
  - `NotificationPage(Page[NotificationOut])` adding `unread_count: int`
  - `MarkAllReadResponse` with `marked_count: int`
  - `notifications_service.emit(session, *, recipient_id, actor_id, kind, target_id, value=None, post_id=None, comment_id=None, conversation_id=None) -> None`
  - `notifications_service.list_notifications(session, user_id, limit, cursor) -> NotificationPage`
  - `notifications_service.mark_read(session, user_id, notification_id) -> None`
  - `notifications_service.mark_all_read(session, user_id) -> MarkAllReadResponse`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_notifications.py`:

```python
import pytest

from app.services import notifications as notifications_service
from app.services.exceptions import NotFoundError


async def test_emit_is_silent_for_your_own_actions(session: AsyncSession) -> None:
    """Commenting on or voting your own content must not notify you."""
    ada, _ = await _two_users(session)
    await notifications_service.emit(
        session,
        recipient_id=ada,
        actor_id=ada,
        kind="post_comment",
        target_id=1,
        post_id=None,
    )
    assert await notifications_repo.count_unread(session, ada) == 0


async def test_marking_someone_elses_notification_is_not_found(
    session: AsyncSession,
) -> None:
    """404, not 403: ids are sequential, so a 403 would confirm the row exists."""
    ada, bob = await _two_users(session)
    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_comment", target_id=1
    )
    mine = (await notifications_repo.list_for_user(session, ada, 10))[0]
    with pytest.raises(NotFoundError):
        await notifications_service.mark_read(session, bob, mine.id)
    with pytest.raises(NotFoundError):
        await notifications_service.mark_read(session, ada, mine.id + 999)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/unit/test_notifications.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.notifications'`.

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/notifications.py`:

```python
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
```

- [ ] **Step 4: Write the service**

Create `backend/app/services/notifications.py`:

```python
"""Notification business logic.

``emit`` is the write side, called by the forum and messages services on their
own session so a rolled-back action cannot leave a phantom notification. The
read side returns API schemas, not ORM rows, because actor emails and post
titles have to be joined in — db work the api layer is not allowed to do
(mirrors the forum and messages services).
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import forum as forum_repo
from app.db.repos import notifications as notifications_repo
from app.db.repos import users as users_repo
from app.schemas.notifications import (
    MarkAllReadResponse,
    NotificationKind,
    NotificationOut,
    NotificationPage,
)
from app.schemas.pagination import slice_page
from app.services.exceptions import NotFoundError


async def emit(
    session: AsyncSession,
    *,
    recipient_id: int,
    actor_id: int,
    kind: NotificationKind,
    target_id: int,
    value: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    conversation_id: int | None = None,
) -> None:
    """Record an event for the recipient, unless they caused it themselves.

    The self-check lives here rather than at each call site so that commenting
    on your own post, or voting your own content, is silent everywhere by
    construction.
    """
    if recipient_id == actor_id:
        return
    await notifications_repo.upsert(
        session,
        recipient_id=recipient_id,
        actor_id=actor_id,
        kind=kind,
        target_id=target_id,
        value=value,
        post_id=post_id,
        comment_id=comment_id,
        conversation_id=conversation_id,
    )


async def list_notifications(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> NotificationPage:
    """One keyset page, newest first, plus the unread total.

    Three batched queries for the page: actor emails, post titles, and the
    count — no per-row lookups.
    """
    rows = await notifications_repo.list_for_user(session, user_id, limit, cursor)
    rows, next_cursor = slice_page(rows, limit, lambda n: (n.created_at, n.id))
    emails = await users_repo.get_emails(session, {n.actor_id for n in rows})
    titles = await forum_repo.get_post_titles(
        session, {n.post_id for n in rows if n.post_id is not None}
    )
    items = [
        NotificationOut(
            id=n.id,
            kind=n.kind,  # type: ignore[arg-type]
            actor_email=emails[n.actor_id],
            value=n.value,
            post_id=n.post_id,
            post_title=titles.get(n.post_id) if n.post_id is not None else None,
            conversation_id=n.conversation_id,
            created_at=n.created_at,
            read_at=n.read_at,
        )
        for n in rows
    ]
    return NotificationPage(
        items=items,
        next_cursor=next_cursor,
        unread_count=await notifications_repo.count_unread(session, user_id),
    )


async def mark_read(
    session: AsyncSession, user_id: int, notification_id: int
) -> None:
    """Acknowledge one notification.

    Someone else's id raises NotFoundError, not NotOwnerError: notification ids
    are sequential, so a 403 would confirm that a given event exists.
    """
    notification = await notifications_repo.get(session, notification_id)
    if notification is None or notification.recipient_id != user_id:
        raise NotFoundError("notification")
    await notifications_repo.mark_read(
        session, notification_id, datetime.now(tz=UTC)
    )


async def mark_all_read(
    session: AsyncSession, user_id: int
) -> MarkAllReadResponse:
    return MarkAllReadResponse(
        marked_count=await notifications_repo.mark_all_read(
            session, user_id, datetime.now(tz=UTC)
        )
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/unit/test_notifications.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 6: Lint, typecheck, commit**

```bash
cd backend && uv run ruff check . && uv run mypy .
git add backend/app/schemas/notifications.py backend/app/services/notifications.py tests/unit/test_notifications.py
git commit -m "feat: notifications service"
```

---

### Task 4: Emit from the forum service

**Files:**
- Modify: `backend/app/services/forum.py` (`add_comment`, `vote_post`, `vote_comment`, `_apply_vote`)
- Test: `tests/integration/test_notifications.py`

**Interfaces:**
- Consumes: `notifications_service.emit` (Task 3)
- Produces: `_apply_vote(session, model, user_id, target_id, value, *, owner_id: int, kind: NotificationKind, post_id: int, comment_id: int | None = None) -> VoteResponse` — the keyword-only block is new.

**Note on reading this task:** the integration tests here assert through the HTTP API, but `GET /notifications` does not exist until Task 6. They therefore read the rows through the repo using the `session` fixture, which the `client` fixture shares.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_notifications.py`:

```python
"""Notifications raised by forum and message activity, end to end."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import notifications as notifications_repo
from app.db.repos import users as users_repo
from tests.conftest import signup_headers
from tests.integration.factories import POST_BODY


async def _user_id(session: AsyncSession, email: str) -> int:
    user = await users_repo.get_by_email(session, email)
    assert user is not None
    return user.id


async def test_a_comment_notifies_the_post_author_only(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    resp = await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "good catch"},
        headers=bob,
    )
    assert resp.status_code == 201, resp.text

    alice_id = await _user_id(session, "alice@example.com")
    bob_id = await _user_id(session, "bob@example.com")
    rows = await notifications_repo.list_for_user(session, alice_id, 10)
    assert [(n.kind, n.actor_id, n.post_id) for n in rows] == [
        ("post_comment", bob_id, post_id)
    ]
    assert await notifications_repo.list_for_user(session, bob_id, 10) == []


async def test_two_comments_from_one_actor_are_two_notifications(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    """target_id is the comment id for this kind, so comments never collapse."""
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for body in ("first", "second"):
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": body}, headers=bob
        )

    alice_id = await _user_id(session, "alice@example.com")
    assert len(await notifications_repo.list_for_user(session, alice_id, 10)) == 2


async def test_commenting_on_your_own_post_is_silent(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "replying to myself"},
        headers=auth_headers,
    )
    alice_id = await _user_id(session, "alice@example.com")
    assert await notifications_repo.list_for_user(session, alice_id, 10) == []


async def test_toggling_a_vote_leaves_exactly_one_notification(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    """Like, unlike, like again: the dedupe key is (actor, post), and clearing
    a vote emits nothing, so the author sees one event, not three."""
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for value in (1, 1, 1):
        await client.put(
            f"/forum/posts/{post_id}/vote", json={"value": value}, headers=bob
        )

    alice_id = await _user_id(session, "alice@example.com")
    rows = await notifications_repo.list_for_user(session, alice_id, 10)
    assert len(rows) == 1
    assert rows[0].kind == "post_vote"
    assert rows[0].value == 1


async def test_a_comment_vote_notifies_the_comment_author(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    comment_id = (
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=bob
        )
    ).json()["id"]
    resp = await client.put(
        f"/forum/comments/{comment_id}/vote", json={"value": -1}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    bob_id = await _user_id(session, "bob@example.com")
    rows = await notifications_repo.list_for_user(session, bob_id, 10)
    # The comment vote, plus nothing else: alice owns the post, so bob's
    # comment on it notified her, not him.
    assert [(n.kind, n.value, n.post_id) for n in rows] == [
        ("comment_vote", -1, post_id)
    ]


async def test_deleting_a_post_cascades_its_notifications_away(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.put(f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=bob)
    alice_id = await _user_id(session, "alice@example.com")
    assert len(await notifications_repo.list_for_user(session, alice_id, 10)) == 1

    resp = await client.delete(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 204, resp.text
    session.expire_all()
    assert await notifications_repo.list_for_user(session, alice_id, 10) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/integration/test_notifications.py -v
```

Expected: FAIL — every assertion on `list_for_user` returns `[]` because nothing emits yet.

- [ ] **Step 3: Wire the comment emit**

In `backend/app/services/forum.py`, add to the imports (after `from app.services import media as media_service`):

```python
from app.services import notifications as notifications_service
```

In `add_comment`, insert the emit after `_claim_attachments_for_comment` and before the `return`:

```python
    # target_id is the comment id, so every comment notifies separately;
    # comment_id is carried only so deleting the comment cascades this away.
    await notifications_service.emit(
        session,
        recipient_id=post.user_id,
        actor_id=user.id,
        kind="post_comment",
        target_id=comment.id,
        post_id=post_id,
        comment_id=comment.id,
    )
```

- [ ] **Step 4: Wire the vote emits**

Replace `vote_post`, `vote_comment` and `_apply_vote` in `backend/app/services/forum.py` with:

```python
async def vote_post(session: AsyncSession, user_id: int, post_id: int, value: int) -> VoteResponse:
    post = await _require_post(session, post_id)
    return await _apply_vote(
        session,
        PostVote,
        user_id,
        post_id,
        value,
        owner_id=post.user_id,
        kind="post_vote",
        post_id=post_id,
    )


async def vote_comment(session: AsyncSession, user_id: int, comment_id: int, value: int) -> VoteResponse:
    comment = await forum_repo.get_comment(session, comment_id)
    if comment is None:
        raise NotFoundError("comment")
    return await _apply_vote(
        session,
        CommentVote,
        user_id,
        comment_id,
        value,
        owner_id=comment.user_id,
        kind="comment_vote",
        post_id=comment.post_id,
        comment_id=comment_id,
    )


async def _apply_vote(
    session: AsyncSession,
    model: type[forum_repo.VoteT],
    user_id: int,
    target_id: int,
    value: int,
    *,
    owner_id: int,
    kind: NotificationKind,
    post_id: int,
    comment_id: int | None = None,
) -> VoteResponse:
    """Toggle semantics: re-sending the value you already hold clears it,
    sending the opposite switches sides.

    Notifies the owner only when a vote is set or flipped. Clearing stays
    silent and leaves any existing notification alone — telling someone their
    like was withdrawn is noise, and re-liking would only bump the row it
    already has.
    """
    existing = await forum_repo.get_vote(session, model, user_id, target_id)
    if existing is not None and existing.value == value:
        await forum_repo.remove_vote(session, model, user_id, target_id)
        my_vote = 0
    else:
        await forum_repo.set_vote(session, model, user_id, target_id, value)
        my_vote = value
        # target_id is the thing voted on, so one actor voting repeatedly
        # collapses onto a single row.
        await notifications_service.emit(
            session,
            recipient_id=owner_id,
            actor_id=user_id,
            kind=kind,
            target_id=target_id,
            value=value,
            post_id=post_id,
            comment_id=comment_id,
        )
    counts = (await forum_repo.count_votes(session, model, [target_id])).get(
        target_id, forum_repo.VoteCounts(0, 0)
    )
    return VoteResponse(
        like_count=counts.likes, dislike_count=counts.dislikes, my_vote=my_vote
    )
```

Add `NotificationKind` to the imports:

```python
from app.schemas.notifications import NotificationKind
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/integration/test_notifications.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 6: Run the full backend suite for regressions**

```bash
cd backend && uv run pytest
```

Expected: PASS. The vote tests in `tests/integration/test_votes.py` exercise the changed `_apply_vote` signature — if any fail, the keyword-only arguments were not threaded through both call sites.

- [ ] **Step 7: Lint, typecheck, commit**

```bash
cd backend && uv run ruff check . && uv run mypy .
git add backend/app/services/forum.py tests/integration/test_notifications.py
git commit -m "feat: notify on comments and votes"
```

---

### Task 5: Emit from the messages service

**Files:**
- Modify: `backend/app/services/messages.py` (`send_message`)
- Test: `tests/integration/test_notifications.py` (append)

**Interfaces:**
- Consumes: `notifications_service.emit` (Task 3), `messages_service._other_id`
- Produces: nothing new

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_notifications.py`:

```python
async def test_every_dm_notifies_the_recipient_separately(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    """target_id is the message id, so a chatty sender produces one
    notification per message rather than one per thread."""
    bob = await signup_headers(client, "bob@example.com")
    conversation_id = (
        await client.post(
            "/messages/conversations",
            json={"recipient_email": "alice@example.com"},
            headers=bob,
        )
    ).json()["id"]
    for body in ("hello", "you there?"):
        resp = await client.post(
            f"/messages/conversations/{conversation_id}/messages",
            json={"body": body},
            headers=bob,
        )
        assert resp.status_code == 201, resp.text

    alice_id = await _user_id(session, "alice@example.com")
    bob_id = await _user_id(session, "bob@example.com")
    rows = await notifications_repo.list_for_user(session, alice_id, 10)
    assert len(rows) == 2
    assert {n.kind for n in rows} == {"dm"}
    assert {n.conversation_id for n in rows} == {conversation_id}
    assert all(n.post_id is None for n in rows)
    assert await notifications_repo.list_for_user(session, bob_id, 10) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/integration/test_notifications.py::test_every_dm_notifies_the_recipient_separately -v
```

Expected: FAIL with `assert 0 == 2`.

- [ ] **Step 3: Wire the emit**

In `backend/app/services/messages.py`, add to the imports (after `from app.services import media as media_service`):

```python
from app.services import notifications as notifications_service
```

In `send_message`, capture the conversation that `_require_participant` already returns and emit after the `touch`:

```python
    conversation = await _require_participant(session, user.id, conversation_id)
    message = await messages_repo.create_message(
        session, conversation_id, user.id, body
    )
    attachments = await _claim_attachments(
        session, attachment_ids, user, message.id
    )
    # Bump with the message's own timestamp rather than a fresh clock reading,
    # so last_message_at always equals the newest message's created_at.
    await messages_repo.touch(session, conversation_id, message.created_at)
    # target_id is the message id, so each message notifies separately. This is
    # independent of the §4 unread badge, which counts messages not yet opened
    # rather than events not yet acknowledged.
    await notifications_service.emit(
        session,
        recipient_id=_other_id(conversation, user.id),
        actor_id=user.id,
        kind="dm",
        target_id=message.id,
        conversation_id=conversation_id,
    )
    return _message_out(message, user.email, attachments)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/integration/test_notifications.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
cd backend && uv run ruff check . && uv run mypy . && uv run pytest
git add backend/app/services/messages.py tests/integration/test_notifications.py
git commit -m "feat: notify on direct messages"
```

---

### Task 6: Notification routes

**Files:**
- Create: `backend/app/api/notifications.py`
- Modify: `backend/app/api/__init__.py`
- Test: `tests/integration/test_notifications.py` (append)

**Interfaces:**
- Consumes: `notifications_service` (Task 3), `SessionDep`, `CurrentUserDep`, `PageParamsDep` from `app/api/deps.py`
- Produces: `GET /notifications`, `POST /notifications/read`, `POST /notifications/{notification_id}/read`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_notifications.py`:

```python
async def test_the_feed_names_the_actor_and_carries_the_post_title(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.put(f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=bob)

    resp = await client.get("/notifications?limit=15", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["unread_count"] == 1
    item = payload["items"][0]
    assert item["kind"] == "post_vote"
    assert item["actor_email"] == "bob@example.com"
    assert item["value"] == 1
    assert item["post_id"] == post_id
    assert item["post_title"] == POST_BODY["title"]
    assert item["conversation_id"] is None
    assert item["read_at"] is None


async def test_marking_one_read_clears_it_from_the_unread_count(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.post(
        f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=bob
    )
    notification_id = (
        await client.get("/notifications", headers=auth_headers)
    ).json()["items"][0]["id"]

    resp = await client.post(
        f"/notifications/{notification_id}/read", headers=auth_headers
    )
    assert resp.status_code == 204, resp.text
    payload = (await client.get("/notifications", headers=auth_headers)).json()
    assert payload["unread_count"] == 0
    assert payload["items"][0]["read_at"] is not None


async def test_marking_someone_elses_notification_read_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.post(
        f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=bob
    )
    notification_id = (
        await client.get("/notifications", headers=auth_headers)
    ).json()["items"][0]["id"]

    resp = await client.post(f"/notifications/{notification_id}/read", headers=bob)
    assert resp.status_code == 404, resp.text


async def test_mark_all_read_reports_what_it_changed(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for body in ("one", "two"):
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": body}, headers=bob
        )

    resp = await client.post("/notifications/read", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"marked_count": 2}
    assert (
        await client.get("/notifications", headers=auth_headers)
    ).json()["unread_count"] == 0


async def test_the_feed_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/notifications")).status_code == 401


async def test_the_feed_pages_by_cursor(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for body in ("one", "two", "three"):
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": body}, headers=bob
        )

    first = (
        await client.get("/notifications?limit=2", headers=auth_headers)
    ).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await client.get(
            f"/notifications?limit=2&cursor={first['next_cursor']}",
            headers=auth_headers,
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/integration/test_notifications.py -v
```

Expected: FAIL with 404s on `/notifications` (the SPA-agnostic backend has no such route yet).

- [ ] **Step 3: Write the router**

Create `backend/app/api/notifications.py`:

```python
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
```

- [ ] **Step 4: Mount the router**

In `backend/app/api/__init__.py`, extend the import line and add the include:

```python
from app.api import analysis, auth, forum, history, messages, notifications, preferences
```

```python
api_router.include_router(notifications.router)
```

Put the `include_router` call after `messages.router`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest -c pyproject.toml ../tests/integration/test_notifications.py -v
```

Expected: PASS, 13 tests.

- [ ] **Step 6: Lint, typecheck, full suite, commit**

```bash
cd backend && uv run ruff check . && uv run mypy . && uv run pytest
git add backend/app/api/notifications.py backend/app/api/__init__.py tests/integration/test_notifications.py
git commit -m "feat: notification routes"
```

---

### Task 7: Frontend API client and display text

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/notifications.ts`
- Create: `frontend/src/lib/notificationText.ts`

**Interfaces:**
- Consumes: `GET /notifications`, `POST /notifications/read`, `POST /notifications/{id}/read` (Task 6); `request` / `requestJson` from `api/client.ts`
- Produces:
  - `NotificationKind`, `NotificationOut`, `NotificationPage`, `MarkAllReadResponse` types
  - `notificationsKey`, `NOTIFICATION_PAGE_SIZE`, `listNotifications(limit, cursor?)`, `markNotificationRead(id)`, `markAllNotificationsRead()`
  - `notificationText(n: NotificationOut): string`
  - `notificationLink(n: NotificationOut): string | null`

- [ ] **Step 1: Add the schema mirrors**

Append to `frontend/src/api/types.ts`:

```ts
// Mirrors app/schemas/notifications.py. The backend ships kind + value rather
// than a rendered sentence, so display copy stays a frontend concern.
export type NotificationKind =
  | 'dm'
  | 'post_comment'
  | 'post_vote'
  | 'comment_vote'

export interface NotificationOut {
  id: number
  kind: NotificationKind
  actor_email: string
  value: number | null
  post_id: number | null
  post_title: string | null
  conversation_id: number | null
  created_at: string
  read_at: string | null
}

// A Page<NotificationOut> plus the unread total, so one poll feeds both the
// toasts and the bell badge.
export interface NotificationPage extends Page<NotificationOut> {
  unread_count: number
}

export interface MarkAllReadResponse {
  marked_count: number
}
```

- [ ] **Step 2: Write the client**

Create `frontend/src/api/notifications.ts`:

```ts
import { request, requestJson } from './client'
import type {
  MarkAllReadResponse,
  NotificationPage,
} from './types'

// Shared so the bell and the toast hook read the same cached poll, and so a
// mark-read anywhere invalidates both without either importing the other.
export const notificationsKey = ['notifications']

// One screen of recent events. The feed is polled, not browsed, so this is the
// only page size in play — there is no notification list UI to page through.
export const NOTIFICATION_PAGE_SIZE = 15

export function listNotifications(
  limit: number = NOTIFICATION_PAGE_SIZE,
  cursor?: string | null,
): Promise<NotificationPage> {
  const query = cursor
    ? `?limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `?limit=${limit}`
  return request<NotificationPage>(`/notifications${query}`)
}

// Acknowledges one event — the toast click path.
export function markNotificationRead(notificationId: number): Promise<void> {
  return requestJson<void>(`/notifications/${notificationId}/read`, 'POST', {})
}

// Acknowledges everything — the bell click path.
export function markAllNotificationsRead(): Promise<MarkAllReadResponse> {
  return requestJson<MarkAllReadResponse>('/notifications/read', 'POST', {})
}
```

- [ ] **Step 3: Write the text and link builders**

Create `frontend/src/lib/notificationText.ts`:

```ts
import type { NotificationOut } from '../api/types'

// The sentence that follows the actor's email in a toast. Pure so it can be
// read and checked on its own; the backend deliberately ships kind + value
// rather than prose, which keeps copy changes out of the API contract.
export function notificationText(n: NotificationOut): string {
  const title = n.post_title ?? 'your post'
  switch (n.kind) {
    case 'dm':
      return 'sent you a message'
    case 'post_comment':
      return `commented on «${title}»`
    case 'post_vote':
      return n.value === 1
        ? `liked your post «${title}»`
        : `disliked your post «${title}»`
    case 'comment_vote':
      return n.value === 1
        ? `liked your comment on «${title}»`
        : `disliked your comment on «${title}»`
  }
}

// Where clicking the notification goes. Exactly one of post_id and
// conversation_id is set by the backend; null means the target is gone (a post
// deleted between the poll and the click), and the caller should not navigate.
export function notificationLink(n: NotificationOut): string | null {
  if (n.conversation_id !== null) {
    return `/messages/${n.conversation_id}`
  }
  if (n.post_id !== null) {
    return `/forum/${n.post_id}`
  }
  return null
}
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both pass. `tsc` proves the `switch` covers every `NotificationKind` — a missing case would be a "not all code paths return a value" error.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/notifications.ts frontend/src/lib/notificationText.ts
git commit -m "feat: notification api client"
```

---

### Task 8: Toast hook, bell, and layout wiring

**Files:**
- Create: `frontend/src/lib/useNotificationToasts.ts`
- Create: `frontend/src/components/NotificationBell.tsx`
- Modify: `frontend/src/AppLayout.tsx`

**Interfaces:**
- Consumes: `listNotifications`, `markNotificationRead`, `markAllNotificationsRead`, `notificationsKey`, `NOTIFICATION_PAGE_SIZE` (Task 7); `notificationText`, `notificationLink` (Task 7)
- Produces: `useNotificationToasts(): number` (returns the unread count), `<NotificationBell />`

- [ ] **Step 1: Write the hook**

Create `frontend/src/lib/useNotificationToasts.ts`:

```ts
import { notifications } from '@mantine/notifications'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  listNotifications,
  markNotificationRead,
  notificationsKey,
  NOTIFICATION_PAGE_SIZE,
} from '../api/notifications'
import { notificationLink, notificationText } from './notificationText'

// A poll that lands after a long idle tab can carry more events than fit on
// screen; past this many, the rest are summarised in one line.
const TOAST_BURST = 5

/** Polls the feed, toasts what is new, and returns the unread count.
 *
 * Mount once, in the app shell.
 */
export function useNotificationToasts(): number {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // The high-water mark of ids already toasted. A ref, not query state, on
  // purpose: React Query restores cached data on remount, and a remount — a
  // route change, or StrictMode's double mount in development — must not
  // re-toast events the user has already seen.
  const seen = useRef<number | null>(null)

  const { data } = useQuery({
    queryKey: notificationsKey,
    queryFn: () => listNotifications(NOTIFICATION_PAGE_SIZE),
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (!data) {
      return
    }
    const highest = data.items.reduce((max, n) => Math.max(max, n.id), 0)
    const watermark = seen.current
    seen.current = watermark === null ? highest : Math.max(watermark, highest)
    if (watermark === null) {
      // First successful poll: seed the mark and toast nothing. Logging in
      // after a busy weekend would otherwise bury the screen in toasts — the
      // bell badge is what reports a backlog.
      return
    }

    const fresh = data.items
      .filter((n) => n.id > watermark && n.read_at === null)
      .sort((a, b) => a.id - b.id)

    for (const n of fresh.slice(0, TOAST_BURST)) {
      const link = notificationLink(n)
      notifications.show({
        title: n.actor_email,
        message: notificationText(n),
        style: link ? { cursor: 'pointer' } : undefined,
        onClick: () => {
          void markNotificationRead(n.id).then(() =>
            queryClient.invalidateQueries({ queryKey: notificationsKey }),
          )
          if (link) {
            navigate(link)
          }
        },
      })
    }
    if (fresh.length > TOAST_BURST) {
      notifications.show({
        message: `+${fresh.length - TOAST_BURST} more notifications`,
      })
    }
  }, [data, navigate, queryClient])

  return data?.unread_count ?? 0
}
```

- [ ] **Step 2: Write the bell**

Create `frontend/src/components/NotificationBell.tsx`:

```tsx
import { ActionIcon, Indicator } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  markAllNotificationsRead,
  notificationsKey,
} from '../api/notifications'

interface NotificationBellProps {
  unreadCount: number
}

/** Unread events, acknowledged in one click.
 *
 * There is no dropdown: the toast is how an event is read, and this is the
 * catch-up affordance for events whose toast was missed.
 */
export function NotificationBell({ unreadCount }: NotificationBellProps) {
  const queryClient = useQueryClient()
  const markAll = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: notificationsKey }),
  })

  return (
    <Indicator
      label={unreadCount > 0 ? unreadCount : undefined}
      disabled={unreadCount === 0}
      size={16}
      offset={4}
    >
      <ActionIcon
        variant="subtle"
        color="ink"
        size="lg"
        aria-label={
          unreadCount > 0
            ? `${unreadCount} unread notifications — mark all read`
            : 'Notifications'
        }
        disabled={unreadCount === 0 || markAll.isPending}
        onClick={() => markAll.mutate()}
      >
        {/* Text glyph rather than an icon dependency: the app ships no icon
            library, and a bell is unambiguous. */}
        <span aria-hidden>🔔</span>
      </ActionIcon>
    </Indicator>
  )
}
```

- [ ] **Step 3: Mount both in the layout**

In `frontend/src/AppLayout.tsx`, add the imports:

```ts
import { NotificationBell } from './components/NotificationBell'
import { useNotificationToasts } from './lib/useNotificationToasts'
```

Inside `AppLayout`, below the existing `unreadCount` line, add:

```ts
  // Polls the notification feed and toasts new events; the count it returns
  // drives the bell. Independent of the §4 badge above: that counts messages
  // not yet opened, this counts events not yet acknowledged.
  const notificationCount = useNotificationToasts()
```

Then in the header, put the bell before the email `Text` inside the right-hand `<Group gap="md">`:

```tsx
          <Group gap="md">
            <NotificationBell unreadCount={notificationCount} />
            <Text className={classes.email} visibleFrom="xs">
```

- [ ] **Step 4: Typecheck and lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both pass.

- [ ] **Step 5: Verify by hand in the running app**

```bash
uv run --project backend python tests/devserver.py    # from repo root, needs Docker
cd frontend && npm run dev
```

In the browser, sign up two accounts in two different browser profiles (or one normal and one private window, since the session is localStorage). As user A, create a forum post. As user B, like it and comment on it. Within 30 seconds user A must see two toasts and a bell badge reading 2. Confirm each of these:

1. Clicking a toast navigates to the post and drops the badge by one.
2. Re-liking and un-liking as B repeatedly does not produce more than the one vote notification.
3. A DM from B toasts for A, and the §4 badge also increments — the two counters are independent by design.
4. Reloading the page does not re-toast anything already on screen; the badge still shows the outstanding count.
5. Acting on your own post as A produces no toast.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/useNotificationToasts.ts frontend/src/components/NotificationBell.tsx frontend/src/AppLayout.tsx
git commit -m "feat: notification toasts and bell"
```

---

### Task 9: Documentation

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything above
- Produces: nothing code-facing

- [ ] **Step 1: Document the subsystem**

In `CLAUDE.md`, under **Implemented:**, add a bullet after the Messages / DM one:

```markdown
- **Notifications** (`services/notifications.py`, `api/notifications.py`): one
  `notifications` row per event another user caused — `dm`, `post_comment`,
  `post_vote`, `comment_vote`. Routes: `GET /notifications` (keyset page newest
  first, and the `unread_count` in the same response so one 30s poll feeds both
  the toasts and the bell), `POST /notifications/{id}/read`,
  `POST /notifications/read`. Someone else's notification is **404, not 403**,
  like conversations. The whole collapse policy is one
  `UniqueConstraint(recipient_id, actor_id, kind, target_id)` plus a per-kind
  choice of what `target_id` means: a vote points at the thing voted on, so one
  actor voting repeatedly upserts a single row (bumping `created_at`, rewriting
  `value`, clearing `read_at`), while a DM points at the message and a comment
  at the comment, so those never collapse. Clearing a vote emits nothing.
  `post_id` / `comment_id` / `conversation_id` are nullable FKs that exist for
  `ON DELETE CASCADE` — `target_id` cannot be a FK since its referent varies —
  with reads using `post_id` and `conversation_id` for navigation.
  `emit()` is called by `services/forum.py` and `services/messages.py` on the
  caller's session (so a rolled-back action leaves no phantom) and returns early
  when `actor_id == recipient_id`. Actors are named for every kind, votes
  included: this is the first place the forum reveals *who* voted, aggregate
  counts having been the only vote surface before.
  Frontend: `lib/useNotificationToasts.ts` polls, diffs against a `useRef`
  watermark and toasts what is new — the first poll seeds the mark and toasts
  nothing, so logging in after a backlog shows a badge rather than a wall of
  toasts, and a remount cannot re-toast. `components/NotificationBell.tsx` in
  the header shows the unread count and marks all read. There is no list page.
  The bell and the §4 DM badge are deliberately independent counters: the bell
  counts events not yet acknowledged, §4 counts messages not yet opened.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: describe the notifications subsystem"
```

---

## Verification

After Task 9, from the repo root:

```bash
cd backend && uv run ruff check . && uv run mypy . && uv run pytest
cd ../frontend && npm run build && npm run lint
```

All five must pass before the branch is considered done.
