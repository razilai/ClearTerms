# CLAUDE.md

Guidance for working in this repo. For the product spec and design rationale,
read `README.md` (root) and `backend/README.md` first — this file covers the
current state of the code, not the vision.

## What ClearTerms is

Web app + Chrome extension that flags complex terms-of-service clauses and
explains them. Thin extension, smart backend. Core design: **analyze once,
filter per user** — each TOS is scored against a fixed set of clause categories,
cached by a hash of the normalized text, and each user's thumbs-up/down verdict
is computed at read time from cached scores × their preference weights. Changing
preferences never re-triggers analysis.

## Repo layout

```
backend/        FastAPI backend
  app/
    main.py     app entrypoint: /health, router mount, lifespan (logging, init_db, queue)
    api/        HTTP layer — routers + request/response wiring ONLY, no logic
    services/   business logic — the only layer that combines db + agent + preferences
    agent/      LLM agent (PydanticAI + Ollama) — plain text in, structured scores out
    db/         persistence — engine + repos; reached only through services
    models/     SQLAlchemy ORM entities
    schemas/    Pydantic wire contracts, decoupled from models
    core/       settings, logging — leaf layer, imports from none of the above
  data/         runtime SQLite db (gitignored)
frontend/       React web app (Vite + TS + Mantine + TanStack Query)
  src/
    api/        types.ts (schema mirrors), client.ts (fetch wrapper), auth.ts, forum.ts
    auth/       context.ts, AuthContext.tsx (provider), useAuth.ts, RequireAuth.tsx, storage.ts
    pages/      LoginPage, SignupPage, PostListPage, NewPostPage, PostDetailPage
    components/ CommentItem
tests/          test tiers: unit.py, integration.py, system.py, security.py, stress.py
                + devserver.py (fake-backed uvicorn for frontend dev)
docker-compose.yml, backend/Dockerfile
```

## Layer rules (enforced by convention — keep them)

```
api  →  services  →  { db, agent }
core  (shared leaf; imports from none of the above)
```

- `api` never touches `db` or `agent` directly — always via `services`.
- `agent` never sees cache, db, or preferences.
- Services raise **domain exceptions** (`app/services/exceptions.py`), never
  `fastapi.HTTPException`. `app/api/errors.py` maps them to HTTP responses via a
  single `DomainError` handler registered in `main.py`. Add a new failure mode by
  adding an exception subclass + a `case` in the handler.

## Current state (as of feature-forum branch)

Backend is skeleton + two implemented slices; the web app frontend covers those
same slices (auth + forum). The Chrome extension does **not exist yet**.

**Implemented:**
- **Auth** (`services/auth.py`, `api/auth.py`): signup, login, JWT issue/verify.
  Argon2 via `pwdlib`; login verifies against a dummy hash on unknown email so
  response time doesn't leak whether an email is registered; `verify_and_update`
  migrates hashes when argon2 params change. JWT `sub` stored as string (PyJWT
  ≥2.10), decode requires `exp`/`iat`/`sub`, 10s leeway. `POST /auth/signup`,
  `POST /auth/login` (OAuth2 password flow — email in the `username` field).
- **Forum** (phase 2, `services/forum.py`, `api/forum.py`): posts, comments,
  likes. Owner-only delete/edit checks live in the service. Services return API
  schemas (not ORM rows) because `author_email` needs a user-email join. Routes:
  `POST/GET /forum/posts`, `GET/DELETE /forum/posts/{id}`,
  `POST /forum/posts/{id}/comments`, `PATCH/DELETE /forum/comments/{id}`,
  `PUT /forum/posts/{id}/like` (toggle). All require auth.
- **Shared deps** (`api/deps.py`): `SessionDep`, `CurrentUserDep`.
- **Config** (`core/config.py`): pydantic-settings, `CLEARTERMS_` env prefix.
- **Frontend** (`frontend/`): login/signup + forum pages against the routes
  above. Session = JWT + email in localStorage (no `/me` endpoint; ownership UI
  compares `author_email` to the stored email — server still enforces via 403).
  Vite dev server proxies `/auth` and `/forum` to `:8000`; no CORS configured on
  the backend (deliberate — revisit at deployment). Known gap: `GET
  /forum/posts/{id}` doesn't say whether the current user liked the post, so the
  like button has no initial pressed-state.

**Stubbed / not implemented:**
- Analysis pipeline (`services/analysis.py`), preferences verdict computation,
  the agent layer, and the priority queue.
- `services/forum.py::check_rate_limit` raises `NotImplementedError` (phase-2
  guardrail, not wired yet).
- Note: `api/__init__.py` still comments the forum router as "501s until
  implemented" — stale; forum is now implemented.

## Working on the backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload      # GET /health → {"status":"ok"}
```

Lint / typecheck / test:
```bash
uv run ruff check .
uv run mypy .
uv run pytest                              # from backend/ — pytest config lives in backend/pyproject.toml
```

Test modules are named by **tier**, not `test_*.py`; `pyproject.toml` lists them
under `python_files` or pytest skips them. `asyncio_mode = "auto"`.

## Working on the frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /auth + /forum to :8000
npm run build      # tsc -b && vite build — this is the typecheck gate
npm run lint       # oxlint
```

The real DB repos are `NotImplementedError` stubs, so a plain
`uvicorn app.main:app` 500s on anything but `/health`. Run the backend for
frontend dev with the in-memory fakes instead (state resets on restart):

```bash
uv run --project backend python tests/devserver.py    # from repo root
```

## Testing notes

- The DB layer isn't implemented yet. `tests/fakes.py` patches `app.db.repos`
  with in-memory fakes; `conftest.py` overrides the session dependency to yield
  `None` (unused by fakes). When the real DB lands, swap for an in-memory SQLite
  engine + session override — the endpoint tests stay valid.
- Fixtures: `store` (FakeStore), `client` (httpx ASGITransport), `auth_headers`
  (signs up alice@example.com and returns a Bearer header).
- Testing strategy is **hybrid**: test-first for backend logic (analysis
  pipeline, preference matching, API contracts); build-first for UI/extension.

## Stack

FastAPI · SQLAlchemy 2.0 async + aiosqlite · Pydantic v2 · PyJWT · pwdlib[argon2]
· PydanticAI + Ollama (Qwen2.5-7B-Instruct) · uv for deps · ruff + mypy.
SQLite for MVP (revisit Postgres if the analysis queue + forum contend on writes).

## Conventions

- Async throughout (async SQLAlchemy sessions, async routes).
- Keep the layer boundaries above; don't let `api` reach past `services`.
- Bump `settings.model_version` on model/prompt changes to invalidate cached
  analyses.
