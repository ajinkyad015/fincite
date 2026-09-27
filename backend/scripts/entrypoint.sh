#!/bin/sh
# Container entrypoint: run pending Alembic migrations then start the server.
# Using /bin/sh (not bash) for maximum portability in slim images.
set -e

echo "[entrypoint] Running Alembic migrations..."
/app/.venv/bin/alembic upgrade head

echo "[entrypoint] Migrations complete. Starting server..."
exec /app/.venv/bin/start
