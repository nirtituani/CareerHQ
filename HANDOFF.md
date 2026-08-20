# HANDOFF

**Last updated:** 2026-08-20 · **Commit:** `5c8aeb2` · **Branch:** `main`, clean, pushed

> **Slice 004 is complete — 89 of 89 — and verified on the deployed system.**
>
> Four commits are **not yet live**: three Railway deploys have been stuck since 15:00 and a fourth
> is queued behind them. All four are presentation-only, so the deployed site scores identically to
> local (see §2).

This file is the volatile half of the project's memory: what is true *right now* and what to do
next. `CLAUDE.md` is the durable half — conventions, gotchas, and how the project works. When those
two disagree about status, **this file wins**.

---

## 1. Core goal

CareerHQ is an AI-powered career intelligence platform. A user imports a CV, tracks applications,
and an agent tailors the resume to a specific job description — **with the user's approval on
every change**.

Built solo as a course project on a four-to-six-week budget. Two things are graded requirements and
are not optional: **deployment** (slice 002, done) and the **Reviewer / evaluation layer**
(slice 005, **not started — the largest thing outstanding**).

The seven non-negotiable principles are in `.specify/memory/constitution.md`. Violations of II–IV
are release blockers.

---

## 2. Current implementation status

| Slice | Tasks | State |
|---|---|---|
| 001 — Platform Foundation | 69 / 69 | Complete |
| 002 — Deployment | 52 / 52 | Complete |
| 003 — Data Foundation | 98 / 109 | US1, US2 done. **US3 blocked on a JobTracker CSV** |
| **004 — Match Analysis** | **89 / 89** | **Complete and verified in production** |
| **005 — Reviewer / evaluation** | — | **Not started. Graded requirement** |
| next — Resume Tailoring Agent | — | Not started. The flagship |

**Measured 2026-08-20, not copied:** `287 backend tests passed, 81.06% coverage` (gate 80%),
`109 frontend tests passed (8 files)`, ruff format + check clean, mypy clean across 49 source
files, `next build` succeeds.

### Live system

**https://frontend-production-02ac.up.railway.app**

Deployed database, checked this session — **`users 1 | profiles 1 | applications 1 | analyses 1`,
grounding violations `0`**.

The deployed analysis reads `58 · stretch · v3-earned · claude-sonnet-5 · is_fixture=false ·
$0.039222`. That closed T086, T087 and slice 003's long-open T089 in one action.

**What is live is `cf27083`.** Four commits behind, all presentation:

| Commit | Change |
|---|---|
| `401e339` | Counts (`5/7`) instead of points in the breakdown |
| `e49a800` | The loading ring while an analysis runs |
| `648535d` | Tab order — Versions before Company |
| `5c8aeb2` | Documentation only |

**Nothing functional is missing** — v3 scoring, the cap, and the grounding rule all shipped in
`c942a38`, which is live. A deployed job scores exactly as it would locally.

The stall looks like Railway rather than this repository: CI is green on every commit, the stuck
frontend container **starts** (`Next.js ✓ Ready`), both services jammed at the same minute, and
Railway's SSH key-verification service was returning *"temporary service issue"* at the same time.
If it has not cleared, `railway redeploy --service frontend --from-source` pulls the newest commit
and makes the stale queue irrelevant.

### What slice 004 built

Score a recorded job against the approved profile. **One structured call — the third `complete()`
call site.** No loop, no tools, no retrieval, no embeddings.

- **Five verdicts** — `confirmed`, `partial`, `transferable`, `gap`, `unverified`. All but
  `unverified` must quote the profile, **including `gap`**, which quotes the shortfall.
- **`unverified` is weighed like a gap but never claimed like one.** A recruiter reads the same
  profile the model does; only `unverified` is recoverable by editing the profile.
- **Importance is judged per requirement**, 0–100; the band caps at 70.
- **The score is earned from the requirements** — `Σ(importance × credit) / Σ(importance)` — so
  the total explains the list rather than arguing with it. `criteria_version = v3-earned`.
- **The interface** shows a score ring, the requirement counts by verdict, and the requirements
  split into what is missing (importance-ordered) and what fits (with quoted evidence).

---

## 3. Files modified

Slice 004 spans `84de85e..5c8aeb2`. Regenerate with:

```bash
git diff --name-status 84de85e~1..HEAD -- backend/src frontend/src
```

### Read these first

| File | Why |
|---|---|
| `backend/src/careerhq/application/match_criteria.py` | `v3-earned` — the credit table, the cap, `score_from` |
| `backend/src/careerhq/application/analyze_match.py` | The use case, the prompt, the abandoned-run rule |
| `backend/src/careerhq/domain/schemas/match.py` | The grounding validator |
| `frontend/src/components/applications/match-tab.tsx` | Everything a person actually reads |

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
NEW  applications/match-tab.tsx  applications/match-score.tsx
MOD  applications/detail-tabs.tsx  applications/add-application.tsx
MOD  applications/applications-view.tsx  lib/api.ts
MOD  app/applications/[id]/page.tsx  app/globals.css
NEW  __tests__/match.test.tsx  __tests__/tokens.test.ts
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

