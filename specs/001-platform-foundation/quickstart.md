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

Run these **on the host**, not with `docker compose exec` — they are the same commands CI runs,
and two of them cannot work inside the containers at all (see the note below).

Backend, from `backend/` with the venv active (first time:
`python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"` — see the README):

```bash
.venv/bin/ruff format --check .    # formatting
.venv/bin/ruff check .             # lint
.venv/bin/mypy src                 # types (strict)
.venv/bin/pytest                   # tests, with the 80% coverage gate
```

Frontend, from `frontend/`:

```bash
npm run lint          # oxlint
npm run typecheck     # tsc --noEmit
npm test              # vitest
npm run build         # next build
npm run e2e           # playwright — needs the stack running
```

`pytest` needs the stack up: the database tests **skip** without PostgreSQL, and skipped tests
cover nothing, so the coverage gate fails. `pytest --no-cov` for a quick unit-only check.

> **Why not `docker compose exec`?** Found while running this quickstart from a clean clone
> (T069). `backend/.dockerignore` excludes `tests/`, so the runtime image has no test suite and
> `docker compose exec backend pytest` reports *no tests collected* — which reads like a passing
> run if you are not watching. And the frontend container is built `target: dev`, so its running
> dev server owns `/app/.next`; `docker compose exec frontend npm run build` races it and fails
> prerendering `/_global-error`, while the identical build succeeds on the host and in CI. Lint,
> type-checking, and `npm test` do work in the containers, but there is no reason to run half the
> gates one way and half the other.

Then confirm the pipeline actually fails on bad input: push a branch containing a deliberate
formatting error, an unannotated function, and a failing assertion. GitHub Actions must report
failure and name each problem. Fix and confirm green.

The concurrency test from SC-004 is part of the backend suite:

```bash
.venv/bin/pytest -k concurrent_first_signin -v
```

---

## Common issues

**A change to `.env` seems to have no effect** — use `docker compose up -d <service>`, not
`docker compose restart <service>`. Environment variables are injected when a container is
*created*; `restart` reuses the existing container and keeps the values it was born with, while
`up -d` notices the configuration changed and recreates it. Verify with:

```bash
docker compose exec backend printenv GOOGLE_CLIENT_ID
```

**A host port is already in use** — every published port is configurable in `.env`
(`FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `MINIO_PORT`,
`MINIO_CONSOLE_PORT`). Find what is holding the port with `docker ps`, then change the host side
only — containers still reach each other on the standard ports over the internal network.

**`redirect_uri_mismatch` from Google** — the URI in the Cloud Console must match
`http://localhost:3000/api/auth/google/callback` exactly, including scheme and port.

**A fresh clone still has the previous database** — `docker-compose.yml` pins `name: careerhq`,
so every checkout on the machine shares one Compose project and therefore one set of volumes.
Cloning into a new directory does *not* give you a clean database. For genuinely clean state run
`docker compose down -v` first, which deletes the volumes; the next `up` re-runs the migrations
and initialises MinIO from scratch.

**`extension "vector" is not available`** — the Postgres service must use the
`pgvector/pgvector:pg17` image, not stock `postgres`. If you changed it after the first run,
remove the volume (`docker compose down -v`) so the new image initializes cleanly.

**Frontend shows "service unavailable"** — expected briefly while the backend applies migrations
on first start; it should clear on its own within a few seconds (FR-019). If it persists, check
`docker compose logs backend`.
