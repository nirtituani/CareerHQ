# CareerHQ

> Your AI-powered headquarters for every job application.

Import your CV once, track every application, and have an agent tailor your resume to a specific
job description — with your approval on every change, and never a claim your profile does not
support.

Built with FastAPI, Next.js, PostgreSQL with pgvector, and LangGraph.

---

## Status

**Live at https://frontend-production-02ac.up.railway.app**

**Slice 001 — Platform Foundation**: complete. **Slice 002 — Deployment**: live, finishing.

Working today: the containerized environment, Google sign-in with per-user isolation, health
checks that report each dependency by name — and all of it running on a public HTTPS address,
redeployed from `main`.

The agent capabilities are next. See [`docs/05_Implementation_Plan.md`](docs/05_Implementation_Plan.md)
for the roadmap, [`docs/07_Capabilities.md`](docs/07_Capabilities.md) for what each one does, and
[`docs/08_Technical_Spec.md`](docs/08_Technical_Spec.md) for the whole system in one document.

---

## Quick start

**Prerequisites**: Docker Desktop, and a Google Cloud OAuth 2.0 client (Web application) with the
authorized redirect URI `http://localhost:3000/api/auth/google/callback`.

```bash
cp .env.example .env
```

Fill in three values:

| Variable | How to get it |
|---|---|
| `SESSION_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID` | Google Cloud Console → Credentials → OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Same screen |

Then:

```bash
docker compose up -d
```

Open **http://localhost:3000**. API documentation is at **http://localhost:3000/api/docs**.

