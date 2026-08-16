# CareerHQ

AI-powered career intelligence platform. Import a CV, track applications, and have an agent tailor
your resume to a job description — with your approval on every change.

Built solo as a course project on a four-to-six-week budget. That constraint is real and shapes
the plan: see `docs/05_Implementation_Plan.md` §2.

---

## Read these first

In this order. The whole project is legible from five files.

1. **`docs/07_Capabilities.md`** — what CareerHQ is and what each capability does. Start here;
   it is one page.
2. **`docs/08_Technical_Spec.md`** — the full technical spec in one document: problem, goals,
   architecture, test plan, rollout, rollback, cost, risk, open questions. Every capability
   carries a status marker, so it is also the fastest way to see what is actually built.
3. **`.specify/memory/constitution.md`** — the seven non-negotiable principles. Violations of
   II–IV are release blockers.
4. **`docs/05_Implementation_Plan.md`** — the slice roadmap and why it is ordered that way.
5. **`specs/00N-<slice>/tasks.md`** — the current slice's task list, with checkboxes showing
   exactly where work stopped. **Only slice 001 has these** — 002–007 are specified when they
   start.

Supporting detail lives in `docs/01` (requirements), `docs/02` (ADRs), `docs/03` (domain model),
`docs/04` (architecture), `docs/06` (stack). Original source material — the course requirements,
the author's design notes, the resume-builder reference — is in `docs/reference/`.

---

## Current state

**Slice 001 — Platform Foundation is complete.** All 69 tasks done, all three user stories
verified, and the quickstart run end to end from a fresh clone on wiped volumes — including a
real Google sign-in taking the database from `0|0` to `1|1`, and a second sign-in leaving it at
`1|1` while advancing only `last_login_at`.

Working: Docker Compose stack, Google sign-in end to end, per-user isolation, health checks
reporting each dependency by name, and CI green on every gate. 55 backend tests at 89% coverage,
3 component tests, 6 Playwright smoke tests. (58 backend tests as of slice 002.)

Merged to `main` and pushed; CI green on the merge commit. Working branch is now `main`.

**Slice 002 — Deployment is complete. All 52 tasks done.**

**CareerHQ is deployed at https://frontend-production-02ac.up.railway.app** — publicly
reachable over HTTPS, with a real Google sign-in working end to end and taking the deployed
database from `0|0` to `1|1`, staying `1|1` on a second sign-in.

User Stories 1 and 2 are verified against the running system. What that established is recorded
in `specs/002-deployment/observations.md`, which is the evidence FR-015 required — that file
matters more than usual, because it records where a first measurement was **wrong** as well as
where it passed.

### What is deployed

Railway project `CareerHQ`, three services:

| Service | Role | Public? |
|---|---|---|
| `frontend` | Next.js. Serves pages, proxies `/api/*` to the backend | **Yes** — the only public door |
| `backend` | FastAPI. Reached at `backend.railway.internal:8000` | No |
| `pgvector` | PostgreSQL 18.4 + `vector` 0.8.6. `pgvector.railway.internal` | No — TCP proxy deleted |

Deployment config is version-controlled: `backend/railway.toml` (pre-deploy `alembic upgrade
head`, healthcheck `/api/health/ready`) and `frontend/railway.toml`. Railway reads them from each
service's root directory — **not** from the repository root.

**The environment variables are documented in `README.md` → Deployment.** Three of them are easy
to get wrong and each failed at least once during slice 002:

- `DATABASE_URL` must use **`postgresql+psycopg://`** — a bare `postgres://` will not build the
  async engine — and **`PGHOST_PRIVATE`/`PGPORT_PRIVATE`**, not `PGHOST`, which is the public
  proxy. Compose it from `${{pgvector.*}}` references so a password rotation propagates by itself.
- **`PORT=8000` is set explicitly** on the backend. The entrypoint honours whatever a platform
  assigns, which is correct — but the frontend reaches the backend at a *fixed*
  `backend.railway.internal:8000`, so the assigned port has to be pinned or the two disagree.
- `BACKEND_URL` on the frontend is consumed at **build** time. Changing it needs a rebuild, not a
  restart.

