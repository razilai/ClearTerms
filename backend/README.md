# ClearTerms — Backend

FastAPI backend. Cleans and chunks TOS text, runs the LLM agent, caches the
analysis, applies user preferences to produce a verdict, stores history.

See the [root README](../README.md) for the product overview and the
**"Analyze once, filter per user"** design that this layout is built around.

## Layer rules

Dependencies flow one direction. Keep them that way:

```
api  →  services  →  { db, agent }
              ↘  agent → prompts
core  (shared by all; imports from none of the above)
```

- `api` never touches `db` or `agent` directly — it goes through `services`.
- `agent` never sees the cache, db, or user preferences — plain text in,
  structured scores out.
- `core` is a leaf: it may not import from `api`, `services`, `agent`, or `db`.

## Folders — what goes where, what to implement

### `app/main.py`

FastAPI app entrypoint. Currently just mounts `/health`. Wire the `api` routers
here as they land.

### `app/api/`

HTTP layer. FastAPI routers and request/response wiring **only — no business
logic**. Routes validate input with `app.schemas` and delegate to
`app.services`.

Implement the routes from the root README's API sketch: `POST /auth/signup`,
`POST /auth/login`, `GET/PUT /preferences`, `POST /analyze`,
`GET /analyses/{id}`, `GET /history`.

### `app/services/`

Business logic. The only layer allowed to combine db, agent, and preferences.
Stub files already mark the seams:

- `auth.py` — signup, login, JWT issue/verify, password hashing.
- `preferences.py` — preference CRUD + **verdict computation** at read time
  (cached category scores × user weights). Changing preferences never
  re-triggers analysis.
- `analysis.py` — the analysis pipeline (preference-independent): normalize →
  hash → cache lookup; on miss clean, chunk, call `app.agent`, take per-category
  max across chunks, persist to cache keyed by `text_hash + model_version`.
  Owns the seam between the LLM and the rest of the system.
- `queue.py` — priority queue guardrail so one user can't spam analysis; cache
  hits skip the queue.

### `app/agent/`

LLM agent layer (PydanticAI + Ollama). Owns everything model-facing: prompt
loading, request construction, response parsing. Called **only** by services;
must stay unaware of cache, db, and preferences. Classifies each TOS chunk
against all clause categories with few-shot prompting; PydanticAI structured
output enforces the classification schema.

### `app/agent/prompts/`

Prompt templates. Package exists so `prompts.toml` can be loaded via
`importlib.resources` instead of filesystem paths. Put prompt text and few-shot
examples here.

### `app/db/`

Persistence layer. Engine/session setup and data access. **Accessed only
through services** — api routes never touch the db directly. SQLite for MVP.

### `app/models/`

Database models. ORM entities **only** — not the API surface. See the root
README data model: `User`, `Preference`, `Document`, `Analysis`,
`HistoryEntry` (phase 2: `Post`, `Comment`, `Like`).

### `app/schemas/`

API contracts. Pydantic request/response schemas, **decoupled from
`app.models`** so the wire format can evolve independently of storage.

### `app/core/`

Cross-cutting infrastructure: settings, logging, shared helpers. A leaf layer —
nothing here may import from `api`, `services`, `agent`, or `db`.

### `data/`

Runtime data (SQLite db file, etc.). Not source. Keep out of version control.

## Build files

- `pyproject.toml` — deps + hatchling packaging (`app` package).
- `uv.lock` — locked deps. Use `uv` to install/run.
- `Dockerfile` — container build (referenced by root `docker-compose.yml`).

## Run

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health` → `{"status": "ok"}`.
