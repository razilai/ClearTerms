# ClearTerms

## General Description

ClearTerms is a web app and Chrome extension that helps you identify complex or uncommon terms-of-service clauses and provides simplified explanations for better understanding.

The extension automatically detects TOS on registration forms and sends the text to the backend, where it is analyzed once against a fixed set of clause categories. Your personal preferences decide which categories matter to you.

- Standard TOS → the extension shows a "thumbs up" icon.
- Complex TOS → the extension shows a "thumbs down" icon with a link to the web app for a per-clause breakdown and simplified explanations.

The web app holds your preferences and the history of TOS you've reviewed. A community forum for discussing specific clauses is planned for phase 2.

## Architecture

**Thin extension, smart backend.**

- **Chrome extension**: detects TOS, extracts raw text from the page/linked document, sends it to the backend, renders the verdict icon. No analysis logic client-side.
- **Backend (FastAPI)**: cleans and chunks text, checks the analysis cache, runs the LLM agent, applies user preferences to produce a verdict, stores history.
- **LLM agent (PydanticAI + Ollama)**: runs server-side next to the backend. Classifies each TOS against all clause categories with few-shot prompting.
- **Web app (React)**: auth, preferences, history, detailed analysis view; forum in phase 2.

### Analyze once, filter per user

Analysis is **preference-independent**:

1. Each TOS is scored against a fixed set of clause categories (e.g. data selling, arbitration clauses, unilateral changes, content licensing, auto-renewal, ...).
2. The result is cached, keyed by a hash of the normalized text — one analysis serves all users and all future visits.
3. A user's verdict (thumbs up/down) is computed at read time: cached category scores × the user's preference weights. Changing preferences never re-triggers analysis.

## Core Flows

### First usage

1. Sign up / sign in (web app).
2. On first sign-in, the user sets their preferences: which clause categories they care about and how strictly.
3. Preferences are saved in the database.
4. The user connects the extension to their account (see Auth below).

### Preferences update

1. Settings page sends an update request; verdicts on already-analyzed TOS update instantly (no re-analysis needed).

### Entering a website

1. Extension checks heuristically whether the site has a TOS (registration form present, common TOS link patterns, etc.).
2. Alternatively, clicking the extension icon triggers detection manually.
3. Extension extracts the raw TOS text and sends it to the backend.
4. Backend pipeline:
    - Normalize text and compute its hash.
    - Cache hit → skip to step 6.
    - Clean the text; chunk by TOS section headings, falling back to ~3k-token windows with ~200-token overlap.
    - Agent classifies each chunk against all clause categories; per-category score = max across chunks.
    - Analysis is saved to the cache.
5. Backend applies the user's preferences to the category scores → verdict.
6. Verdict is returned to the extension ("thumbs up" / "thumbs down") and appended to the user's history. Thumbs down includes a deep link to the web app's detailed view.

### Auth (extension ↔ backend)

- Web app: standard session/JWT login.
- Extension: token handoff via `externally_connectable` — user logs into the web app, the web page detects the extension and sends a JWT via `chrome.runtime.sendMessage` (web app domain whitelisted in the manifest); the extension stores it in `chrome.storage.local`. Fallback: manual token paste from the settings page.
- No anonymous mode: analysis requires an account.

## Data Model (sketch)

- **User**: id, email, password hash, created_at
- **Preference**: user_id, category, weight/threshold
- **Document**: id, text_hash (unique), url, normalized_text, created_at
- **Analysis**: document_id, category, score, explanation snippet, model version
- **HistoryEntry**: user_id, document_id, verdict, timestamp
- Phase 2: **Post**, **Comment**, **Like**

## API (sketch)

- `POST /auth/signup`, `POST /auth/login`
- `GET/PUT /preferences`
- `POST /analyze` — body: raw text + source URL; returns verdict + analysis id
- `GET /analyses/{id}` — detailed per-category breakdown
- `GET /history`
- Phase 2: `/forum/...`

## Phases

### Phase 1 — MVP

- Auth + preferences
- Extension: detection heuristics, text extraction, verdict icon
- Backend: analysis pipeline with hash-based cache
- Web app: preferences page, history page, detailed analysis view

### Phase 2

- Forum: new post, comment, like, delete post/comment, edit comment
- Forum rate limits and basic moderation
- Simplified clause explanations improvements (better prompts, category tuning)

## Guardrails

- Priority queue for TOS analysis — prevents a single user from spamming the system with analysis requests; cache makes repeat requests free.
- Request size limits on `/analyze`.
- Phase 2: forum posting rate limits.

## Engineering Decisions

- **Testing — hybrid**: test-first for backend logic (analysis pipeline, preference matching, API contracts); build-first for UI and extension, tests added once the shape stabilizes.
- **Database — SQLite** for MVP; revisit (Postgres) if concurrent writes from the analysis queue + forum become a bottleneck.
- **LLM — Qwen2.5-7B-Instruct via Ollama**; PydanticAI structured output enforces the classification schema and keeps the agent code provider-agnostic in case a hosted model is needed later. `model_version` on Analysis rows handles cache invalidation on model/prompt changes.
- **CI/CD — GitHub Actions.** PR pipeline: lint (ruff + eslint) → typecheck (mypy + tsc) → unit tests (pytest + vitest) → build check (docker compose build, extension zip). LLM calls are mocked in CI; a small hand-labeled eval set (~20 TOS) runs as a separate manual/nightly job against the real model to catch prompt-quality drift. CD deferred until a deployment target exists (tag → build image → push registry → deploy).
- **Extension auth — `externally_connectable` token handoff** (see Auth section). No anonymous mode.

## Open Questions

- Clause category taxonomy: categories to be defined manually (not derived from external sources), plus few-shot examples per category.
- Per-category scoring scale (e.g. 0–2: absent / present-standard / present-aggressive) — finalize alongside the taxonomy.

## Tech Stack

- PydanticAI + Ollama: LLM and agents (server-side)
- SQLite: database
- FastAPI: backend
- React: frontend (web app)
- Chrome extension: Manifest V3