**Only Postgres is deployed.** Redis and object storage are not; nothing needs them until slices
003/004. That is why `REDIS_URL` and the `S3_*` settings are now optional, and why readiness
reports them as `not_configured` rather than failing. Setting placeholder values would make the
application believe it has a cache and fail at first use.

### What the deployment gate and rollback drills established

All of it is in `specs/002-deployment/observations.md`, which is worth reading before touching
deployment again. The short version:

- **The gate was watched in both directions.** A good commit's deployment sat at `WAITING` until
  CI reported success, then went `SUCCESS`. A deliberately broken commit's deployment went
  `WAITING` → **`SKIPPED`** and stayed there, while the site kept serving the previous commit.
  Deployment status, not CI status, is the honest signal — `SKIPPED` is visible only from the
  deployment record, and Actions alone shows a red run without saying whether anything shipped.
- **Rollback is drilled and zero-downtime.** But `railway deployment redeploy` redeploys the
  *latest* deployment, so during an incident it restarts the broken version rather than rolling
  back. And a rollback creates a **new** deployment id carrying the **old** commit, so which
  version is live must be read from the commit, never the id.
- **Railway blanks the `message` field** of parsed JSON logs. Structured fields survive; the
  human-readable text does not, with or without `--json`, and the same code logs messages fine
  locally. Put anything you will need to debug a production problem in `extra={…}` fields, not in
  the message string — only the fields survive. This is silent: the records look well-formed.
- **Declining Google consent cannot be tested without revoking access first.** The OAuth request
  sends no `prompt=consent`, so an already-authorised account is signed straight in and there is
  no consent screen to decline. Revoke at `myaccount.google.com/connections`.
- **A low-entropy secret cannot be scanned for.** Local `POSTGRES_PASSWORD` is `careerhq`, which
  collides with the project name in 2000 log lines. Use high-entropy values even in development,
  or secret-scanning the logs is meaningless.

### Two things worth doing when convenient

- **Rotate the database password**, and restart `pgvector` while you are there. It was visible on
  screen during setup while the public TCP proxy was still open. That proxy is gone — `tcpProxies`
  returns `[]`, so the database is not reachable from the internet — but the stale `PGHOST` in the
  *running* container has since sent an authentication attempt to whichever tenant now owns the
  recycled proxy port (see the `psql` gotcha below). That moves this from hygiene to worth doing.
  Restarting the service recreates the container and clears the stale pointer, so the next person
  to open that Console does not repeat it. `DATABASE_URL` references `${{pgvector.PGPASSWORD}}`,
  so rotating propagates with nothing to hand-edit. Note that changing the variable alone does
  **not** change the password: run `ALTER USER … WITH PASSWORD` first.
- **The deployed domain says `frontend`, and three misspellings of it cost real time** (`fronted`,
  `frontned`). Copy it from Railway rather than typing it, and remember `PUBLIC_BASE_URL` must
  match the Google redirect URI byte for byte.

### Slice 003 — Data Foundation is in progress: 58 of 96 tasks

**User Story 1 is complete** apart from T058. A user uploads a CV, reviews what was extracted,
corrects it, and approves it into their Professional Profile. Verified repeatedly against a real
CV, and 126 backend tests at 81% plus 37 component tests.

**The structured completion seam is the artifact to understand first**
(`specs/003-data-foundation/contracts/extraction-seam.md`). One call in, one validated object out:
`complete(task, schema, prompt) -> Completion[T]`. A schema is required, so unvalidated text
cannot come back; the model is chosen by **task name**, which is what lets slice 004 express
docs/08 §3.2.3 as configuration rather than branches; and usage is returned so the audit record
Principle V requires is written in the same transaction as the work.

`infrastructure/ai/litellm_gateway.py` is the **only** module that may import `litellm`, asserted
by a test over the import graph. Two other boundary tests exist for the same reason —
`storage_key` is read by exactly one module, and `domain/` imports no framework or provider code.
All three were watched failing before being trusted.

Extraction runs on **Sonnet** at roughly $0.017–$0.038 per CV, defaulted in code rather than left
to the environment (an unset variable fell back to Opus at more than twice the price for
identical output). Measured on a real CV: 9 of 9 bullets attributed to the correct role.

