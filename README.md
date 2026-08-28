# CareerHQ

> Your AI-powered headquarters for every job application.

Import your CV once, track every application, and have an agent tailor your resume to a specific
job description — with your approval on every change, and never a claim your profile does not
support.

Built with FastAPI, Next.js, PostgreSQL with pgvector, and LangGraph.

---

## Status

**Live at https://frontend-production-02ac.up.railway.app**

**Slice 001 — Platform Foundation**: complete. **Slice 002 — Deployment**: complete.
**Slice 003 — Data Foundation**: User Stories 1 and 2 complete; User Story 3 (JobTracker import)
is blocked on a real CSV export.

Working today, and deployed:

- **Google sign-in** with per-user isolation, and health checks that name each dependency
- **Import a CV** — upload it, review what was extracted item by item, correct anything wrong, and
  approve it into your Professional Profile. Nothing reaches the profile without your approval
- **Record a job** — paste a posting URL and the company, title, location and requirements are
  read from it; or enter them by hand. Every status change is recorded, and the timeline is
  append-only
- **See where everything stands** — a dashboard whose stat tiles filter the applications table,
  and a per-application record holding the job description the resume tailoring will work from

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

### To import a CV or read a job posting

Both need a model provider. Set **one** of these:

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Real extraction. Roughly 2–4¢ per CV or posting on Sonnet |
| `AI_PROVIDER=fixture` | Canned demo content, no key and no network |

**Fixture mode is never a fallback.** An absent key reports `ai_provider: not_configured` and
refuses, rather than quietly showing someone else's career history in a review screen they are
about to approve into their own profile. Everything it produces is labelled `is_fixture` for the
same reason.

`ai_provider: ok` only means a client could be *built* — it is deliberately not a live probe,
because this endpoint is the platform's healthcheck and probing would bill a completion on every
check. A key that is present and wrong still reports `ok`; the only proof is a real import.

**Uploads need object storage.** Compose starts MinIO and wires it up, so locally there is nothing
to do. Deployed, `S3_*` must point at a real bucket — without it an upload fails at the point of
use rather than at startup, which is deliberate: the stack must come up on a clean clone before
any storage account exists.

### Company logos (optional)

Set `LOGO_DEV_TOKEN` to a publishable token from [logo.dev](https://www.logo.dev) and the
applications table shows company logos. Leave it empty and it falls back to initials — nothing
else changes. It is publishable by design (it travels in the image URL), but it belongs in `.env`
rather than in the source, because this repository is public.

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

**That setting is not on by default** — enable it on *both* services under Settings → Deploy. And
it waits on every GitHub check suite reporting on the commit, not only this repository's CI, so a
third-party check that never completes leaves a merge permanently undeployed while Actions looks
entirely green.

Database migrations and corpus ingestion both run as a pre-deploy step:

```toml
preDeployCommand = "alembic upgrade head && python -m careerhq.ingest"
```

If either fails, the deployment does not proceed and the previous version keeps serving.

**The `&&` is the ordering, not a separator**: `knowledge_chunks` has to exist before ingestion
writes to it. **Pre-deploy, not startup**, so the model is loaded once per deploy rather than once
per replica — and so two replicas booting together cannot race the corpus's unique constraint.
Re-running an unchanged corpus creates nothing and embeds nothing, and the embedding weights are
baked into the image, so the step makes no network call.

Locally, the same command by hand:

```bash
docker compose exec backend python -m careerhq.ingest
```

Run it after editing anything under `backend/corpus/`. Without it the files and the database
disagree about what guidance exists, retrieval falls back to the static rubric, and every run
records that it did — which looks entirely healthy.

### Reading logs

Start with the **Deployments** tab in Railway. It needs nothing installed, and it shows which
commit is live, whether the last deployment succeeded, why it failed, and the pre-deploy step's
output — which is where a failed migration appears.

The CLI is quicker once set up, but it is a separate install and **not** a dependency of this
repository, so an operator reaching for it mid-incident starts here:

```bash
brew install railway                # not `npm i -g` — Homebrew's node_modules is root-owned
                                    # on this setup and the npm install fails with EACCES
railway login                       # opens a browser; may already be authenticated
railway link --project CareerHQ --environment production --service backend

railway logs --service backend      # one JSON object per line, each with a request id
railway logs --service backend --build       # build logs, a separate stream
railway deployment list             # which deployments exist, and which succeeded
```

Two things that will otherwise mislead you:

- **Alembic writes to stderr**, so Railway tags every migration line `"level":"error"`. A
  successful migration looks like a failure in any search filtered by level.
- **Only the current deployment's logs are retained.** Once a deployment is superseded it goes
  `REMOVED` and its logs go with it, so evidence about a past deploy has to be captured while it
  is still live.

Walking this section as written is what found that gap: `railway logs` used to be the first
instruction an operator met, and nothing above it said the command had to be installed first.

### Rolling back

Deployments tab → the last known-good deployment → **Redeploy**. This has been drilled against
the live site, and it is zero-downtime: the site served 200 throughout both the rollback and the
restore.

Two traps, both found by doing it:

- **`railway deployment redeploy` is not a rollback.** It redeploys the *latest* deployment, which
  during an incident means restarting the version that is broken. Rolling back is a different
  operation — the dashboard's Redeploy on an *older* deployment, or `deploymentRollback(id)`
  through `railway api`.
- **A rollback creates a new deployment id carrying the old commit**, and the previously live id
  flips to `REMOVED`. So read which version is live from the deployment's **commit**, never its
  id — the id you rolled back to is not the id you end up running.

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
PUBLIC_BASE_URL=https://frontend-production-02ac.up.railway.app
GOOGLE_CLIENT_ID=…
GOOGLE_CLIENT_SECRET=…
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=…
S3_ENDPOINT_URL=…          # Railway bucket, `railway bucket credentials`
S3_ACCESS_KEY=…
S3_SECRET_KEY=…
S3_BUCKET=careerhq-uploads
S3_REGION=…
```

On `frontend`:

```
BACKEND_URL=http://backend.railway.internal:8000
NEXT_PUBLIC_LOGO_DEV_TOKEN=…   # optional; logos fall back to initials without it
```

Four things about that list are easy to get wrong:

- **`REDIS_URL` is deliberately unset.** It is optional, and readiness reports it as
  `not_configured`. A placeholder would make the application believe it has a cache and fail at
  first use. `S3_*` *is* set, because uploads need it — without it a CV upload fails at the point
  of use rather than at startup.
- **`NEXT_PUBLIC_LOGO_DEV_TOKEN` is consumed when the frontend image is *built*.** Same trap as
  `BACKEND_URL` below: setting it on a running service is too late, the value is already baked in,
  and the failure is silent — the logos simply do not load.
- **`DATABASE_URL` must use `postgresql+psycopg://` and the `_PRIVATE` host.** A bare `postgres://`
  will not build the async engine, and the public host routes database traffic over the internet.
- **`BACKEND_URL` is consumed when the frontend image is *built*.** Changing it requires a
  rebuild, not a restart.

### The Google OAuth redirect URI

In the Google Cloud console, on the OAuth 2.0 client, **Authorized redirect URIs** must contain
exactly:

```
https://frontend-production-02ac.up.railway.app/api/auth/google/callback
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
