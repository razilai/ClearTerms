"""Unit tests: forum repo (votes upsert/toggle/count)."""


from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import forum as forum_repo
from app.models import PostVote, User

# --- vote repo --------------------------------------------------------------
#
# Repo-level, on the shared `session`: set_vote is an upsert and the count/
# my-vote reads are pure queries, so no committing harness is needed. The
# route wiring (toggle-clears, switch-sides, my_vote per user) is covered over
# HTTP in integration/test_votes.py.


async def test_vote_repo_counts_and_toggles(session: AsyncSession) -> None:
    """set_vote is an upsert; count_votes splits likes from dislikes."""
    from app.schemas.forum import PostCreate

    user = User(email="votes@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    post = await forum_repo.create_post(
        session, user.id, PostCreate(title="t", body="b")
    )

    await forum_repo.set_vote(session, PostVote, user.id, post.id, 1)
    counts = await forum_repo.count_votes(session, PostVote, [post.id])
    assert counts[post.id] == (1, 0)

    # Same (user, post) again with the opposite value updates in place — the
    # unique constraint means a second insert would raise instead.
    await forum_repo.set_vote(session, PostVote, user.id, post.id, -1)
    counts = await forum_repo.count_votes(session, PostVote, [post.id])
    assert counts[post.id] == (0, 1)

    mine = await forum_repo.get_my_votes(session, PostVote, user.id, [post.id])
    assert mine == {post.id: -1}

    await forum_repo.remove_vote(session, PostVote, user.id, post.id)
    assert await forum_repo.count_votes(session, PostVote, [post.id]) == {}
    assert await forum_repo.get_my_votes(session, PostVote, user.id, [post.id]) == {}