**Decisions made during implementation that the spec does not carry:**

- **A second import merges, it does not append.** Keys are conservative — a role is company plus
  title plus start date — so a duplicate can be discarded by hand rather than an incorrect merge
  being undoable. Contact and summary are single-valued, but a value the **user corrected** is
  never replaced by a later import.
- **Approval has two modes**, chosen by what the user did. An untouched review adds everything not
  discarded; explicitly adding any item narrows it to those. A second import marks what the
  profile already holds, so only new items need attention.
- **The profile is editable and removable** — per item, per section, and entirely — behind an
  explicit edit mode rather than permanently visible controls. Correcting there marks the fact
  `user_corrected`, which then protects it from a later import.
- **`EXTRACTED` is not labelled.** Every fact carries it straight after an import, so the label
  said nothing; only `CORRECTED` and `ADDED` are marked, and the dashed rule carries the rest.

**What remains:** T058 (a scanned PDF observed failing in a browser), all of User Story 2
(recording a job, the applications table, the tabbed detail view) and User Story 3 (JobTracker
import — **blocked on a real CSV export**, T074).

### What working on this slice actually taught

Worth reading before writing more interface code, because it cost most of a day:

- **Every display bug was found by a person looking at a real CV, not by the suite.** Contact
  fields, bullet attribution, skill categories and project URLs were all extracted correctly and
  then dropped, summarised away, or detached from their context by the renderer. A fixture only
  contains the fields whoever wrote it thought to include — the same set the renderer was written
  against — so it cannot catch an omission. `tests/integration/test_profile_content.py` now reads
  the models' own columns and requires every stored value to reach the API; it found a fourth bug
  on its first run.
- **A second render path costs an affordance every time.** Grouping skills created one, and Edit,
  then Add, then Remove each went missing from it before the controls were extracted into a single
  component.
- **Test against a scratch user, never the real profile.** A test run against live data merged a
  fictional CV into it and replaced the contact block, because contact is single-valued by design.
  It was recoverable only because import records are kept.

### Slice 004 decision recorded ahead of its spec

`docs/08` §3.2.3 fixes the model per workflow node: **Sonnet** to analyze, draft and revise;
**Opus** for the Reviewer, and for a revision that has already failed once. The Reviewer gets the
stronger model because it enforces Principle III, which is a release blocker; escalating Revise on
the second attempt stops the loop where an Opus reviewer rejects work a Sonnet reviser cannot fix.
Roughly $0.17 per tailoring run against $0.24 all-Opus. When slice 004 is specified, that decision
must flow into it rather than being re-derived.

**Repo location**: `/Users/nirtituani/Developer/CareerHQ`. It was moved out of
`~/Documents/AI Workshop/` because iCloud syncs that folder and had generated 69 conflict copies
of source files — including `config 2.py` and `security 2.py`. `.gitignore` now excludes the
`* 2.*` pattern, but the real fix was leaving iCloud. Do not move it back.

### What the T068 security review established

These are conventions, not one-off fixes — new code is expected to follow them:

- **Configuration errors name the field, never the value.** `get_settings()` catches
  `ValidationError` and rebuilds the message, because pydantic puts rejected input in its own
  error text — a too-short `SESSION_SECRET` was being printed in full by the crash meant to
  protect it. Secret fields are detected from their `SecretStr` annotation, so a new secret is
  covered automatically.
- **Unauthenticated endpoints disclose the kind of failure, not the detail.** Readiness returns
  `OperationalError`; the driver's text — which names the internal IP, port, and database user —
  goes only to the log.
- **`SecurityHeadersMiddleware` sets `nosniff`, `DENY`, and `no-referrer` on every response**,
  including errors. HSTS is production-only; sending it from plain-HTTP localhost pins a scheme
  that does not work there, and browsers cache the pin.

A full `/security-review` of the branch diff has **not** been run — T068 was scoped to cookies,
headers, and secret handling.

---

## How we work

**Spec-Driven Development** using GitHub Spec-Kit. Every slice runs
`specify → plan → tasks → analyze → implement → verify`. Artifacts live in `specs/` and are
version-controlled. Do not skip `analyze` — it has caught real gaps before code was written.

