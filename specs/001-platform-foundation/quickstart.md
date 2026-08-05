# Quickstart: Platform Foundation

**Date**: 2026-08-05 | **Feature**: [spec.md](./spec.md)

How to run the slice and verify each user story actually works. This doubles as the acceptance
script — the slice is not done until every check below passes.

---

## Prerequisites

- Docker Desktop running
- A Google Cloud OAuth 2.0 Client ID (type: **Web application**) with authorized redirect URI:
  `http://localhost:3000/api/auth/google/callback`

Creating the OAuth client: Google Cloud Console → APIs & Services → Credentials → Create
Credentials → OAuth client ID. If the project has no consent screen yet, configure it as
**External** and add your own Google account as a test user — that is enough for local
development and avoids the app-verification process.

---

## Setup

```bash
cp .env.example .env
# Fill in GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and SESSION_SECRET.
# Generate a session secret:  python3 -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

First build pulls images and installs dependencies. Subsequent starts are fast.

---

## Verify User Story 1 — one command brings the platform up

```bash
# Liveness
curl -s localhost:3000/api/health
# → {"status":"ok","version":"0.1.0"}

# Readiness — every dependency named
curl -s localhost:3000/api/health/ready | python3 -m json.tool
# → database, cache, object_storage all "ok"

# Interactive API documentation
open http://localhost:3000/api/docs

# Schema is at head, applied automatically at startup
docker compose exec backend alembic current
```

**Fail-fast check** (FR-006): stop the stack, comment out `SESSION_SECRET` in `.env`, and run
`docker compose up backend`. The container must exit immediately with a message naming
`SESSION_SECRET` — not start and fail later on the first request. Restore the value afterwards.

**Dependency-outage check** (SC-008): with the stack up, run `docker compose stop redis`, then
`curl -s -o /dev/null -w '%{http_code}' localhost:3000/api/health/ready` → `503`, and the body
names `cache` as the failure. `docker compose start redis` to recover.

---

## Verify User Story 2 — sign in and reach the workspace

1. Open `http://localhost:3000/dashboard` while signed out → redirected to `/login`.
2. Click **Continue with Google** and complete the flow → land on `/dashboard`, with your name or
   email visible in the user menu and an empty-state message where data will appear.
3. Reload the page → still signed in (the cookie persists).
4. Confirm exactly one user and one profile exist:
   ```bash
   docker compose exec postgres psql -U careerhq -d careerhq \
     -c "SELECT (SELECT count(*) FROM users) AS users,
                (SELECT count(*) FROM professional_profiles) AS profiles;"
   ```
   → `1 | 1`
5. Sign out, then sign in again with the same account. Re-run the query — still `1 | 1`
   (FR-011: no second profile).
6. Sign out and visit `/dashboard` → redirected to `/login`.
7. Confirm the API rejects the unauthenticated call directly:
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' localhost:3000/api/profile   # → 401
   ```

**Cookie check** (FR-016): in DevTools → Application → Cookies, `careerhq_session` must show
`HttpOnly` ✓ and `SameSite=Lax`. Running `document.cookie` in the console must not reveal it.

---

## Verify User Story 3 — quality gates

Locally, the same commands CI runs:

```bash
docker compose exec backend ruff format --check .
docker compose exec backend ruff check .
docker compose exec backend mypy .
docker compose exec backend pytest --cov --cov-report=term-missing   # ≥80%
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
docker compose exec frontend npm test
```

Then confirm the pipeline actually fails on bad input: push a branch containing a deliberate
formatting error, an unannotated function, and a failing assertion. GitHub Actions must report
failure and name each problem. Fix and confirm green.

The concurrency test from SC-004 is part of the backend suite:

```bash
docker compose exec backend pytest -k concurrent_first_signin -v
```

---

## Common issues

**`redirect_uri_mismatch` from Google** — the URI in the Cloud Console must match
`http://localhost:3000/api/auth/google/callback` exactly, including scheme and port.

**`extension "vector" is not available`** — the Postgres service must use the
`pgvector/pgvector:pg17` image, not stock `postgres`. If you changed it after the first run,
remove the volume (`docker compose down -v`) so the new image initializes cleanly.

**Frontend shows "service unavailable"** — expected briefly while the backend applies migrations
on first start; it should clear on its own within a few seconds (FR-019). If it persists, check
`docker compose logs backend`.

**Port already in use** — 3000, 8000, 5432, 6379, or 9000 is taken. Stop the conflicting process
or override the host port in `docker-compose.yml`.
