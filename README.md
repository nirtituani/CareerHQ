# CareerHQ

> Your AI-powered headquarters for every job application.

Import your CV once, track every application, and have an agent tailor your resume to a specific
job description — with your approval on every change, and never a claim your profile does not
support.

Built with FastAPI, Next.js, PostgreSQL with pgvector, and LangGraph.

---

## Status

**Live at https://frontend-production-02ac.up.railway.app**

**All ten slices (001–010) are complete, merged and deployed**; the system runs from `main`.

Working today:

- **Google sign-in** with per-user isolation, and health checks that name each dependency
- **Import a CV** — upload it, review what was extracted item by item, correct anything wrong, and
  approve it into your Professional Profile. Nothing reaches the profile without your approval
- **Record a job** — paste a posting URL and the company, title, location and requirements are
  read from it; or enter them by hand. Every status change is recorded, and the timeline is
  append-only
- **Import your history** — a JobTracker CSV export merges into your applications rather than
  appending, so re-importing the same file adds nothing
- **Match analysis** — every requirement scored against your profile with quoted evidence, and
  five verdicts rather than three so the model can say *"your profile does not mention this"*
  without inventing an absence
- **Resume tailoring** — a LangGraph workflow (Plan → Draft → Review → Revise) that rewrites your
  resume for one posting, critiques its own output, and stops at two revisions
- **Item-level approval** — every proposed change is accepted or rejected individually. A claim
  the Reviewer finds ungrounded is discarded before it can reach an approve button
- **Export and submit** — render to PDF, then lock. A submitted version is immutable, and
  submission re-reads and re-hashes the stored bytes rather than trusting the recorded checksum
- **Theme-faithful export** — an imported CV's visual design is extracted deterministically at
  import, persisted alongside the profile, and reproduced when a tailored resume is exported;
  bundled fonts keep the render reproducible, and regression tests protect the fidelity
- **Company research** — role-aware research for one application, driven by the job description
  rather than the CV. A research provider returns a cited brief whose sources are shown as
  provider-attributed; the retained built-in pipeline searches, fetches and synthesises here
  instead, and its stored excerpts are verified verbatim against the pages it retrieved itself
- **Career advisor** — agent-managed career memory over the whole application history:
  falsifiable claims with frozen evidence, denominators and lineage, which later runs confirm,
  supersede or retire; guidance is evidence-grounded, and a claim the grounding gate cannot
  verify is discarded before it is ever stored

Depth lives in [`docs/07_Capabilities.md`](docs/07_Capabilities.md) (what each capability does),
[`docs/08_Technical_Spec.md`](docs/08_Technical_Spec.md) (the whole system in one document) and
[`docs/05_Implementation_Plan.md`](docs/05_Implementation_Plan.md) (the slice roadmap).

---

## How it works

**One AI boundary.** Every model call goes through a single seam —
`complete(task, schema, prompt) -> Completion[T]`. A schema is required, so unvalidated text
cannot come back; the model is chosen **by task name**, so model-per-node is configuration rather
than branching; and token usage returns with the result, so the audit record is written in the
same transaction as the work. A test asserts that **no module under `application/` imports a
provider SDK**, which is what keeps the boundary real rather than aspirational.

**Where the agent is.** Resume tailoring is the agentic workflow: `Plan → Draft → Review → Revise`,
orchestrated by LangGraph, with one conditional edge and a hard bound of two revisions. The
Reviewer judges the *composed resulting resume* rather than the diff, because "which requirements
are still uncovered" is a question about the document. Draft and Revise return **only changed
items, by id** — output is the expensive half of a completion.

**Where RAG is.** Resume-writing guidance is retrieved per posting from a curated corpus
(18 documents, 79 chunks) embedded locally with `fastembed` and searched in PostgreSQL via `pgvector`.
Retrieval sits behind a port with no `top_k`, no scores and no embedding parameters, so swapping
the static rubric for retrieval changed no workflow node. Every retrieved rule is recorded with
its content hash, so a run can say what advice it was given.

**Where the tools are.** Company research reaches the web over **plain HTTPS, not MCP** — a
deliberate simplification argued in `tavily_search.py` — behind a `ResearchProvider` port with two
implementations. The **default** delegates search, source selection and synthesis to Tavily
Research, which returns a brief plus the sources it consulted; CareerHQ never fetches those pages,
so they are stored and shown as **provider-attributed** provenance. The **retained built-in
pipeline**, which serves as the configured fallback, works the older way: the search provider
returns URLs only, **CareerHQ fetches the pages itself**, and that is what makes verbatim citation
checking possible there. Job postings are read through a separate fetcher whose SSRF guard
resolves every hostname and refuses non-global addresses on each redirect hop.