**Tests first.** Write the test, run it, confirm it fails for the right reason, then implement.
The failure message matters: `ImportError` because the module does not exist yet is a valid red;
a test that passes before implementation is a broken test.

**Verify in Docker, not just in pytest.** Every user story ends with a task that runs the real
stack. That step has caught bugs the suite could not: a missing dependency that existed only in a
local venv, an empty `SESSION_SECRET` being accepted, and an OAuth redirect URI pointing at an
internal Docker hostname.

**Update `tasks.md` as you go.** Tick boxes when tasks complete, and amend a task's text when the
implementation deviates — a task list that lies about what happened is worse than none.

**Commit messages explain why.** The what is in the diff.

---

## Conventions

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 async, layered as
  `api/ → application/ → domain/`, with `infrastructure/` implementing what the inner layers
  declare. `domain/` imports no framework code — that is what keeps Principle V enforceable.
- **Frontend**: Next.js 16 App Router, TypeScript 7, Tailwind 4 (configured in CSS via `@theme`;
  there is no `tailwind.config.js`), shadcn/ui.
- **Frontend tooling**: **oxlint**, not ESLint — `typescript-eslint` refuses to run against
  TypeScript 7 and `eslint-config-next` imports it at load time, so the whole Next lint preset is
  unusable. Rules live in `.oxlintrc.json`; the rules of hooks are enforced. Type correctness is
  `npm run typecheck` (tsc), which was always more accurate than lint rules approximating it.
  Vitest config is `vitest.config.mts` (ESM); Playwright is separate and needs the stack running.
- **Business invariants belong in the schema.** A UNIQUE constraint cannot be raced or forgotten;
  an application-level check can be both.
- **Ownership comes from the session, never from the request.** No endpoint accepts a
  client-supplied user or profile id. A test enumerates every route and asserts non-public ones
  return 401.
- **Quality gates**: `ruff format`, `ruff check`, `mypy` strict, `pytest` at ≥80% coverage;
  frontend `lint`, `typecheck`, `test`, `build`. CI runs all of them with `if: !cancelled()` so a
  push surfaces every problem at once rather than one per round trip.
- **A gate nobody has watched fail is not a gate.** When adding one, prove it catches something —
  push a deliberate break, confirm the failure is named, then remove it. That is how the CI
  fail-fast problem above was found.

---

## Running it

```bash
cp .env.example .env          # fill SESSION_SECRET and the Google OAuth values
docker compose up -d
```

Then http://localhost:3000. API docs at http://localhost:3000/api/docs.

```bash
docker compose ps                     # what is running and healthy
docker compose logs -f backend        # follow one service
docker compose up -d backend          # apply a .env or compose change
docker compose build backend          # after changing dependencies or the Dockerfile
docker compose down                   # stop; data survives
docker compose down -v                # stop and delete the database
```

Backend checks (from `backend/`, with the venv active):

```bash
.venv/bin/pytest              # 42 of 55 run without Docker; 13 skip without PostgreSQL
.venv/bin/ruff check .
.venv/bin/mypy src
```

---

## Gotchas already hit

Recorded so they are not rediscovered.

- **`docker compose restart` does not pick up `.env` changes.** Environment variables are injected
  when a container is *created*. Use `up -d`, which recreates it. Verify with
  `docker compose exec backend printenv VAR`.
- **`ModuleNotFoundError: No module named 'careerhq'` from an apparently correct editable
  install** is macOS setting the BSD `hidden` flag on the `.pth` file. Python 3.12's `site` module
  deliberately skips hidden `.pth` files, so the install looks perfect — right path, right
  contents, readable — and Python ignores it. Diagnose with `ls -lO .venv/lib/*/site-packages/*.pth`
  (look for `hidden`), fix with `chflags nohidden` on those files. `pytest` no longer depends on
  this at all, because `pythonpath = ["src"]` is set in `pyproject.toml`; anything else invoking
  the venv's Python directly still can. Recreating the venv also clears it, which is why an earlier
  diagnosis blamed venv nesting — that was wrong.
