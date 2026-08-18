# HANDOFF

**Last updated:** 2026-08-18 · **Commit:** `9e88039` · **Branch:** `main`, clean, pushed

This file is the volatile half of the project's memory: what is true *right now* and what to do
next. `CLAUDE.md` is the durable half — conventions, gotchas, and how the project works. When
those two disagree about status, **this file wins**.

---

## 1. Core goal

CareerHQ is an AI-powered career intelligence platform. A user imports a CV, tracks applications,
and an agent tailors the resume to a specific job description — **with the user's approval on
every change**.

Built solo as a course project on a four-to-six-week budget. That constraint is real and drives
the slice ordering (`docs/05_Implementation_Plan.md` §2). Two things are graded requirements and
are not optional: **deployment** (slice 002, done) and the **Reviewer / evaluation layer**
(slice 005, not started).

The seven non-negotiable principles are in `.specify/memory/constitution.md`. Violations of
II–IV are release blockers.

---

## 2. Current implementation status

| Slice | Tasks | State |
|---|---|---|
| 001 — Platform Foundation | 69 / 69 | **Complete.** Docker stack, Google sign-in, per-user isolation, health checks |
| 002 — Deployment | 52 / 52 | **Complete.** Live on Railway over HTTPS |
| 003 — Data Foundation | **97 / 109** | **US1 and US2 done and deployed. US3 blocked** |
| 004 — Match analysis | — | Design approved and committed. **No code written** |
| 005 — Reviewer / evaluation | — | Not started. Graded requirement |

**Verified on 2026-08-18, not copied forward:** `189 backend tests passed, 81% coverage`
(gate is 80%) and `64 component tests passed (6 files)`. 6 Playwright e2e specs exist and need
the stack running.

### Live system

**https://frontend-production-02ac.up.railway.app** — real Google sign-in works end to end.

Railway project `CareerHQ`, three services: `frontend` (Next.js, **the only public door**,
proxies `/api/*`), `backend` (FastAPI at `backend.railway.internal:8000`), `pgvector`
(PostgreSQL 18.4 + vector 0.8.6, no public TCP proxy).

Deployed database state, checked this session:

```
users | professional_profiles | applications
  1   |          1            |      0
```

The profile holds 3 roles, 10 bullets, 23 skills. **Zero applications — this is what blocks T089.**

Readiness reports `database ok, cache not_configured, object_storage ok, ai_provider ok`.
Redis is deliberately not deployed: nothing reads a cache yet, and a placeholder would make the
app believe it has one and fail at first use.

### What slice 003 actually built

**US1 — a CV becomes a reviewed profile.** Upload → review item by item → correct → approve.
Nothing reaches the profile without approval. A second import **merges** rather than appends,
and never overwrites a value the user corrected.

**US2 — a job becomes a record to tailor against.** Add from a posting URL, from pasted text, or
by hand; move it through statuses; open a record holding the description slice 004 works from.

**The artifact to understand first is the structured completion seam** —
`specs/003-data-foundation/contracts/extraction-seam.md`. One call in, one validated object out:
`complete(task, schema, prompt) -> Completion[T]`. A schema is required, so unvalidated text
cannot come back; the model is chosen **by task name**, which is what lets slice 004 express
docs/08 §3.2.3 as configuration rather than branches; usage is returned so the audit record
Principle V requires is written in the same transaction as the work.

There are two call sites — `extract_resume` and `extract_job`. Neither loops, uses tools, or
reacts to its own output, which is the line the scope guard actually protects.

---

## 3. Files modified

Slice 003 spans commits `3e526bb..9e88039` (24 commits). Regenerate this list any time with:

```bash
git diff --name-status 3e526bb~1..HEAD -- backend/src frontend/src
```

### Read these four first

| File | Why |
|---|---|
| `backend/src/careerhq/infrastructure/ai/litellm_gateway.py` | The completion seam. Everything AI goes through it |
| `backend/src/careerhq/infrastructure/jobs/fetch.py` | **The only place a user-supplied URL is requested** — the one SSRF surface |
| `backend/src/careerhq/infrastructure/jobs/parse.py` | Posting parsing, and where the failed strategies in §4 are encoded |
| `backend/src/careerhq/application/approve_import.py` | The approval boundary — the constitutional promise that nothing lands unapproved |

