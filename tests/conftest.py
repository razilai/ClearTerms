"""Shared pytest fixtures.

Run from backend/ so the editable install resolves `app`:

    uv run --project backend pytest

Fixtures to add as implementation lands: async test engine (in-memory SQLite),
session override for app.db.engine.get_session, httpx.AsyncClient against
app.main.app, and a monkeypatched app.agent.classifier.classify_chunk.
"""