> The health checks work without Google credentials — only sign-in needs them. If a port is taken,
> change it in `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, …) rather than editing `docker-compose.yml`.

---

## Running the checks

These are exactly what CI runs. If they pass locally, they pass there.

**Backend** (from `backend/`):

```bash
.venv/bin/ruff format --check .    # formatting
.venv/bin/ruff check .             # lint
.venv/bin/mypy src                 # types (strict)
.venv/bin/pytest                   # tests, with the 80% coverage gate
```

**Frontend** (from `frontend/`):

```bash
npm run lint          # oxlint
npm run typecheck     # tsc --noEmit
npm test              # vitest
npm run build         # next build
npm run e2e           # playwright — needs the stack running
```

Two things worth knowing. `pytest` enforces the coverage floor, and the database tests **skip**
when PostgreSQL is unreachable — skipped tests cover nothing, so the gate fails without the stack
running. Use `pytest --no-cov` for a quick unit-only check. And `npm run e2e` drives the real
stack rather than a mock, so `docker compose up -d` first.

First-time backend setup:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

> On macOS, if an apparently correct editable install still raises
> `ModuleNotFoundError: No module named 'careerhq'`, the `.pth` file has the BSD `hidden` flag and
> Python's `site` module skips it deliberately. Check with
> `ls -lO .venv/lib/*/site-packages/*.pth` and clear it with `chflags nohidden`. `pytest` is
> unaffected — `pyproject.toml` sets `pythonpath = ["src"]` — but anything else invoking the venv's
> Python directly is.

---

## Docker

```bash
docker compose ps                  # what is running, and whether it is healthy
docker compose logs -f backend     # follow one service
docker compose up -d backend       # apply a .env or compose change (not `restart`)
docker compose build backend       # after changing dependencies or the Dockerfile
docker compose down                # stop; your data survives
docker compose down -v             # stop and delete the database
```

Application source is mounted, so code edits need no rebuild. `restart` does **not** pick up
`.env` changes — environment variables are injected when a container is created, so use `up -d`.

---

## Deployment

Hosted on Railway, in the project `CareerHQ`. Three services: `frontend` (the only public one),
`backend`, and `pgvector`. The frontend proxies `/api/*` to the backend over Railway's private
network, so there is one public origin and no CORS surface.

Deployment settings live in `backend/railway.toml` and `frontend/railway.toml`, read from each
service's **root directory** — not from the repository root.

### Deploying

Merge to `main`. That is the whole procedure. CI runs the same gates listed above, and Railway's
**Wait for CI** setting holds the deployment until they pass — so a failing gate leaves the
public site untouched rather than rolling back after the fact.

Database migrations run as a pre-deploy step (`alembic upgrade head`). If a migration fails, the
deployment does not proceed and the previous version keeps serving.

### Reading logs

```bash
railway logs --service backend      # one JSON object per line, each with a request id
railway logs --service frontend
```

Or the **Deployments** tab in Railway, which also shows which commit is live and why a deployment
failed. A failed migration appears there, in the pre-deploy step's output.

### Rolling back

Deployments tab → the last known-good deployment → **Redeploy**.

**What that does and does not undo:**

| Layer | Rolls back? |
|---|---|
| Application code | ✅ Completely — containers are stateless |
| Database schema | ⚠️ Only if the migration was reversible. `alembic downgrade` restores structure, **not data** — a dropped column is not undone by re-adding an empty one |
| Business data | ❌ **Never**, by design |

The last row is Constitution Principle IV. Submitted resumes and status history are immutable: an
application whose history rewrote itself on deploy could not reproduce what was sent to an
employer, which is the guarantee the system exists to provide.

**So a migration that discards data needs a database snapshot taken immediately before deploy** —
its rollback path is restore-from-backup, not `downgrade`. Additive migrations, which is nearly
all of them, need nothing.

### Configuration

Set on the `backend` service:

```
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://${{pgvector.PGUSER}}:${{pgvector.PGPASSWORD}}@${{pgvector.PGHOST_PRIVATE}}:${{pgvector.PGPORT_PRIVATE}}/${{pgvector.PGDATABASE}}
PORT=8000
SESSION_SECRET=…
PUBLIC_BASE_URL=https://<frontend-domain>
GOOGLE_CLIENT_ID=…
GOOGLE_CLIENT_SECRET=…
```

On `frontend`:

```
BACKEND_URL=http://backend.railway.internal:8000
```

Three things about that list are easy to get wrong:

- **`REDIS_URL` and `S3_*` are deliberately unset.** They are optional, and readiness reports them
  as `not_configured`. A placeholder value would make the application believe it has a cache and
  fail at first use.
- **`DATABASE_URL` must use `postgresql+psycopg://` and the `_PRIVATE` host.** A bare `postgres://`
  will not build the async engine, and the public host routes database traffic over the internet.
- **`BACKEND_URL` is consumed when the frontend image is *built*.** Changing it requires a
  rebuild, not a restart.

### The Google OAuth redirect URI

In the Google Cloud console, on the OAuth 2.0 client, **Authorized redirect URIs** must contain
exactly:

```
https://<frontend-domain>/api/auth/google/callback
```

No trailing slash, and byte-identical to `PUBLIC_BASE_URL` plus that path. Google matches by
string, so a near miss fails at the provider with an error describing a mismatch rather than what
to fix. Keep the `http://localhost:3000/...` entry alongside it so local development still works.

**Copy the domain from Railway rather than typing it.** Three misspellings of it cost real time
during slice 002.

---

## Layout

```
backend/          FastAPI. api/ → application/ → domain/, with infrastructure/
                  implementing what the inner layers declare.
frontend/         Next.js App Router. Proxies /api/* to the backend, so every
                  request is same-origin.
docs/             Design documents. Start with 07_Capabilities.md.
docs/reference/   Original source material the design was derived from.
specs/            Per-slice specification, plan, and task list.
.specify/         Spec-Kit configuration and the project constitution.
```

---

## How this is built

Spec-Driven Development: every slice runs `specify → plan → tasks → analyze → implement → verify`,
and the artifacts are version-controlled alongside the code. A slice is not finished when its tests
pass — it is finished when it has been demonstrated against the running stack.

The rules the codebase will not bend on are in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md). The short version: the
professional profile is the single source of truth, AI proposes and the user decides, submitted
resumes are immutable, every recommendation is explainable, and business domains never call a
model provider.

[`CLAUDE.md`](CLAUDE.md) carries the working conventions and the gotchas already paid for.