### Backend — added

```
api/routes/applications.py            api/routes/imports.py
application/approve_import.py         application/extract_job.py
application/extract_resume.py         application/ports.py
application/record_application.py
domain/models/{application,imports,profile,provenance}.py
domain/schemas/{extraction,job}.py
infrastructure/ai/{litellm_gateway,fixture_gateway}.py
infrastructure/documents/{pdf,docx}.py
infrastructure/jobs/{fetch,parse,comeet}.py
```

### Backend — modified / moved

```
M  api/deps.py  api/routes/health.py  api/routes/profile.py
M  config.py  infrastructure/storage.py  main.py
R  domain/models.py   -> domain/models/identity.py     (100% rename)
R  domain/schemas.py  -> domain/schemas/identity.py    (100% rename)
```

### Frontend — added

```
app/{import,profile,applications,applications/[id]}/page.tsx
components/applications/{applications-page,applications-view,add-application,
                         job-import,detail-tabs,status-pill,company-logo}.tsx
components/import-review/{import-flow,review,item-actions,item-editor}.tsx
components/profile/{edit-mode,entry,profile-menu,remove,row-editor,section}.tsx
components/{provenance,sidebar-nav,not-built-yet}.tsx
lib/{imports,session}.ts
components/__tests__/{applications,import-review,profile-menu,provenance}.test.tsx
lib/__tests__/imports.test.ts
```

### Frontend — modified

```
M  app/dashboard/page.tsx  app/layout.tsx
M  components/app-shell.tsx  components/__tests__/app-shell.test.tsx
M  lib/api.ts
```

### Design / spec artifacts

```
docs/superpowers/specs/2026-08-17-match-analysis-design.md   (approved, no code)
specs/003-data-foundation/{tasks.md,observations.md,contracts/extraction-seam.md}
specs/002-deployment/observations.md                          (deployment evidence, FR-015)
```

---

## 4. What failed

The expensive part of this project's memory. Each of these was tried and did **not** work —
re-attempting any of them costs real time.

### Reading job postings

- **Returning early on schema.org `JobPosting` metadata.** Looked free, was wrong twice. On a
  real posting that block held 1,591 characters of company blurb while the page held 9,447
  including the requirements — the early return skipped requirements narrowing entirely. Where
  the employer *did* state a field it still wins, but **the body always comes from the page**.
- **Asking the model to retype the description.** A real Greenhouse posting took **52 seconds**
  and timed out the frontend proxy. Metadata-only is 5.4s / 131 output tokens. Output is also
  57–86% of the cost, so this is the cost lever as well as the latency one. **Never ask the model
  to echo back text you already have.**
- **Reading a page that ships its own template.** Client-rendered boards serve
  `{{position.name}} @ {{company.name}}`, and the model dutifully "extracts" placeholders into an
  empty company and a requirements box full of `{{…}}`. Such a page must be **refused, not read**.
- **A generic fetch for Comeet.** It renders client-side, so it needed a vendor adapter
  (`infrastructure/jobs/comeet.py`). Its page ships the credentials its own browser code uses.
- **Assuming LinkedIn needs special handling — wrong, repeatedly.** A plain fetch returns 200 and
  ~10k characters of real content.

### Testing

- **Trusting the suite to catch display bugs. It never once did.** Contact fields, bullet
  attribution, skill categories and project URLs were each extracted correctly and then dropped by
  the renderer — all four found by a person looking at real data. A fixture only contains the
  fields whoever wrote it thought to include, so it *cannot* catch an omission.
  `tests/integration/test_profile_content.py` now reads the models' own columns and requires every
  stored value to reach the API; it found a fourth bug on its first run.
- **`create_all` against an existing test database.** It does **not** reconcile an existing table,
  so the test DB kept whatever shape it was first built with and every schema-shaped assertion
  checked a stale snapshot. T067 — a release blocker — passed against a deliberately added
  `rejected` column until `conftest.py` dropped before creating. **Any test that asserts an
  absence must be watched failing.**
