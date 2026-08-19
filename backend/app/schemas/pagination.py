"""Keyset (cursor) pagination primitives, shared by the list endpoints.

Lists page by ``(created_at, id)`` descending — id breaks ties so the ordering is
total (two rows can share a timestamp). A cursor is an opaque token carrying the
last row's ``(created_at, id)``; the next page is everything strictly before it.
This is O(page) regardless of depth, unlike offset paging which scans and drops.

Flow: a repo fetches ``limit + 1`` rows, the service calls ``slice_page`` to peel
off the extra row (its presence is how we know another page exists) and mint the
next cursor from the last kept row.
"""

import base64
import binascii
from collections.abc import Callable
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")
R = TypeVar("R")


class Page(BaseModel, Generic[T]):
    """A page of ``items`` plus the cursor for the next one (None at the end)."""

    items: list[T]
    next_cursor: str | None = None


def encode_cursor(created_at: datetime, id_: int) -> str:
    raw = f"{created_at.isoformat()}|{id_}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Parse a cursor back to ``(created_at, id)``; raise ValueError if malformed.

    Callers (services) translate the ValueError into a 400 so a hand-edited
    cursor is a client error, not a 500.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts_str), int(id_str)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


def slice_page(
    rows: list[R], limit: int, key: Callable[[R], tuple[datetime, int]]
) -> tuple[list[R], str | None]:
    """Trim an over-fetched ``limit + 1`` result to a page + its next cursor.

    ``key`` pulls ``(created_at, id)`` off a row. If a row beyond ``limit`` came
    back, another page exists: drop it and mint the cursor from the last kept row.
    """
    if len(rows) > limit:
        rows = rows[:limit]
        return rows, encode_cursor(*key(rows[-1]))
    return rows, None


# --- id-only cursors ---
#
# Rows that carry no timestamp cannot page by ``(created_at, id)``. The vote
# tables are the case in point: one row per (user, target), no created_at, and
# nothing to add one for — the primary key is already monotonic, so id alone is
# a total order and a sufficient cursor.


def encode_id_cursor(id_: int) -> str:
    return base64.urlsafe_b64encode(str(id_).encode()).decode()


def decode_id_cursor(cursor: str) -> int:
    """Parse an id-only cursor; raise ValueError if malformed.

    Callers (the api layer) translate the ValueError into a 400, exactly as
    they do for the two-part cursor.
    """
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


def slice_page_by_id(
    rows: list[R], limit: int, key: Callable[[R], int]
) -> tuple[list[R], str | None]:
    """``slice_page`` for id-only cursors: trim ``limit + 1`` to a page plus
    the cursor for the next one."""
    if len(rows) > limit:
        rows = rows[:limit]
        return rows, encode_id_cursor(key(rows[-1]))
    return rows, None
