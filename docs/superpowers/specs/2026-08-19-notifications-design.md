# Notifications — design

Date: 2026-08-19

## Goal

Tell a user, while they are using the site, when another user:

- sent them a direct message,
- commented on one of their posts,
- liked or disliked one of their posts,
- liked or disliked one of their comments.

Delivery is a popup toast on arrival plus an unread bell badge in the header.

## Decisions

| Question | Decision |
|---|---|
| Storage | Durable `notifications` table, one row per event |
| Delivery | Polling (30s), matching the existing unread-badge query |
| Vote noise | Emit when a vote is set or flipped; dedupe per (actor, target); clearing a vote emits nothing |
| Voter identity | Actor named for every kind, votes included |
| UI surface | Toast on arrival + unread bell badge in the header; no list page |
| DM overlap | DMs produce notification rows *and* still drive the §4 badge; the two counters stay independent |

The last one is deliberate: the bell counts events you have not acknowledged,
the §4 badge counts messages you have not opened. Opening a thread clears §4
and does not clear the bell. Keeping them independent avoids a
`messages` → `notifications` service call that nothing else in the codebase
needs.

Naming the voter is a real change in behaviour: today the forum exposes only
aggregate vote counts, never who voted. After this, content owners learn who
voted on their content — and since email is the only user identifier the API
exposes, a named voter also becomes DM-able. Aggregate counts on posts and
comments are unchanged. Recipient anonymity is unaffected: an anonymous
post's author is the *recipient*, and recipients always see their own content.

## Data model

`backend/app/models/notification.py`:

```python
class Notification(Base):
    __tablename__ = "notifications"
    id: int                                       # PK
    recipient_id: FK users.id                     # indexed via the composite below
    actor_id: FK users.id
    kind: str                                     # see table below
    target_id: int                                # untyped; meaning set by kind
    value: int | None                             # +1 / -1 for vote kinds
    post_id: FK posts.id | None                   # ondelete CASCADE
    comment_id: FK comments.id | None             # ondelete CASCADE
    conversation_id: FK conversations.id | None   # ondelete CASCADE
    created_at: datetime
    read_at: datetime | None
```

Constraints and indexes:

- `UniqueConstraint(recipient_id, actor_id, kind, target_id)` — the dedupe key.
  Every column is non-null, so no Postgres `NULLS NOT DISTINCT` subtlety.
- `Index("ix_notifications_recipient_created_id", recipient_id, created_at, id)`
  — covers the newest-first keyset page and, on its leading column, the unread
  count.

### `target_id` encodes the collapse policy

There is one unique constraint. What each kind stores in `target_id` is what
decides whether repeated events collapse:

| kind | `target_id` | FKs set | collapses? |
|---|---|---|---|
| `dm` | message id | `conversation_id` | no — every DM notifies |
| `post_comment` | comment id | `post_id`, `comment_id` | no — every comment notifies |
| `post_vote` | post id | `post_id` | yes, per (actor, post) |
| `comment_vote` | comment id | `post_id`, `comment_id` | yes, per (actor, comment) |

Emit is an `ON CONFLICT DO UPDATE` upsert on the unique key: it bumps
`created_at`, overwrites `value` so a like→dislike flip re-notifies with the
new verb, and clears `read_at` so the event resurfaces. A user toggling a vote
twenty times produces one row, not twenty.

### Why three nullable foreign keys

`target_id` cannot be a foreign key — its referent varies by kind — so on its
own it would strand rows when a post or comment is deleted. Setting every
foreign key that applies to the event makes cleanup free at the database
level: deleting a post removes its notifications, deleting a comment removes
the comment and comment-vote notifications that point at it. The columns exist
for `ON DELETE CASCADE`; reads use `post_id` and `conversation_id` for
navigation and ignore `comment_id`.

## Backend

### Emit points

All in the service layer, on the caller's session, so an action that rolls
back cannot leave a phantom notification.

- `services/forum.py::add_comment` — recipient is `post.user_id`.
- `services/forum.py::_apply_vote` — the owner id is passed down from
  `vote_post` / `vote_comment`, which already load the post or comment.
  Emits only when a vote is **set** or flipped; clearing emits nothing and
  leaves any existing row alone.
- `services/messages.py::send_message` — recipient is the other participant.

