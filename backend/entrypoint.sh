#!/usr/bin/env bash
#
# Bring the schema to head, then serve (FR-003).
#
# Migrations run here rather than in application startup so that the process
# either has a current schema or does not start at all — there is no window in
# which the API serves requests against a stale database.

set -euo pipefail

# Hosting platforms assign a port at run time and inject it as $PORT, then probe
# that port to decide whether the service came up. A hardcoded port means the
# health check knocks somewhere nothing is listening, and the symptom is a
# healthcheck that retries until it gives up — with no error from the
# application, because the application is fine and simply unreachable.
#
# Defaults to 8000 so local Compose, which publishes that port, is unaffected.
PORT="${PORT:-8000}"

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API on :${PORT}"
exec uvicorn careerhq.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --no-access-log \
  "$@"
