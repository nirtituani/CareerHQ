# HANDOFF

**Last updated:** 2026-08-20 · **Commit:** `a7c50ff` · **Branch:** `004-match-analysis`

> **Nothing in slice 004 is pushed.** Remote `main` is still at `9e88039`, and the deployed
> database has **no `match_analyses` table**. Everything below is local.

This file is the volatile half of the project's memory: what is true *right now* and what to do
next. `CLAUDE.md` is the durable half — conventions, gotchas, and how the project works. When those
two disagree about status, **this file wins**.

---

## 1. Core goal

CareerHQ is an AI-powered career intelligence platform. A user imports a CV, tracks applications,
and an agent tailors the resume to a specific job description — **with the user's approval on
every change**.

Built solo as a course project on a four-to-six-week budget. That constraint drives the slice
ordering (`docs/05_Implementation_Plan.md` §2). Two things are graded requirements and are not
optional: **deployment** (slice 002, done) and the **Reviewer / evaluation layer** (slice 005, not
started).

The seven non-negotiable principles are in `.specify/memory/constitution.md`. Violations of II–IV
are release blockers.

---

## 2. Current implementation status

| Slice | Tasks | State |
|---|---|---|
| 001 — Platform Foundation | 69 / 69 | **Complete** |
| 002 — Deployment | 52 / 52 | **Complete.** Live on Railway |
| 003 — Data Foundation | 97 / 109 | US1 and US2 done. **US3 blocked on a JobTracker CSV** |
| **004 — Match Analysis** | **84 / 89** | **All three user stories complete. 5 open, all deployment** |
| 005 — Reviewer / evaluation | — | Not started. Graded requirement |
| next — Resume Tailoring Agent | — | Not started. Was slice 004; see docs/05 §5.4 |

**Measured 2026-08-20, not copied:** `285 backend tests passed, 81.02% coverage` (gate 80%),
`99 frontend tests passed (8 files)`, ruff format 86 files, ruff check clean, mypy clean across 49
source files, `next build` succeeds.

### Live system

**https://frontend-production-02ac.up.railway.app** — Google sign-in works end to end.

Deployed database, checked this session: **`users 1 | professional_profiles 1 | applications 0`**,
and `match_analyses` **does not exist** — slice 004 has never been deployed.

### What slice 004 built

Score a recorded job against the approved profile. **One structured call — the third `complete()`
call site.** No loop, no tools, no retrieval, no embeddings.

- **Five verdicts**: `confirmed`, `partial`, `transferable`, `gap`, `unverified`. Every one except
  `unverified` must quote the profile, **including `gap`**, which quotes the shortfall.
  `unverified` is the only evidence-free verdict because it is the only one asserting nothing.
- **`unverified` is weighed like a gap** — a recruiter reads the same profile the model does — but
  never *claimed* like one, and only it is recoverable by editing the profile.
- **Importance is judged per requirement**, 0–100, not read off the posting's heading. The band
  caps at 70. On the reference posting the model rated "excellent communication in English" **30**
  and "fast-paced startup environment" **15**, both listed under *Requirements*.
- **`criteria_version = v2-importance`**, stored on every analysis, as is the band — re-banding
  history would rewrite what a person was told.
- **The interface** shows a score ring, the four weighted dimensions it is the sum of, and the
  requirements split into what is missing (importance-ordered) and what fits (with evidence).

---

## 3. Files modified

Slice 004 spans `84de85e..a7c50ff`. Regenerate the list with:

```bash
git diff --name-status 84de85e~1..HEAD -- backend/src frontend/src
```

### Read these first

| File | Why |
|---|---|
| `backend/src/careerhq/application/analyze_match.py` | The use case, the prompt, and the abandoned-run rule |
| `backend/src/careerhq/application/match_criteria.py` | `v2-importance` — weights, bands, the cap, and `cap_bit` |
| `backend/src/careerhq/domain/schemas/match.py` | The grounding validator: which verdicts must quote the profile |
| `frontend/src/components/applications/match-tab.tsx` | Everything the person actually reads |

### Backend

```
NEW  application/analyze_match.py      application/match_criteria.py
NEW  domain/models/match.py            domain/schemas/match.py
MOD  api/routes/applications.py        application/extract_job.py
MOD  application/record_application.py config.py
MOD  domain/models/application.py      domain/schemas/job.py
MIG  0006_match_analysis · 0007_requirement_importance
     0008_unverified_no_shortfall · 0009_match_dimensions
```

### Frontend

