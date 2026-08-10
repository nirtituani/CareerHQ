# CareerHQ

> Your AI-powered headquarters for every job application.

Import your CV once, track every application, and have an agent tailor your resume to a specific
job description — with your approval on every change, and never a claim your profile does not
support.

Built with FastAPI, Next.js, PostgreSQL with pgvector, and LangGraph.

---

## Status

**Slice 001 — Platform Foundation**, in progress. Working today: the containerized environment,
Google sign-in with per-user isolation, and health checks that report each dependency by name.

The agent capabilities are next. See [`docs/05_Implementation_Plan.md`](docs/05_Implementation_Plan.md)
for the roadmap and [`docs/07_Capabilities.md`](docs/07_Capabilities.md) for what each one does.

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