`services/notifications.py::emit()` returns early when
`actor_id == recipient_id`, so commenting on or voting your own content is
silent. Forum and messages import the notifications service; the layer rule
`api → services → {db, agent}` is unchanged.

Emit failures must not take down the action that triggered them; the emit is
part of the same transaction, so a constraint bug would surface immediately in
tests rather than silently in production.

### Routes

`backend/app/api/notifications.py`, mounted in `api/__init__.py`.

- `GET /notifications` → `{items, next_cursor, unread_count}`. One call feeds
  both the toasts and the badge. Keyset paged newest-first, 15 per page, like
  the forum and history lists. `actor_email` and `post_title` are batched into
  the page the way forum batches its author-email join; the service returns
  the API schema, not ORM rows, per the existing convention.
- `POST /notifications/{id}/read` — marks one read (toast click). A
  notification belonging to someone else returns **404, not 403**, matching the
  conversation rule: ids are sequential, so a 403 would confirm the row exists.
- `POST /notifications/read` — marks all read (bell click).

`NotificationOut`: `id`, `kind`, `actor_email`, `value`, `post_id`,
`post_title`, `conversation_id`, `created_at`, `read_at`.

### Migration

`uv run alembic revision --autogenerate -m "notifications"`, reviewed before
`upgrade head`.

## Frontend

### New files

- `src/api/notifications.ts` — `NotificationOut` type, `getNotifications`,
  `markRead`, `markAllRead`, exported `notificationsKey`.
- `src/lib/notificationText.ts` — pure `(n) => string`:
  - `dm` → "sent you a message"
  - `post_comment` → "commented on «title»"
  - `post_vote` → "liked/disliked your post «title»"
  - `comment_vote` → "liked/disliked your comment on «title»"
- `src/lib/useNotificationToasts.ts` — the poll-and-diff hook.
- `src/components/NotificationBell.tsx` — `ActionIcon` inside a Mantine
  `Indicator`, count from `unread_count`, click calls `markAllRead` and
  invalidates.

### Changed files

- `src/AppLayout.tsx` — mount the hook, add the bell to the header group
  beside the email.
- `src/api/types.ts` — the schema mirror.

### The watermark

Toasting every unread item would blast a screenful the moment a user logs in
after a busy weekend. The hook holds a `useRef` of the highest notification id
it has seen:

- The **first** successful fetch seeds the watermark from the page's maximum
  id and toasts nothing. The bell badge is what reports the backlog.
- Every later fetch toasts unread items with `id > watermark`, oldest first,
  then advances the watermark.

The ref lives outside the React Query cache on purpose: cached data is
restored on remount, and a remount — a route change, or StrictMode's double
mount in development — must not re-toast events the user already saw. Bursts
are capped at five toasts per tick with a "+N more" summary, so a poll landing
after a long idle tab cannot stack toasts off-screen.

Toast bodies are clickable: navigate to `/forum/{post_id}` or
`/messages/{conversation_id}`, mark that notification read, invalidate.

Polling uses `refetchInterval: 30_000`, matching the existing unread-badge
query. The nav therefore runs two 30-second polls; they stay separate because
the two counters are independent by design.

Mantine's `Notifications` provider is already mounted in `main.tsx`, so no new
dependency is needed.

## Testing

Hybrid strategy per the repo convention: test-first on the backend,
build-first on the UI.

`tests/unit/test_notifications.py`:

- self-action suppression — acting on your own content emits nothing
- clearing a vote emits nothing
- the upsert bumps `created_at` and clears `read_at` instead of inserting
- a like→dislike flip rewrites `value`

`tests/integration/test_notifications.py`:

- alice comments on bob's post → bob has one notification, alice has none
- alice likes, unlikes, likes again → exactly one row
- two comments from one actor on one post → two notifications (this is what
  proves the per-kind `target_id` choice)
- marking another user's notification read returns 404
- deleting the post cascades its notifications away

Frontend: `npm run build` is the typecheck gate. `notificationText` is a pure
function; the hook and bell are verified by hand in the running app.

## Out of scope

- Dropdown list or a routed `/notifications` page
- Email or web-push delivery
- Per-user mute or per-kind notification preferences
- Real-time transport (SSE or WebSocket)

Real-time was rejected for the same reason the analysis queue is documented as
per-process: fan-out across multiple uvicorn workers needs out-of-process
pub/sub, and `EventSource` cannot send the `Authorization` header the API
expects.
