# syntax=docker/dockerfile:1
FROM python:3.11-slim

# uv: fast, reproducible installs from the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install deps first (cached until the lockfile changes), then the app source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# alembic upgrade head brings a fresh db to the current schema, then serve. The
# entrypoint waits on nothing here — compose gates startup on the db healthcheck.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
