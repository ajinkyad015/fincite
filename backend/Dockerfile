# https://hub.docker.com/_/python
FROM python:3.11.3-slim-bullseye

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
WORKDIR $APP_HOME

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# No gcc / build-essential / libpq-dev needed: psycopg2-binary and
# psycopg[binary] ship manylinux wheels, so nothing compiles at build time.

# Install dependencies in their own layer so code changes don't bust the cache.
# --no-install-project: only the locked dependencies; the project itself needs
# the source, which is copied below.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Pre-download NLTK tokenizer data (rides the cached dependency layer)
RUN .venv/bin/python -m nltk.downloader punkt punkt_tab

# Add the source and install the project itself
COPY . ./
RUN uv sync --frozen --no-dev

# Run the venv entrypoint directly: `uv run start` would re-sync the
# environment (dev group included by default) on every container start.
CMD ["/app/.venv/bin/start"]