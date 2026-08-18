#!/usr/bin/env bash
# Start ClearTerms. Two modes:
#   ./run.sh dev      infra in docker, backend + frontend on the host with hot
#                     reload. Ollama runs on the host. Fast iteration. (default)
#   ./run.sh docker   everything in containers (db, minio, ollama, backend,
#                     frontend) via docker compose. Prod-like, no host deps.
#
# The agent runs on qwen2.5:0.5b (backend default in app/core/config.py); the
# ollama serve/pull below bring it up on the host for dev mode.
set -e
cd "$(dirname "$0")"

mode="${1:-dev}"

case "$mode" in
docker)
    # Free ports first: dev mode leaves db/minio containers running detached, and
    # they bind the same ports the full graph wants (5432, 9000/9001). Tear them
    # down so the up below doesn't hit "address already in use".
    docker compose down
    # NOTE: a host Ollama on :11434 (from dev mode or the app) still clashes with
    # the ollama container. Stop it manually if you hit a bind error on 11434.

    # Whole graph in containers; --build picks up code changes. Ctrl-C stops all.
    exec docker compose up --build
    ;;

dev)
    trap 'kill 0' EXIT

    # The LLM backend is chosen in backend/.env (CLEARTERMS_LLM_PROVIDER). With
    # "openrouter" the host Ollama is unused and agent_model/model_version come
    # from backend/.env (an OpenRouter slug), so the ollama serve/pull below is
    # skipped.
    provider="$(sed -n 's/^CLEARTERMS_LLM_PROVIDER=//p' backend/.env 2>/dev/null | tail -1)"
    provider="${provider:-ollama}"

    # Ensure Postgres + MinIO are up (idempotent; skips if already healthy).
    docker compose up -d db minio

    # Create the bucket if it doesn't exist yet.
    docker compose run --rm createbucket

    # Apply any pending migrations.
    (cd backend && uv run alembic upgrade head)

    if [ "$provider" = ollama ]; then
        # Start Ollama only if it isn't already serving on :11434.
        if ! curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
            ollama serve &
            until curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; do
                sleep 0.5
            done
        fi

        # Pull the model on the host Ollama (no-op if already present). Must
        # match the backend default agent_model in app/core/config.py.
        ollama pull "qwen2.5:0.5b"
    fi

    (cd backend && uv run uvicorn app.main:app --reload) &
    (cd frontend && npm run dev) &

    wait
    ;;

*)
    echo "usage: $0 [dev|docker]" >&2
    exit 2
    ;;
esac
