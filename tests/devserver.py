"""Run the backend with the in-memory fake repos from tests/fakes.py.

The real DB layer (app/db/repos) is not implemented yet, so `uvicorn
app.main:app` 500s on any endpoint that touches persistence. This harness
serves the same app with the fakes installed — enough for frontend
development against live auth + forum endpoints. State resets on restart.

    uv run --project backend python tests/devserver.py
"""

import sys
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import uvicorn

from tests.fakes import FakeStore, install


def main() -> None:
    install(pytest.MonkeyPatch(), FakeStore())

    from app.db.engine import get_session
    from app.main import app

    async def _null_session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_session] = _null_session
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
