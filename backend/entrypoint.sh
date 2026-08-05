#!/usr/bin/env bash
#
# Bring the schema to head, then serve (FR-003).
#
# Migrations run here rather than in application startup so that the process
# either has a current schema or does not start at all — there is no window in
# which the API serves requests against a stale database.

set -euo pipefail

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API on :8000"
exec uvicorn careerhq.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --no-access-log \
  "$@"
