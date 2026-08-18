# CLAUDE.md

Guidance for working in this repo. For the product spec and design rationale,
read `README.md` (root) and `backend/README.md` first — this file covers the
current state of the code, not the vision.

## What ClearTerms is

Web app + Chrome extension that flags complex terms-of-service clauses and
explains them. Thin extension, smart backend. Core design: **analyze once,
filter per user** — each TOS is scored against a fixed set of clause categories,
cached by a hash of the normalized text, and each user's thumbs-up/down verdict
is computed at read time from cached scores filtered by their preference
checklist. Changing
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
  alembic/      migrations (env.py wired to settings + Base.metadata)
frontend/       React web app (Vite + TS + Mantine + TanStack Query)
  src/
    api/        types.ts (schema mirrors), client.ts (fetch wrapper), auth.ts, forum.ts
    auth/       context.ts, AuthContext.tsx (provider), useAuth.ts, RequireAuth.tsx, storage.ts
    pages/      LoginPage, SignupPage, PostListPage, NewPostPage, PostDetailPage,
                MessagesPage (layout stub), PersonalAreaPage
    components/ CommentItem, PreferencesPanel
tests/          test tiers as packages: unit/, integration/, system/
                  (per-module test_*.py + a factories.py of shared helpers per tier)
                + devserver.py (uvicorn on a throwaway Postgres container for frontend dev)
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

Backend covers auth, forum, and the analysis pipeline (analyze + history +
preferences); the web app frontend covers all of these. The Chrome extension
does **not exist yet** (see stubbed list below).

**Implemented:**
- **Auth** (`services/auth.py`, `api/auth.py`): signup, login, JWT issue/verify.
  Argon2 via `pwdlib`; login verifies against a dummy hash on unknown email so
  response time doesn't leak whether an email is registered; `verify_and_update`
  migrates hashes when argon2 params change. JWT `sub` stored as string (PyJWT
  ≥2.10), decode requires `exp`/`iat`/`sub`, 10s leeway. `POST /auth/signup`,
  `POST /auth/login` (OAuth2 password flow — email in the `username` field).
- **Forum** (phase 2, `services/forum.py`, `api/forum.py`): posts, comments,
  votes. Owner-only delete/edit checks live in the service. Services return API
  schemas (not ORM rows) because `author_email` needs a user-email join. Routes:
  `POST/GET /forum/posts`, `GET /forum/posts/mine` (own posts, same keyset page
  — declared *before* `/posts/{id}` or "mine" parses as an int id),
  `GET /forum/me/vote-totals` (post count + likes/dislikes across every post you
  wrote, for the personal-area header), `GET/DELETE /forum/posts/{id}`,
  `POST /forum/posts/{id}/comments`, `PATCH/DELETE /forum/comments/{id}`,
  `PUT /forum/posts/{id}/vote`, `PUT /forum/comments/{id}/vote` (body
  `{value: 1 | -1}`; re-sending the value you hold clears it). All require auth.
  Votes live in two tables (`post_votes`, `comment_votes`), each keyed
  `(user_id, target_id)` with `value` in `{-1, 1}`; both name the target column
  `target_id`, so one set of repo functions — parameterized on a constrained
  `TypeVar` — serves both. Every post/comment read carries `like_count`,
  `dislike_count`, and the viewer's `my_vote`, batched two queries per page.
  Posts (not comments) can be created with `is_anonymous: true`. Anonymity is
  display-only — `posts.user_id` is still recorded, so ownership, deletes and
  moderation are unchanged; `_post_out` is the single choke point that returns
  `author_email: null` to everyone except the author, who keeps seeing their own
  email so the owner-only UI (which compares it to the localStorage email) still
  works. `PostOut.is_anonymous` rides along so the author's own post can render
  an "Anonymous" badge. Anonymity is **inherited by the post author's own
  comments** on that post (`_comment_out`) — otherwise replying by name under
  your own anonymous post deanonymises it. Nothing is stored on `comments`: the
  mask is derived per read from `post.is_anonymous and comment.user_id ==
  post.user_id`, which is why `edit_comment` loads the owning post.
