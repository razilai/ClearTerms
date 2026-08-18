"""Unit tests: users repo."""



import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import users


async def test_create_user_then_read_back(session: AsyncSession) -> None:
    created = await users.create(session, "ada@example.com", "hashed-pw")
    assert created.id is not None, "flush should populate the PK"

    found = await users.get_by_email(session, "ada@example.com")
    assert found is not None
    assert found.id == created.id
    assert found.email == "ada@example.com"
    assert found.password_hash == "hashed-pw"


async def test_get_by_email_returns_none_when_absent(session: AsyncSession) -> None:
    await users.create(session, "ada@example.com", "hashed-pw")

    assert await users.get_by_email(session, "nobody@example.com") is None


async def test_create_user_duplicate_email_raises(session: AsyncSession) -> None:
    await users.create(session, "ada@example.com", "hashed-pw")

    with pytest.raises(IntegrityError):
        await users.create(session, "ada@example.com", "another-pw")


async def test_create_multiple_users(session: AsyncSession) -> None:
    u1 = await users.create(session, "ada@example.com", "pw1")
    u2 = await users.create(session, "bob@example.com", "pw2")

    assert u1.id != u2.id
    assert await users.get_by_email(session, "ada@example.com") is not None
    assert await users.get_by_email(session, "bob@example.com") is not None
