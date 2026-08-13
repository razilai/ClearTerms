#!/usr/bin/env bash
# Start ClearTerms. Two modes:
#   ./run.sh dev      infra in docker, backend + frontend on the host with hot
#                     reload. Ollama runs on the host. Fast iteration. (default)
#   ./run.sh docker   everything in containers (db, minio, ollama, backend,
#                     frontend) via docker compose. Prod-like, no host deps.
#
# Optional second arg picks the LLM: 4b (default) or 0.5b (tiny, faster/weaker).
# agent_model and model_version must move together or the analysis cache is
# poisoned (see app/core/config.py), so both are set from one place here.
#   ./run.sh dev 0.5b
#   ./run.sh docker 0.5b
set -e
cd "$(dirname "$0")"

mode="${1:-dev}"
model="${2:-4b}"

case "$model" in
4b)
    agent_model="gemma3:4b"
    model_version="gemma3-4b-v1"
    ;;
0.5b)
    agent_model="qwen2.5:0.5b"
    model_version="qwen2.5-0.5b-v1"
    ;;
*)
    echo "usage: $0 [dev|docker] [4b|0.5b]" >&2
    exit 2
    ;;
esac

case "$mode" in
docker)
    # Free ports first: dev mode leaves db/minio containers running detached, and
    # they bind the same ports the full graph wants (5432, 9000/9001). Tear them
    # down so the up below doesn't hit "address already in use".
    docker compose down
    # NOTE: a host Ollama on :11434 (from dev mode or the app) still clashes with
    # the ollama container. Stop it manually if you hit a bind error on 11434.

    # The 0.5b override flips the pulled model + backend env in one file.
    compose_files=(-f docker-compose.yml)
    [ "$model" = "0.5b" ] && compose_files+=(-f docker-compose.0.5b.yml)

    # Whole graph in containers; --build picks up code changes. Ctrl-C stops all.
    exec docker compose "${compose_files[@]}" up --build
    ;;

dev)
    trap 'kill 0' EXIT

    # The LLM backend is chosen in backend/.env (CLEARTERMS_LLM_PROVIDER). With
    # "openrouter" the host Ollama is unused and agent_model/model_version come
    # from backend/.env (an OpenRouter slug), so the 4b/0.5b wiring, the export
    # override, and the ollama serve/pull below are all skipped.
    provider="$(sed -n 's/^CLEARTERMS_LLM_PROVIDER=//p' backend/.env 2>/dev/null | tail -1)"
    provider="${provider:-ollama}"

    if [ "$provider" = ollama ]; then
        # Backend reads the model from env; export before uvicorn so the running
        # model matches the pulled one below and the cache version.
        export CLEARTERMS_AGENT_MODEL="$agent_model"
        export CLEARTERMS_MODEL_VERSION="$model_version"
    fi

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

        # Pull the chosen model on the host Ollama (no-op if already present).
        ollama pull "$agent_model"
    fi

    (cd backend && uv run uvicorn app.main:app --reload) &
    (cd frontend && npm run dev) &

    wait
    ;;

*)
    echo "usage: $0 [dev|docker] [4b|0.5b]" >&2
    exit 2
    ;;
esac