- **Analysis pipeline** (`services/analysis.py`, `api/analysis.py`): `POST /analyze`
  (normalize → hash → cache lookup → verdict + history append) and `GET
  /analyses/{id}` (per-category breakdown). `analysis_id` in the response *is* the
  `document_id` — the cache is keyed per document. `run_analysis` calls the agent
  and persists one `Analysis` row (plus its `Finding`s) per category.
- **History** (`services/history.py`, `api/history.py`): `GET /history` — every doc
  the user has had reviewed, newest first, with the document url joined in (service
  returns the API schema, like forum). Each entry's verdict is **recomputed** from
  the cached scores against current preferences, not read off
  `history_entries.verdict` — that column is an analyze-time snapshot, and a
  checklist the user can change afterwards would leave it disagreeing with the
  detail view. The snapshot survives as the fallback for documents with no cached
  scores at the current `model_version` (an empty score list would otherwise
  fabricate a thumbs-up). Costs two batched queries per page
  (`documents_repo.get_analyses_for_documents` + the user's prefs).
- **Preferences** (`services/preferences.py`, `api/preferences.py`): `GET/PUT
  /preferences` (full replace) plus `compute_verdict(scores, prefs)`. Preferences
  are a **binary checklist** — `preferences.enabled` is a bool, one row per
  category the user has saved; anything absent defaults to `DEFAULT_ENABLED =
  True` so a fresh account still gets a meaningful verdict. Policy: thumbs-down if
  any *enabled* category scored aggressive. The agent scores every category
  regardless of preferences, so unchecking one only hides it — re-checking it
  reveals it in analyses that already exist, retroactively. Unchecked categories
  are dropped from the report in the **frontend** (`AnalysisReport` reads the
  shared `['preferences']` query and filters; `GET /analyses/{id}` still returns
  everything, staying a pure per-document cache view). The report footers the
  hidden count so a suppressed aggressive clause never vanishes silently.
- **Shared deps** (`api/deps.py`): `SessionDep`, `CurrentUserDep`.
- **Config** (`core/config.py`): pydantic-settings, `CLEARTERMS_` env prefix.
- **Analysis queue** (`services/queue.py`): a bounded `asyncio.PriorityQueue`
  drained by `settings.analysis_workers` worker tasks, started and stopped from
  the lifespan hook in `app/main.py`. The queue **owns the session each job
  runs on** — callers must never close over their request session, since a job
  can wait a long time and a request session holds a pooled connection and,
  mid-transaction, locks for the whole wait; getting this wrong reintroduces
  the deadlock the design exists to avoid. Ordering is by
  `score = priority * settings.analysis_queue_alpha + sequence`, where priority
  is the submitter's count of in-flight jobs and sequence is a monotonic arrival
  counter. Priority alone means everyone's first job beats everyone's second —
  but on its own it starves, since a steady stream of *new* users supplies an
  unbounded number of priority-0 arrivals to overtake a second job. Sequence is
  the ageing term that bounds it: an entry at priority p can be overtaken by at
  most `p * alpha` later arrivals, after which nothing new can pass it. Alpha is
  the dial between the two properties — read it as "how many other users' first
  jobs may jump ahead of your second job" — and strict first-beats-second holds
  only within that window, deliberately. Entries already queued age uniformly,
  so ageing never reorders them among themselves and needs no heap traversal;
  adding the term to newcomers is equivalent to decrementing everyone else.
  A full queue raises `QueueFullError` (503). A caller
  whose total wait — queued **plus** running, since the timeout wraps the whole
  submit — passes `settings.analysis_queue_timeout_seconds` gets
  `QueueTimeoutError` (504), with the job left running via `asyncio.shield` so
  the cache still gets populated and a retry is likely a cache hit. A caller
  still parked when `stop()` runs gets `QueueShutdownError` (503 + `Retry-After`),
  whether its job was still queued or already running: shutdown cancels the
  workers and then drains the queue, resolving every waiting caller and
  releasing its in-flight count, rather than dropping connections. `submit`
  after `stop()` raises rather than enqueueing onto a queue nothing will drain.
  Cache hits never enqueue.
  Caveat: the queue is per process — multiple uvicorn workers each get their
  own, so the concurrency cap multiplies and fairness only holds within a
  process; fixing that needs an out-of-process broker, which means expressing
  jobs as data rather than callables.
- **Frontend** (`frontend/`): login/signup, forum, **and analysis** — analyze,
  history, analysis-detail pages against the routes above. Nav sections are
  §1 Analysis, §2 History, §3 Forum, §4 Messages, §5 Personal Area. There is no
  Settings page: the preference checklist lives in `components/PreferencesPanel.tsx`
  and is mounted inside `/me`, with `/settings` redirecting there. `/me`
  (`PersonalAreaPage`) also shows the vote totals and the user's own posts.
  Forum and History page 15 at a time, the personal area's own-posts list 5.
  All three use discrete pages, not infinite scroll: `lib/useKeysetPages.ts`
  holds the stack of visited cursors (the backend cursor is forward-only, so
  walking back means replaying one) and `components/Pager.tsx` renders the
  controls. `goNext` takes the current page's `next_cursor` as an argument
  rather than closing over it — the caller only learns it from a query the
  hook's own `cursor` keys, so passing it in at construction would be a cycle.
  Post *comments* (`PostDetailPage`) still load-more; only the two top-level
  lists were converted. `/messages` is layout only (no DM backend).
  Session = JWT + email in localStorage (no `/me` endpoint; ownership
  UI compares `author_email` to the stored email — server still enforces via 403).
  Backend calls are namespaced under **`/api`**, added in `api/client.ts::request`
  and stripped again by the proxy (`vite.config.ts` in dev, `frontend/nginx.conf`
  in docker) — the backend itself stays unprefixed. The namespace is what keeps
  API paths from shadowing SPA routes: `/forum`, `/history` and `/analyze` are
  both pages and endpoints, and a refresh is a plain GET the proxy cannot tell
  apart from an API call, so it used to answer raw JSON. Callers still pass
  backend-relative paths. No CORS configured on the backend (deliberate — revisit
  at deployment). Vote state (`like_count`, `dislike_count`, `my_vote`) ships on
  every post and comment read, so buttons render pressed-state on first paint.

**Stubbed / not implemented:**
- **Messages (DM)**: `pages/MessagesPage.tsx` is a two-pane layout placeholder.
  No model, no routes, no service — the section exists so the shape is settled.
- **Logging** (`core/logging.py::setup_logging`) is a no-op — wired into lifespan
  but not configured yet.
- `services/forum.py::check_rate_limit` raises `NotImplementedError` (phase-2
  guardrail, not wired yet).

The agent (`agent/classifier.py::analyze`) is fully implemented: chunk →
classify each chunk against Ollama → verbatim-evidence check → densify to one
score per category. It needs a live Ollama; tests run it against a tiny model.

## Working on the backend

```bash
cd backend
uv sync
docker compose up -d db                    # Postgres 16 on :5432 (from repo root)
uv run alembic upgrade head                # apply migrations to the fresh db
uv run uvicorn app.main:app --reload       # GET /health → {"status":"ok"}
```

The db is Postgres. `init_db` only pings it at startup — the schema is owned by
**Alembic**, not `create_all`. After changing a model:

```bash
uv run alembic revision --autogenerate -m "what changed"   # review the output
uv run alembic upgrade head
```

An autogenerate that produces an empty migration means the db matches the models.

Lint / typecheck / test:
```bash
uv run ruff check .
uv run mypy .
uv run pytest                              # from backend/ — pytest config lives in backend/pyproject.toml
```

Tests are organised by **tier package** — `tests/{unit,integration,system}/`,
each a package (has `__init__.py`, needed so same-named files like
`unit/test_auth.py` and `integration/test_auth.py` don't collide) of per-module
`test_*.py` files plus a `factories.py` of helpers shared within that tier.
`asyncio_mode = "auto"`. Run one tier from `backend/` with
`uv run pytest -c pyproject.toml ../tests/unit` — passing a path shifts pytest's
rootdir to the repo root (which has no `pyproject.toml`) and silently drops this
project's config, so `-c pyproject.toml` is required to keep rootdir on
`backend/`. A bare `uv run pytest` (no path) needs no `-c`.

## Working on the frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api/* to :8000 (prefix stripped)
npm run build      # tsc -b && vite build — this is the typecheck gate
npm run lint       # oxlint
```

A plain `uvicorn app.main:app` needs the compose Postgres up and migrations
applied. For frontend dev, `devserver.py` instead spins up a throwaway Postgres
container (testcontainers), builds the schema from the ORM metadata, and serves
the real app — state resets when the process exits. Needs Docker:

```bash
uv run --project backend python tests/devserver.py    # from repo root
```

## Testing notes

- Tests run against a real **Postgres** database in a throwaway container
  (testcontainers), matching prod — no SQLite, so dialect differences (FK
  enforcement, types) can't hide until runtime. One container per session; the
  schema is built once. Per-test isolation is an outer transaction that is always
  rolled back, so tests never see each other's rows (schema is never rebuilt).
- Fixtures: `session` (AsyncSession bound to the per-test transaction), `client`
  (httpx ASGITransport; overrides `get_session` to share `session`, so flushes
  are visible across requests without a commit), `committing_client` (each
  request gets its own committing session on the shared connection — tests the
  real transaction boundary), `auth_headers` (signs up alice@example.com). Needs
  Docker; CI runs on `ubuntu-latest` which has it.
- Testing strategy is **hybrid**: test-first for backend logic (analysis
  pipeline, preference matching, API contracts); build-first for UI/extension.

## Pre-push hook

`.githooks/pre-push` mirrors CI's fast gates (backend ruff + mypy, frontend
lint) so a lint/type failure can't reach the pipeline. It is **not** active
until each clone opts in — `core.hooksPath` is local config, not versioned:

```bash
git config core.hooksPath .githooks    # one-time, per clone
```

Heavy gates (pytest, frontend build) need Docker + Ollama and stay CI-only.
Bypass once with `git push --no-verify`.

## Stack

FastAPI · SQLAlchemy 2.0 async + asyncpg · Alembic · Pydantic v2 · PyJWT ·
pwdlib[argon2] · PydanticAI + Ollama (Qwen2.5-7B-Instruct) · uv for deps · ruff +
mypy. **PostgreSQL** (`docker-compose.yml` runs postgres:16); tests + devserver
use testcontainers.

## Conventions

- Async throughout (async SQLAlchemy sessions, async routes).
- Keep the layer boundaries above; don't let `api` reach past `services`.
- Bump `settings.model_version` on model/prompt changes to invalidate cached
  analyses.
- **Input length caps** live in `core/config.py` (`max_*_chars`) and are enforced
  by the Pydantic schemas; `frontend/src/lib/limits.ts` hand-mirrors them for UX
  only — change both together. Login is the exception: it arrives as OAuth2 form
  data with no schema, so `services/auth.py::login` checks the email/password
  caps itself, **before** touching argon2 (hashing an unbounded password is the
  CPU-burn the cap exists to stop), and answers 401 rather than 422. The analyze
  paste box is bounded in *bytes* by `max_analyze_bytes` in `api/analysis.py`
  (413), not by a schema `max_length`; the frontend never sets `maxLength` on it
  — the browser applies `maxLength` before React sees the paste, and silent
  truncation of a pasted TOS would yield a confident verdict on a document the
  user never submitted. `AnalyzePage` instead clips in `onChange`, which caps the
  value identically but keeps the dropped count, shown in an alert under the
  always-visible `CharCount`.
