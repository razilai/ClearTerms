#!/usr/bin/env bash
# Start ClearTerms. Two modes:
#   ./run.sh dev      infra in docker, backend + frontend on the host with hot
#                     reload. Ollama runs on the host. Fast iteration. (default)
#   ./run.sh docker   everything in containers (db, minio, ollama, backend,
#                     frontend) via docker compose. Prod-like, no host deps.
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

    # Ensure Postgres + MinIO are up (idempotent; skips if already healthy).
    docker compose up -d db minio

    # Create the bucket if it doesn't exist yet.
    docker compose run --rm createbucket

    # Apply any pending migrations.
    (cd backend && uv run alembic upgrade head)

    # Start Ollama only if it isn't already serving on :11434.
    if ! curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
      ollama serve &
      until curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; do
        sleep 0.5
      done
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