- **Host ports are configurable** in `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, …). Change those
  rather than editing `docker-compose.yml` when a port collides.
- **`request.base_url` is the internal hostname behind the proxy.** The frontend proxies `/api/*`
  to `http://backend:8000`, so anything browser-facing — OAuth redirect URIs especially — must
  come from `PUBLIC_BASE_URL`, not from the request.
- **Verify package versions against the registry before pinning.** Nine versions across this
  project did not exist when first written down. Installing is faster than guessing.
- **`pytest` fails without PostgreSQL** — not because tests error, but because 13 of 55 skip and
  skipped tests cover nothing, so the coverage gate trips. `pytest --no-cov` for a quick
  unit-only check; `docker compose up -d` for the real run.
- **Playwright must target `127.0.0.1`, not `localhost`.** Node resolves `localhost` to `::1`
  first while Docker publishes IPv4 only, which surfaces as `ECONNREFUSED ::1:3000` against a
  stack that is demonstrably running.
- **A killed `next build` leaves workers behind** that make the next build take minutes and then
  fail on a vanishing temp file. `pkill -f "next-build|processChild"` and `rm -rf .next`.
- **`docker compose exec backend pytest` collects nothing.** `backend/.dockerignore` excludes
  `tests/`, so the runtime image has no suite — and pytest exiting on an empty collection looks
  much like a pass if you are skimming. Run the backend gates on the host, which is what CI does.
- **`docker compose exec frontend npm run build` fails** prerendering `/_global-error`, because
  the container is built `target: dev` and its running dev server owns `/app/.next`. The identical
  build succeeds on the host and in CI. Same rule: gates run on the host.
- **A hardcoded listening port is invisible locally and fatal when deployed.** `entrypoint.sh`
  used `--port 8000`; hosting platforms assign a port and inject it as `$PORT`, then probe *that*.
  Compose publishes 8000, so hardcoding it was accidentally correct. The symptom names nothing —
  a health check retrying for five minutes with **no application error**, because the application
  is healthy and merely unreachable. It now reads `${PORT:-8000}`.
- **The frontend's production image had never been built by anyone.** Compose builds
  `target: dev` and stops, so the `runner` stage was first exercised on the deployment platform —
  where it failed on `COPY /app/public`, a directory that did not exist. If you change anything in
  the production stages, build it: `docker build --target runner frontend/`.
- **`BACKEND_URL` is consumed at *build* time, not run time.** `next.config.ts` resolves the
  `/api/*` proxy destination into `routes-manifest.json` when the bundle is built. A Docker build
  is sealed off from the host environment, so the value only arrives through a declared `ARG` —
  and the ARG must be referenced *inside* the `RUN` line, or a build that changes only the
  variable reuses the cached layer and silently ships the previous destination. The symptom is a
  site that serves pages perfectly while every `/api/*` call 500s, which reads like a network
  fault. The build log now prints the value it baked in.
- **A passing health check is not evidence the proxy works.** The frontend's check probes `/`,
  which never traverses `/api/*`. Three separate proxy misconfigurations all deployed green.
- **Security headers must be sent by both halves of the origin.** `SecurityHeadersMiddleware` is
  backend-only, so HSTS, `nosniff`, `DENY` and `no-referrer` were on `/api/*` and absent from
  every page a browser actually navigates to. The middleware was correct throughout — it simply
  never sees those responses. `frontend/next.config.ts` now sets the same four, with the same
  values, and they must stay in step.
- **`nc -z` cannot tell "port open" from "service exposed".** Checking whether the database was
  publicly reachable, `nc` reported the port open because Railway's proxy edge is shared and
  accepts connections regardless. Speaking the PostgreSQL protocol gave the real answer
  (connection reset). For any "is X exposed" check, speak X's protocol and include a control.
- **Postgres 18 images mount at `/var/lib/postgresql`, not `/var/lib/postgresql/data`.** From
  18 onward the official images store data in a major-version subdirectory (`18/docker`) so
  `pg_upgrade --link` works without crossing a mount boundary. Mounting the pg17 path makes
  the container **exit 1 on startup** with a long explanation, and compose reports only
  `dependency failed to start` — the real message is in `docker compose logs postgres`.
  Changing the tag from `pg17` to `pg18` is therefore not a one-line edit; the volume mount
  has to move too.
- **Every checkout of this repo shares one set of Docker volumes.** `docker-compose.yml` pins
  `name: careerhq`, so cloning into a new directory does *not* give a clean database — it attaches
  to the existing one. `docker compose down -v` for genuinely empty state; it is scoped to this
  project and touches no other project's volumes.
- **`gh` is installed but may not be authenticated.** Check with `gh auth status` before
  reaching for it; an unauthenticated `gh` fails in ways that look like a missing repo. Log in
  with `gh auth login -s workflow` — requesting the `workflow` scope up front, because slice 002
  adds a deploy workflow and a push touching `.github/workflows/` is rejected outright without
  it. Git itself works independently, over HTTPS with `osxkeychain`. CI status can also be read
  from the public Actions API with `curl`, which needs no auth at all.
- **Pushing anything under `.github/workflows/` needs a token with the `workflow` scope.**
  Otherwise the push is rejected outright, with the commit still safe locally.
- **A comment beginning `# noqa` is parsed as a blanket lint suppression.** Do not start an
  explanatory comment with that word.
- **`testing files/` holds real CVs and is gitignored.** A CV carries a home address, a phone
  number and an employment history, and this repository is public. It sat untracked for a while
  with `git add -A` in regular use, which is one keystroke from publishing it permanently. The
  only documents ever committed are the three synthetic fixtures in `backend/tests/fixtures/`,
  whose subject is fictional precisely so they can be.
- **`docker compose up -d backend` does not pick up backend *code* changes.** The frontend mounts
  `./frontend/src:/app/src`, so its dev server hot-reloads; **the backend mounts nothing** and runs
  the baked image. `up -d` recreates the container from that same image, so it restarts happily
  with the old code. Use `docker compose build backend && docker compose up -d backend`.
  The symptom is nasty because everything looks healthy: readiness passes, the API answers, and
  only the *new* behaviour is missing — during slice 003 an extraction kept filing military service
  as employment after the schema had been fixed, and a page 500'd on a field the rebuilt code
  returns. Same family as the `.env` gotcha above: verify with
  `docker compose exec backend python -c "..."` rather than assuming.
- **`psql` in the deployed pgvector Console talks to a stranger's database.** The running
  container still carries `PGHOST=yamabiko.proxy.rlwy.net` and `PGPORT=58953` from before the
  public TCP proxy was deleted — environment variables are injected at container *creation*, so
  clearing the service variables (both are empty now) does not touch a container that is still
  running. It is the same rule as the `docker compose restart` gotcha above, one layer up. Railway
  recycles proxy ports, so that address now serves **another tenant's** database: it answers the
  PostgreSQL protocol and rejects your credentials, which reads as `FATAL: password
  authentication failed` and looks like a password problem when it is a wrong-server problem.
  Override both variables — one is not enough, and `su postgres -c` does not help because `su`
  without a dash preserves the environment:

  ```bash
  PGHOST=localhost PGPORT=5432 psql -U postgres -d railway \
    -c "SELECT (SELECT count(*) FROM users) || '|' || (SELECT count(*) FROM professional_profiles);"
  ```

  `PGPASSWORD` is already correct in that container; it only failed because it was being offered
  to the wrong server. **This sends an authentication attempt to a third party** — SCRAM-SHA-256
  means the plaintext never crosses the wire, but a hostile server can capture the client proof
  and attack it offline. See the password-rotation note above, which this makes concrete.
  The database itself is **not** exposed: `tcpProxies` on the service returns `[]`.

---

## Deliberate non-goals for now

Do not build these without discussion — each was scoped out for a stated reason, recorded in
`docs/05` §7:

- The from-scratch resume builder and the presentation designer (≈40 settings, demonstrates none
  of the project requirements; import reaches the same data far faster — ADR-013)
- Multi-provider LLM routing (LiteLLM makes it configuration)
- A full WYSIWYG resume editor

And two things that are **not** optional despite being unbuilt: the Reviewer/evaluation layer
(slice 005) and deployment (slice 002). Both are graded requirements.