```
NEW  components/applications/match-tab.tsx   components/applications/match-score.tsx
MOD  components/applications/detail-tabs.tsx components/applications/add-application.tsx
MOD  components/applications/applications-view.tsx  lib/api.ts
MOD  app/applications/[id]/page.tsx  app/globals.css
NEW  components/__tests__/match.test.tsx  components/__tests__/tokens.test.ts
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

### Match analysis (slice 004) — every one of these passed a green suite

- **`is` against an enum, on a value read from the database.** These are `String(16)` columns, so a
  row loaded in a **fresh** session comes back a plain `str`. `run_analysis` guarded with
  `status is not MatchStatus.PENDING`, so it returned immediately on every real call — nothing
  raised, nothing logged, and every analysis sat `pending` forever while 270 tests stayed green.
  The tests missed it because they pass the session that *created* the row, whose identity map
  still holds the enum member. Use `==`, and exercise such paths through a second session.
- **A lazy relationship on a freshly added object.** Serialising a just-created analysis read
  `.requirements`, which async SQLAlchemy cannot fetch outside an awaited context —
  `MissingGreenlet`, as a 500. The branch was never exercised because the existing test accepted
  `{202, 409}` and always got 409.
- **Demanding a `shortfall` on `unverified`.** A real completion failed validation on it, and the
  model was right: the profile says nothing, so choosing between *wording*, *evidence* and
  *capability* means guessing **why** it is silent. That is the invented absence the taxonomy
  exists to prevent, reappearing in the field added to make shortfalls actionable.
- **Reporting a cap that did not bite.** `capped_by` named a requirement whenever one *could* cap.
  At 54 the band is `stretch` by arithmetic anyway, so removing the requirement would not move it —
  saying it capped the score claimed a causation that did not happen.
- **`var(--fg)` where the token is `--foreground`.** An undefined custom property does not throw or
  warn. Three uses were `color:`, which inherits, so they looked right by accident; the fourth was
  `fill:` on SVG text and rendered **black on a dark ground**. `tokens.test.ts` now scans for it.
- **Building a CSS reveal the natural way round.** Reduced motion collapses animations to 0.01ms,
  so a base style of "empty ring" plus an animation that draws it in shows **zero** to everyone who
  reduces motion — invisible to anyone testing with motion on. Put the final value in the element's
  own style and let the keyframe supply only the start.
- **Trusting `drop_all` against an existing test database.** It emits statements from the
  *metadata*, not from the database, so the first `use_alter` foreign key broke it outright.
  `conftest.py` drops the schema now. A `use_alter` constraint must also be **named**, or it cannot
  be dropped at all.
- **Assuming a stuck run could be recovered.** R7 said "a re-run fixes it"; the in-flight guard
  answered 409, so the one action that recovers the job was the one action refused. Hit three
  times, each needing SQL by hand. A `pending` row older than an hour is now reaped.
- **Estimating output tokens.** R8 projected ~1,500 output for three verdicts and no `importance`
  or `shortfall`. Measured with five verdicts and both: **2,811**, so $0.0355 against SC-004's
  $0.03. The estimate's *share* was right (79%, inside the predicted 57–86%); its magnitude was not.

### Browser and tooling

- **Next.js dev mode 403s its own chunks when the browser is on `127.0.0.1`.** The page renders,
  nothing hydrates, no console error. Use `localhost` in a browser — the **opposite** of the
  Playwright rule, and both are real.


---

## 5. Exact next steps

**Five tasks remain in slice 004, and all five are deployment.** They are blocked on one decision
that is the author's.

### A — Deploy slice 004 · **blocked on the author's go-ahead**

Nothing is pushed. Remote `main` is at `9e88039`; the branch is `004-match-analysis` at `a7c50ff`.

```bash
git push -u origin 004-match-analysis     # then merge to main, which Railway deploys
```

Railway runs `alembic upgrade head` pre-deploy, so migrations 0006–0009 apply on the way in. **Set
`LLM_MODEL_MATCH_ANALYSIS=anthropic/claude-sonnet-5` on the backend service first** (T085) — the
fallback is Opus at 2.5× the cost, silently.

Then T086 and T087, which need **a real job on the deployed system** — the same thing slice 003's
T089 has been waiting for. One job, added at the deployed URL, closes both:

```bash
railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway \
  -c \"SELECT status, overall_score, band, model, is_fixture FROM match_analyses;\""
# and the grounding check, which must return 0:
#   SELECT count(*) FROM match_requirements WHERE (verdict='unverified') <> (evidence IS NULL);
```

### B — Slice 003 User Story 3 · **blocked on the author** · 11 tasks

A JobTracker export (`GET /api/export`) saved to `backend/tests/fixtures/jobtracker_export.csv`.
The mapping is written; this proves it against real data, and the messy cases are the point.

### C — Decide what to do about SC-004 · **the author's call**

Measured cost is **$0.0355 per job** against a $0.03 target — the criterion is marked *not met* in
`spec.md` rather than quietly adjusted. `research.md` R8 lists three ways out and explains what
each trades away. Doing nothing is a legitimate choice; leaving it unrecorded was not.

### D — The Reviewer / evaluation layer (slice 005) · unblocked, not started

A graded requirement. Nothing about it depends on A, B or C.

### Also worth doing when convenient

- **Rotate the database password** and restart `pgvector` — see CLAUDE.md.
- **Rotate the logo.dev token** hardcoded in public source at `ApplicationTable.jsx:4` in
  `nirtituani/job-tracker-web`.
- **Run `/security-review` on the branch diff.** T068 covered cookies, headers and secrets only,
  and slice 004 added a new user-facing surface.

---

## 6. Process reminders

- **Spec-Driven Development** via Spec-Kit: `specify → plan → tasks → analyze → implement →
  verify`. **Do not skip `analyze`.**
- **Tests first**, and the failure message matters. A test that passes before implementation is a
  broken test — and slice 004 is the case study: five defects shipped under a green suite, each
  found by running the thing rather than testing it.
- **Verify in Docker, and then in a browser.** Every display bug in this project was found by a
  person looking at real data.
- **Update `tasks.md` as you go**, and amend a task's text when the implementation deviates.
- **`/handoff` before `/clear`.** It does not run automatically.
