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

# Docker Compose expands every service in docker-compose.yml, even when dev mode
# starts only db and minio. The repo-root .env is ignored by Git and Compose
# reads it automatically. Dev mode creates secure, per-checkout values there so
# a fresh clone starts without manual secret setup.
compose_secret_is_set() {
    local name="$1" value

    # An explicitly exported value takes precedence over .env, just as it does
    # for Docker Compose. An empty exported value is therefore still invalid.
    if [[ -v "$name" ]]; then
        [[ -n "${!name}" ]]
        return
    fi

    [[ -f .env ]] || return 1
    value="$(sed -n "s/^[[:space:]]*${name}[[:space:]]*=[[:space:]]*//p" .env | tail -n 1)"
    value="${value%$'\r'}"
    [[ -n "$value" && "$value" != '""' && "$value" != "''" ]]
}

check_compose_secrets() {
    local required=(CLEARTERMS_JWT_SECRET POSTGRES_PASSWORD MINIO_ROOT_PASSWORD)
    local missing=() name

    for name in "${required[@]}"; do
        compose_secret_is_set "$name" || missing+=("$name")
    done

    if ((${#missing[@]})); then
        printf 'Missing Docker Compose secret(s): %s\n' "${missing[*]}" >&2
        printf 'Create the repo-root .env from .env.example, then set those values.\n' >&2
        printf '  cp -n .env.example .env\n' >&2
        printf 'Generate each secret with: openssl rand -hex 32\n' >&2
        return 1
    fi
}

set_compose_secret() {
    local name="$1" value="$2"

    # Replace an empty entry copied from .env.example. Values generated here are
    # hexadecimal, so they are safe to interpolate into this expression.
    if grep -qE "^[[:space:]]*${name}[[:space:]]*=" .env; then
        sed -i -E "s|^([[:space:]]*${name}[[:space:]]*=).*|\\1${value}|" .env
    else
        printf '%s=%s\n' "$name" "$value" >> .env
    fi
}

ensure_dev_compose_secrets() {
    local required=(CLEARTERMS_JWT_SECRET POSTGRES_PASSWORD MINIO_ROOT_PASSWORD)
    local name value created=0

    if [[ ! -f .env ]]; then
        cp .env.example .env
        created=1
    fi

    # Local secrets should not be readable by other users on the development
    # machine. This does not affect a caller-provided environment variable.
    chmod 600 .env

    for name in "${required[@]}"; do
        # Compose gives an exported variable precedence over .env. Do not
        # silently generate a value that Compose would then ignore.
        if [[ -v "$name" && -z "${!name}" ]]; then
            printf 'Unset empty exported %s so dev mode can use .env.\n' "$name" >&2
            return 1
        fi

        if ! compose_secret_is_set "$name"; then
            value="$(openssl rand -hex 32)"
            set_compose_secret "$name" "$value"
            printf 'Generated development-only %s in .env.\n' "$name"
        fi
    done

    if ((created)); then
        printf 'Created .env with development-only Docker credentials.\n'
    fi
}

mode="${1:-dev}"

case "$mode" in
docker)
    check_compose_secrets

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
    ensure_dev_compose_secrets

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
