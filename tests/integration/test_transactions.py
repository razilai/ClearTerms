"""Integration tests: request transaction boundary (committing_client)."""


import httpx

# --- request transaction boundary ---
#
# Uses `committing_client`, not `client`: see that fixture's docstring for why
# the shared-session client cannot catch a missing commit.


async def test_writes_persist_across_requests(
    committing_client: httpx.AsyncClient,
) -> None:
    """Signup in one request must be readable by a later, separate request.

    Both requests run on their own session, so the user row is only visible to
    the second one because get_session committed the first. Drop the commit and
    the signup is rolled back at session close, and the login 401s.
    """
    signup = await committing_client.post(
        "/auth/signup", json={"email": "persist@example.com", "password": "s3cretpass"}
    )
    assert signup.status_code == 201, signup.text

    login = await committing_client.post(
        "/auth/login",
        data={"username": "persist@example.com", "password": "s3cretpass"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]
