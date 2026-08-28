# https://hub.docker.com/_/python
FROM python:3.11.3-slim-bullseye

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
WORKDIR $APP_HOME

RUN pip install poetry

COPY . ./

# libpq-dev and gcc are needed for psycopg2 compilation
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    build-essential \
    --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

RUN poetry install --without dev

# Environment variables — pass at runtime via -e or docker-compose
ARG DATABASE_URL
ENV DATABASE_URL=$DATABASE_URL

ARG OPENAI_API_KEY
ENV OPENAI_API_KEY=$OPENAI_API_KEY

ARG SUPABASE_URL
ENV SUPABASE_URL=$SUPABASE_URL

ARG SUPABASE_SERVICE_ROLE_KEY
ENV SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY

ARG SUPABASE_STORAGE_BUCKET
ENV SUPABASE_STORAGE_BUCKET=$SUPABASE_STORAGE_BUCKET

CMD ["poetry", "run", "start"]