- **Asserting an absence against the wrong scope.** "No rejected toggle on the form" passed
  against a form that had one, because Radix renders dialogs into a portal and `container` was
  empty. Same class of false gate, one layer up.
- **Running a test against the real profile.** It merged a fictional CV into it and replaced the
  contact block. **Always use a scratch user** — and seed it `@example.com`, because pydantic's
  `EmailStr` rejects `.test`/`.invalid` and the 500 reads as a white-screen app bug.

### Cost and models

- **Letting a task fall through to `llm_provider_model`.** The fallback is **Opus**, so a task
  with no `llm_model_<task>` entry silently runs at 2.5× the price for no gain. It already caught
  CV extraction once. **Set `llm_model_<task>` for every new task.**

### Deployment

- **`railway deployment redeploy` as a rollback.** It redeploys the *latest* deployment, so during
  an incident it restarts the broken version. Also: a rollback creates a **new** deployment id
  carrying the **old** commit, so read which version is live from the *commit*, never the id.
- **Reading Railway logs for a message string.** Railway **blanks the `message` field** of parsed
  JSON logs — structured fields survive, the human text does not, with or without `--json`, and
  the same code logs fine locally. Put anything needed to debug production in `extra={…}` fields.
  This is silent: the records look well-formed.
- **`nc -z` to test whether the database was exposed.** It reported the port open because
  Railway's proxy edge is shared and accepts connections regardless. Speaking the PostgreSQL
  protocol gave the real answer. For any "is X exposed" check, **speak X's protocol and include a
  control.**
- **Trusting a green health check to mean the proxy works.** The frontend's check probes `/`,
  which never traverses `/api/*`. **Three separate proxy misconfigurations all deployed green.**
- **Secret-scanning the logs for a low-entropy password.** Local `POSTGRES_PASSWORD` is
  `careerhq`, which collides with the project name in 2000 log lines. Use high-entropy values even
  in development or the scan means nothing.

### Product decisions that were tried the other way first

- **A `rejected` boolean beside the status.** JobTracker has one and reconciles the two at every
  read *because they disagree*. Here rejection is a value of `normalized_status`. **There is no
  `rejected` column and its absence is a release blocker**, asserted against `information_schema`
  both locally and on the deployed database.
- **One overwritten date field.** `date_added` and `date_applied` are separate, so "this sat in
  Pre-Applied for 46 days" stays computable.
- **Labelling `EXTRACTED` provenance.** Every fact carries it straight after an import, so the
  label said nothing. Only `CORRECTED` and `ADDED` are marked.
- **A second render path for grouped skills.** It cost an affordance every time — Edit, then Add,
  then Remove each went missing from it.

### Environment

The full list is in `CLAUDE.md` → *Gotchas already hit*, and it is worth reading before touching
Docker or Railway. The two that cost the most time:

- **`docker compose up -d backend` does not pick up backend code changes.** The backend mounts
  nothing and runs the baked image. Use `docker compose build backend && docker compose up -d
  backend`. The symptom is nasty: readiness passes, the API answers, only the *new* behaviour is
  missing.
- **`psql` in the deployed pgvector Console talks to a stranger's database.** The running
  container still carries a stale `PGHOST`/`PGPORT` from the deleted public proxy, and Railway
  recycles proxy ports. Always override both:
  `PGHOST=localhost PGPORT=5432 psql -U postgres -d railway -c '…'`

---

## 5. Exact next steps

Twelve tasks are open in slice 003. **Two of the three blockers are on the author, not on code.**

### A — T089 · blocked on the author · ~1 minute

Add **one real job** at https://frontend-production-02ac.up.railway.app. The task requires the
deployed system to hold *both* of slice 004's inputs; the profile half alone does not count.

Verify:

```bash
railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway \
  -c \"SELECT count(*) FROM applications;\""
```

Expect `1`. Then tick T089 in `specs/003-data-foundation/tasks.md`.

### B — User Story 3, T074–T084 · blocked on the author