### The score itself was wrong, and the arithmetic was why (v2 → v3)

The single most expensive mistake in this slice, and it survived a green suite, a code review of
my own design, and two rounds of interface polish.

- **A score computed independently of the thing it summarises will disagree with it.** v2 asked the
  model for four abstract dimensions and computed the score from those; the per-requirement
  verdicts fed nothing but the band cap. A real job returned **eight requirements addressed and a
  score of 48** while an independent assessment of the same CV and posting said 84. Re-aggregating
  **v2's own verdicts, unchanged**, gave 84 — nearly the entire gap was arithmetic.
- **Telling a model how to distribute its answers is not telling it to judge.** Prompt rule 4 said
  *"Most real profiles are mostly `partial`, `transferable` and `unverified`."* Added to stop a
  met/missing collapse — a real failure — it made the model push verdicts down to comply, and
  systematically under-scored anyone whose skills are real but whose domain differs. One bias
  over-corrected into its opposite.
- **A domain qualifier is not a capability gap.** "Build AI workflows *for system architecture*"
  asks for building AI workflows. Rewriting that rule took the same job from 2 `confirmed` to 5.

### Interface mistakes worth not repeating

- **A summary that flattens a distinction undoes every row that preserves it.** The coverage line
  counted `confirmed`, `partial` and `transferable` together — "8/8 requirements shown on your
  profile" for a profile with two direct matches. It read as a perfect match, contradicted the
  score, and was the exact error FR-011b forbids, in the line most likely to be read.
- **Showing your working is not the same as being useful.** The breakdown was built twice around
  the scoring arithmetic — raw importance sums, then points rescaled to 100 that summed exactly to
  the score. Both were correct. Both answered *how was this calculated*, which almost nobody asks.
  Counts — `5/7` — answer *how many of these do I meet*, which is the question people arrive with.
- **Two independent roundings will contradict each other.** Allocating "worth" and "earned" points
  separately printed "78 of 77". Harmless arithmetic that reads as a typo, and a person invited to
  check a total stops checking after the first thing that looks wrong. (Moot now — the arithmetic
  display is gone, and the class of bug went with it.)


---

## 5. Exact next steps

### A — Slice 005, the Reviewer / evaluation layer · **unblocked, and graded**

The largest thing outstanding and the last non-optional requirement. Nothing depends on anything
below. Start with `speckit-specify`; `docs/05_Implementation_Plan.md` §5.5 has the scope, and
slice 004's grounding work is the natural input — every verdict already carries evidence to check.

### B — Watch the deploy queue · **no action unless it is still stuck**

```bash
railway deployment list --service frontend
```

If the top entries still read `DEPLOYING`/`QUEUED`:
`railway redeploy --service frontend --from-source`. Nothing is degraded meanwhile.

### C — Slice 003 User Story 3 · **blocked on the author** · 11 tasks

A JobTracker export (`GET /api/export`) saved to `backend/tests/fixtures/jobtracker_export.csv`.
The mapping is written; this proves it against real data, and the messy cases are the point.

### D — Decide what to do about SC-004 · **the author's call**

Measured **$0.0355 and $0.0715** on two real jobs against a $0.03 target; `v3` brought a third to
$0.0396 by dropping the dimension ratings. Marked *not met* in `spec.md` rather than adjusted.
`research.md` R8 lists three ways out and what each trades away.

### E — The fit-versus-CV split · designed, deliberately not built

An independent assessment separated *fit* (89) from *fit as the CV shows it* (84). That is
derivable from data already collected — a `wording` shortfall is a presentation gap, a `capability`
one is real — and the difference is exactly what tailoring recovers. Held back because `wording`
has never been validated, and it is the natural opening for the tailoring slice.

### Also worth doing when convenient

- **Run `/security-review` on slice 004.** T068 covered cookies, headers and secrets only, and this
  slice added a new user-facing surface, a new endpoint group and four migrations.
- **Rotate the database password** and restart `pgvector` — see CLAUDE.md.
- **Rotate the logo.dev token** hardcoded in public source at `ApplicationTable.jsx:4` in
  `nirtituani/job-tracker-web`.

---

## 6. Process reminders

- **Spec-Driven Development** via Spec-Kit: `specify → plan → tasks → analyze → implement →
  verify`. **Do not skip `analyze`.**
- **Tests first**, and the failure message matters. Slice 004 is the case study: nine defects
  shipped under a green suite, and every one was found by running the thing rather than testing it.
- **Verify in Docker, then in a browser.** Every display bug in this project was found by a person
  looking at real data — including a score that was simply wrong for a month of arithmetic.
- **Update `tasks.md` as you go**, and amend a task's text when the implementation deviates.
- **`/handoff` before `/clear`.** It does not run automatically.