**How grounding is enforced.** **Provider-attributed content is never presented as though
CareerHQ had verified it.** Where the built-in pipeline produced the research, every claim is
typed `fact`, `interpretation` or `inference`, each tier carries a different evidence obligation
enforced by the schema, and excerpts are checked **verbatim** against the retrieved page — a
deterministic string test, not a model call — with a claim whose excerpt fails *removed*, not
relabelled. Where a research provider produced it, there is no page for CareerHQ to check against,
so the interface shows a quoted excerpt only where one was actually verified and lists the
provider's sources as attribution instead; the tier vocabulary is not the organising surface
there. In tailoring, an `ungrounded` finding discards the proposal and restores the owner's
wording **before any row is written**, so a fabricated claim has no persisted representation.

**Memory.** The Professional Profile is the single source of truth and accumulates across the
lifecycle: imported facts, user corrections that later imports may not overwrite, application
history with separate `date_added`/`date_applied`, immutable resume versions, and research
snapshots that record what was known and when.

**How it was evaluated.** A 12-case synthetic benchmark spanning four disciplines drives the real
shipping path, scored on grounding, requirement coverage, retrieval quality, match calibration and
an LLM-as-judge. The benchmark set is **fully synthetic and committed**, so anyone can reproduce
it. Results — including criteria that were **missed** — are in
[`specs/007-evaluation-benchmark/results/`](specs/007-evaluation-benchmark/results/).

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

CI runs all of these except `npm run e2e` — Playwright exercises the full stack, so it is a
local per-slice verification step rather than a CI job. If the rest pass locally, they pass there.

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

Merge to `main`. That is the whole procedure — and it deploys **immediately**: Railway creates
deployments on both services within seconds of the merge, so the gates above have to pass
*before* the merge, not after it. Treat the merge as the gate.

Railway does offer a **Wait for CI** setting that can hold deployments until checks pass, but
the observed behaviour on this project is auto-deploy on merge, so do not rely on it. If enabling
it, know that it waits on every GitHub check suite reporting on the commit, not only this
repository's CI — a third-party check that never completes leaves a merge permanently undeployed
while Actions looks entirely green.

Database migrations and corpus ingestion both run as a pre-deploy step:

```toml
preDeployCommand = '/bin/sh -c "alembic upgrade head && python -m careerhq.ingest"'
```

If either fails, the deployment does not proceed and the previous version keeps serving.

**The `/bin/sh -c` wrapper is load-bearing**: Railway runs this field without a shell, so a bare
`&&` is not an ordering operator there — only the first command runs, and that once shipped an
empty corpus behind a deployment reporting SUCCESS. With the wrapper, the `&&` is the ordering:
`knowledge_chunks` has to exist before ingestion writes to it. **Pre-deploy, not startup**, so the model is loaded once per deploy rather than once
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

**`EMBEDDING_MODEL` is deliberately *not* in that list, and should stay out of it.** Leaving it
unset means the backend uses `config.py`'s default, `BAAI/bge-small-en-v1.5`, which is the model
`backend/Dockerfile` bakes into the image — so a cold container makes no network call, as spec.md
D3 requires. **Setting it to anything else is a silent way to break retrieval.** The corpus is
embedded with whichever model is configured and queries use the same one, so the two must agree;
the previous default (`sentence-transformers/all-MiniLM-L6-v2`) is *also* 384-dimension, which
means the vector column, `EMBEDDING_DIMENSIONS` and the adapter's width check all accept either.
Measured: re-embedding a stored chunk gives cosine 1.000 for the model that wrote it and **0.346**
for the other one.

Since T053 the corpus records which model embedded it, and `python -m careerhq.ingest` **refuses**
to run against a corpus built with a different model, naming both. That refusal exits non-zero and
so blocks the deploy, which is the intended behaviour: changing the embedding model is a
re-ingestion, not a variable edit. To change it deliberately, change `EMBEDDING_MODEL` *and* the
model baked in `backend/Dockerfile`, then drop the `knowledge_documents` / `knowledge_chunks` rows
so the pre-deploy ingestion rebuilds them.

Five things about that list are easy to get wrong:

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