Produce a JobTracker export (`GET /api/export`) and save it to
`backend/tests/fixtures/jobtracker_export.csv`. **The mapping is already written from the source**,
so this proves it against real data — and the messy cases are the entire point: blank dates,
`"competitive"` salaries, and custom statuses that live in browser storage and reach no export.

Once the file exists, the order is fixed and TDD applies (write the test, **watch it fail for the
right reason**, then implement):

1. **T075** — idempotency: `test_jobtracker_import.py`
2. **T076–T080** `[P]` — mapping unit tests: `rejected=true` keeps its label and normalizes to
   `rejected`; unrecognised status; date parsing; source attribution
3. **T081** — `backend/src/careerhq/application/import_jobtracker.py`
4. **T082** — endpoint in `api/routes/applications.py`
5. **T083** `[P]` — import screen and its report
6. **T084** 👁 — import the real export against the running stack and confirm counts

### C — Match analysis / slice 004 · **the only path that needs nothing from the author**

Design is approved and committed:
[`docs/superpowers/specs/2026-08-17-match-analysis-design.md`](docs/superpowers/specs/2026-08-17-match-analysis-design.md).
No code written. It was **paused** waiting for the author's scoring rubric, which was going to
arrive via GitHub — **checked 2026-08-18: no rubric file, no issues, no PRs, no branches. It has
not arrived.**

It does not have to block. Design §10 anticipates exactly this: *"Until then the rubric is the
model's own judgement... `criteria_version` exists so the first real rubric is distinguishable
from that."* The slots were built so a v0 ships uncalibrated and the real rubric lands later as a
new `criteria_version` **without rework** — a rubric slot in §3, and a vocabulary slot beside
requirement extraction for a skills taxonomy.

Design §9 says this folds into **slice 004's Spec-Kit specification**, not a fourth thing slice
003 quietly grows. So the next step is `speckit-specify` for slice 004, carrying in:

- the approved match-analysis design
- **docs/08 §3.2.3's model-per-node decision**, which must *flow in* rather than be re-derived:
  **Sonnet** to analyze, draft and revise; **Opus** for the Reviewer and for a revision that has
  already failed once. The Reviewer gets the stronger model because it enforces Principle III, a
  release blocker; escalating Revise on the second attempt stops the loop where an Opus reviewer
  rejects work a Sonnet reviser cannot fix. ≈ $0.17 per tailoring run against $0.24 all-Opus.

Three questions stay open and are recorded in design §10 — do not silently resolve them:
the scoring criteria themselves; whether a canonical skill vocabulary is needed for v0; and
**whether Haiku 4.5 suffices** — decide that with a measured comparison once real analyses exist,
not before, because the seam raises rather than accepting partial data.

### Also worth doing when convenient

- **Rotate the database password** and restart `pgvector`. It was on screen while the public TCP
  proxy was still open, and the stale `PGHOST` in the running container has since sent an
  authentication attempt to whichever tenant now owns the recycled port. `DATABASE_URL`
  references `${{pgvector.PGPASSWORD}}`, so rotation propagates — but run `ALTER USER … WITH
  PASSWORD` first; changing the variable alone does not change the password.
- **Rotate the logo.dev token** hardcoded in public source at `ApplicationTable.jsx:4` in
  `nirtituani/job-tracker-web`.
- **Run a full `/security-review` of the branch diff.** T068 was scoped to cookies, headers and
  secret handling only.

---

## 6. Process reminders

- **Spec-Driven Development** via GitHub Spec-Kit: `specify → plan → tasks → analyze → implement
  → verify`. **Do not skip `analyze`** — it has caught real gaps before code was written.
- **Tests first**, and the failure message matters. `ImportError` because the module does not
  exist yet is a valid red; a test that passes before implementation is a broken test.
- **Verify in Docker, not just in pytest.** Every user story ends with a task that runs the real
  stack, and that step has caught bugs the suite could not.
- **Update `tasks.md` as you go** — tick boxes, and amend a task's text when the implementation
  deviates. A task list that lies about what happened is worse than none.
- **Reading the source app is cheaper than guessing at it.** `nirtituani/job-tracker-web` is
  public and settled the status vocabulary, the Applied Via options, `match_rating * 20`, and the
  query that proved why the `rejected` flag had to go.
