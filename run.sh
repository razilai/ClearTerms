#!/usr/bin/env bash
# Dev helper: run backend + frontend together. Ctrl-C stops both.
set -e
cd "$(dirname "$0")"

trap 'kill 0' EXIT

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
