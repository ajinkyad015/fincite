# https://hub.docker.com/_/python
FROM python:3.11.3-slim-bullseye

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
WORKDIR $APP_HOME

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . ./

# libpq-dev and gcc are needed for psycopg2 compilation
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    build-essential \
    --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

RUN uv sync --frozen --no-dev

# Pre-download NLTK tokenizer data
RUN uv run python -m nltk.downloader punkt punkt_tab

CMD ["uv", "run", "start"]
