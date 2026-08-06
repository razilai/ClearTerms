#!/usr/bin/env bash
# Dev helper: run backend + frontend together. Ctrl-C stops both.
set -e
cd "$(dirname "$0")"

trap 'kill 0' EXIT

(cd backend && uv run uvicorn app.main:app --reload) &
(cd frontend && npm run dev) &

wait
