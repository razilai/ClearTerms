# syntax=docker/dockerfile:1
FROM python:3.11-slim

# uv: fast, reproducible installs from the committed lockfile. Pinned (not
# :latest) so image builds are reproducible; bump deliberately with CI's setup-uv.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /app

# ffmpeg + ffprobe for video transcoding and duration probing
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Non-root runtime user. Created before installs so we can hand it /app ownership.
RUN useradd --create-home --uid 10001 appuser

# Install deps first (cached until the lockfile changes), then the app source.
# --mount=type=cache reuses uv's package cache across builds without baking it in.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# Drop root: hand the app + its venv to appuser and run as them.
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness for compose `condition: service_healthy` (frontend waits on this).
# Uses stdlib urllib so no extra package (curl) is needed in the image.
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# alembic upgrade head brings a fresh db to the current schema, then serve. The
# entrypoint waits on nothing here — compose gates startup on the db healthcheck.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
