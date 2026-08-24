# HANDOFF

**Last updated:** 2026-08-24 · **Commit:** `23aec8f` · **Branch:** `005-resume-tailoring`, clean, pushed

> **Slice 005 — Resume Tailoring is 53 of 97.** The agent loop works end to end and every US1 test
> is written and green. **Nothing is reachable through a browser yet** — the six API routes and the
> whole frontend are still ahead.
>
> **CI is green on `23aec8f`**, both jobs, every step
> ([run 32708256515](https://github.com/nirtituani/CareerHQ/actions/runs/32708256515)).
>
> **Seven commits sit unpushed on local `main`** — all the slice-005 planning artifacts. They are
> *contained in the pushed branch*, so nothing is at risk, but `origin/main` is still at `02f1d4d`.
> See §5F.

This file is the volatile half of the project's memory: what is true *right now* and what to do
next. `CLAUDE.md` is the durable half — conventions, gotchas, and how the project works. When those
two disagree about status, **this file wins**.

---

## 1. Core goal

CareerHQ is an AI-powered career intelligence platform. A user imports a CV, tracks applications,
and an agent tailors the resume to a specific job description — **with the user's approval on
every change**.

Built solo as a course project on a four-to-six-week budget. Two things are graded requirements and
are not optional: **deployment** (slice 002, done) and the **evaluation harness** (now slice 007,
not started).

The seven non-negotiable principles are in `.specify/memory/constitution.md`. Violations of II–IV
are release blockers.

### The roadmap was renumbered on 2026-08-22

Build order now matches slice numbers. This was cheap because 005–007 had no artifacts — `specs/`
held 001–004 only, so it was an edit to three documents rather than churn across directories.

| | Slice | State |
|---|---|---|
| 005 | **Resume Tailoring** | **In progress, 53/97** |
| 006 | Document & Retrieval — RAG over guidelines, PDF export, submit-and-lock | Not started |
| 007 | Evaluation & Benchmark | Not started. **Graded** |
| 008 | Company Research | Droppable (`docs/08` §11) |
| 009 | Career Advisor | Droppable |

**Evaluation has now been deferred twice and two slices stand in front of it.** If the budget runs
short, 008 and 009 are what get dropped. This is recorded in `docs/05` §5.7 in those words.

---

## 2. Current implementation status

**Measured 2026-08-24, not copied:**

| Gate | Result |
|---|---|
| Backend suite | **361 passed**, 83.88% coverage (gate 80%) |
| Frontend suite | **109 passed** (8 files) |
| ruff format / check | clean, 113 files |
| mypy strict | clean, 59 source files |
| CI on `23aec8f` | **green** — Backend and Frontend, every step |

| Slice | Tasks | State |
|---|---|---|
| 001 — Platform Foundation | 69 / 69 | Complete |
| 002 — Deployment | 52 / 52 | Complete |
| 003 — Data Foundation | 98 / 109 | US1, US2 done. **US3 blocked on a JobTracker CSV** |
| 004 — Match Analysis | 89 / 89 | Complete, verified in production |
| **005 — Resume Tailoring** | **53 / 97** | **In progress. See §5A** |

### Live system

**https://frontend-production-02ac.up.railway.app** — `/` answers 307, readiness reads
`database ok · cache not_configured · object_storage ok · ai_provider ok`.

Deployed database, checked this session: **`users 1 | profiles 1 | applications 1 | analyses 1`**.

**The Railway deploy queue that was jammed on 2026-08-20 has cleared on its own.** The top
deployment reads `SUCCESS` and the service is `Online`, so the CV viewer (`44d6dbc`) is live.
One deployment in that backlog went `SKIPPED` — expected, and the honest signal the gate is
designed to produce. **No action needed; the previous handoff's plan B is closed.**

Nothing from slice 005 is deployed. It lives on a branch.

### What slice 005 has built

**The agent runs.** Four nodes — plan, draft, review, revise — orchestrated by LangGraph, each
calling the existing `complete()` seam. Bounded at two revisions, escalating from Sonnet to Opus on
the second by **task name**, which is what keeps `docs/08` §3.2.3 as configuration rather than a
branch in workflow code.

**LangGraph orchestrates and owns nothing.** Persistence, business state, audit, ownership and
finalisation all stay in `tailor_resume.py`. The test of that boundary: deleting every LangGraph
import and rewriting the graph as a loop would require no schema change and no change to any use
case.

**The severity split runs in the use case, before any row is written.** An `ungrounded` finding
discards its proposal and restores the owner's wording, so a fabricated claim has no persisted
representation and can never reach an approve button. `overstated` and `uncovered` persist and are
shown — Principle III enforced by the system, Principle II governing everything else.

**Four tables**: `resume_versions`, `tailoring_runs`, `resume_version_items`, `reviewer_findings`.
Two migrations, driven down and back up against a real database (4 tables → 0 → 4).

**The lifecycle gained a state.** `docs/03` §10.1's `Reviewing` meant both *the agent is working*
and *it is your turn*. `Awaiting approval` is the missing half. **`docs/03` has not been amended
yet — that is T080.**

### What is NOT built

- **No API routes.** `api/routes/tailoring.py` does not exist. Six endpoints are specified in
  `contracts/http-api.md` and none are written.
- **No frontend.** Not one file under `frontend/src` has changed this slice.
- **No real provider call has ever been made.** Every test runs against a scripted double. SC-006
  ($0.30) and SC-001 (90s / 3min) are **unmeasured targets**.

---

## 3. Files modified

Slice 005 spans `f414caf..23aec8f`. Regenerate with:

```bash
git diff --name-status f414caf~1..HEAD -- backend/src frontend/src
```

### Read these first

| File | Why |
|---|---|
| `specs/005-resume-tailoring/contracts/tailoring-workflow.md` | O1–O8. The LangGraph/CareerHQ boundary, and the test of it |
| `backend/src/careerhq/application/tailor_resume.py` | The use case: preconditions, execution, finalisation, persistence, the reaper |
| `backend/src/careerhq/application/finalisation_rules.py` | The severity split, versioned. Where Principles II and III are reconciled |
| `backend/src/careerhq/application/agents/tailoring/graph.py` | Four nodes, one conditional edge, the whole self-critique loop |
| `specs/005-resume-tailoring/contracts/http-api.md` | **The six routes to build next.** Written, not implemented |

### Backend source

```
NEW  application/tailor_resume.py          application/finalisation_rules.py
NEW  application/guidelines.py             (GuidelineSource port + static rubric)
NEW  application/agents/tailoring/{graph,state,prompts,__init__}.py
NEW  domain/models/tailoring.py            domain/schemas/tailoring.py
MOD  config.py                             (five llm_model_tailor_* entries)
MOD  domain/models/__init__.py             (exports)
MIG  0010_resume_versions · 0011_version_items_and_findings
```

### Tests

```
NEW  tests/support/{scripted_seam,tailoring_fixtures,__init__}.py
NEW  tests/integration/test_tailoring_workflow.py       (11)
NEW  tests/integration/test_tailoring_preconditions.py  (7)
NEW  tests/integration/test_tailoring_reaper.py         (6)
NEW  tests/integration/test_version_status_transitions.py (5)
NEW  tests/integration/test_tailoring_concurrency.py    (4)
NEW  tests/integration/test_tailoring_schema.py         (4)
NEW  tests/integration/test_owner_data_untouched.py     (3)
NEW  tests/integration/test_version_immutability.py     (3)
NEW  tests/unit/{test_finalisation_rules,test_scripted_seam,test_tailoring_schema_validation,test_task_model_config}.py
MOD  tests/unit/test_architecture.py       (widened provider guard)
```

### Frontend

**None.** Nothing under `frontend/src` has been touched this slice.

---

## 4. What failed

The expensive part of this project's memory. **Append-only — never delete an entry.** Each of these
was tried and did **not** work; re-attempting any of them costs real time.

### Slice 005 — the agent runtime

- **Assuming a LangGraph state key accumulates.** It does not. A key with no reducer is
  **overwritten**, measured against the installed 1.2.11: three nodes each returning one element
  left `['c']`. Applied to `usage` that keeps **one** record out of seven — an incomplete audit
  under Principle V, a cost figure wrong by up to 7×, and *nothing raises*. It reads as a cheap run.
  `Annotated[list, operator.add]` is required.
- **Believing the import guard covered the application layer.** It forbade exactly one package,
  `litellm`. Adding LangGraph made that actively worse rather than merely incomplete:
  `langchain-core` arrives transitively, so `langchain_anthropic` became one install away, and the
  idiomatic LangGraph example binds a model *inside the node*. The dependency creates the hole, so
  the guard cannot land after it.
- **Believing anything asserted "no call site loops".** Nothing executable ever did. That boundary
  is prose in `ports.py`'s docstring, and `CLAUDE.md` overstates it as an enforced guard (T082).
- **Thinking the checkpointer could be avoided.** `langgraph-checkpoint` is a hard transitive
  dependency carrying the in-memory saver. What is actually declined is
  `langgraph-checkpoint-postgres`, a **separate** package. "We don't depend on the checkpointer" is
  falsifiable by reading the lockfile.
- **`dataclasses.replace()` on a Pydantic model.** `DraftedItem` is a `BaseModel`; it needs
  `model_copy(update=...)`.
- **A table-driven loop over `(model, kind, accessor)` tuples** in `_render_master`. Three lines
  shorter and completely untypeable, which meant the one place a column name could be wrong had no
  checking at all. Written out explicitly.
- **`TailoringRun.__new__()` to build an unsaved instance.** Bypasses SQLAlchemy's instrumentation,
  and the first `setattr` fails with `'NoneType' object has no attribute 'set'` — an error that
  says nothing about what is wrong. Use the real constructor.
- **A module-level `pytest.mark.asyncio`** in a file that is half pure functions. It fails the sync
  tests outright.
- **`session.expire_all()` before re-reading.** The next attribute access does IO synchronously,
  which async SQLAlchemy answers with `MissingGreenlet`. Use an awaited `session.refresh(obj)`.
- **`json.load` in strict mode against the GitHub Actions API.** Control characters in commit
  messages break it. `strict=False`.

### Slice 005 — assumptions about existing code that were wrong

- **`MatchAnalysis` has a `profile_id`.** It does not; only `application_id`.
- **`Application.current_analysis_id`.** It is `current_match_analysis_id`.
- **`MatchRequirement.text`.** The column is `text`, the Python attribute is **`text_`** — it
  collides with SQLAlchemy's `text()`.
- **A new `ItemDecision` enum.** `provenance.ItemDecision` already exists for the import reviewer.
  The tailoring one is `ProposalDecision`, and the vocabularies differ for a real reason: import
  review *discards* (the item never enters the profile), tailoring *rejects* (the owner's wording
  stands).

### Slice 004 — match analysis (every one passed a green suite)

- **`is` against an enum on a value read from the database.** Status columns are `String(16)`, so a
  row loaded in a **fresh** session returns a plain `str`. `run_analysis` guarded with
  `status is not MatchStatus.PENDING` and returned immediately on every real call — nothing raised,
  nothing logged, every analysis sat `pending` forever while 270 tests stayed green. Tests missed it
  because they passed the session that *created* the row. Use `==`, and exercise the path against a
  re-read record. **Now asserted in both directions** by
  `test_version_status_transitions.py::test_status_read_from_a_fresh_session_compares_equal`.
- **A lazy relationship on a freshly added object** raises `MissingGreenlet` as a 500 when
  serialised. Assign collections at construction. **This bit again this slice**, in tests reading
  `.items`; the routes will need `selectinload`.
- **Demanding a `shortfall` on `unverified`.** A real completion failed validation and the model was
  right: the profile's silence gives no basis for choosing one. The same trap was avoided in advance
  here — an `uncovered` finding carries no item reference.
- **Reporting a cap that did not bite.** `capped_by` named a requirement whenever one *could* cap,
  claiming a causation that did not happen.
- **`var(--fg)` where the token is `--foreground`.** An undefined custom property fails silently and
  differently per property; three uses were `color:` and looked right by accident, the fourth was
  `fill:` and rendered black on a dark ground.
- **Building a CSS reveal the natural way round.** Reduced motion collapses animations to 0.01ms, so
  a base of "empty" plus an animation that fills it shows **zero** to everyone who reduces motion.
- **Trusting `drop_all` against an existing test database.** It emits from the *metadata*, not the
  database. `conftest.py` drops the schema. A `use_alter` constraint must also be **named**.
- **Assuming a stuck run could be recovered.** The in-flight guard answered 409 to the one action
  that recovers it. Hit three times, each needing SQL by hand.
- **Estimating output tokens.** R8 projected ~1,500 and measured **2,811** — 87% low, in the
  direction that costs money.
- **A score computed independently of the thing it summarises.** v2 asked for four abstract
  dimensions and computed the score from those; a real job returned eight requirements addressed and
  a score of 48 against an honest 84. Re-aggregating v2's *own verdicts* gave 84.
- **Telling a model how to distribute its answers.** *"Most real profiles are mostly `partial`,
  `transferable` and `unverified`"* made the model push verdicts down to comply.

### Testing (all slices)

- **Trusting the suite to catch display bugs. It never once did.** Contact fields, bullet
  attribution, skill categories and project URLs were each extracted correctly and dropped by the
  renderer — all four found by a person looking at real data.
- **`create_all` against an existing test database.** It does not reconcile an existing table, so
  every schema-shaped assertion checked a stale snapshot. T067 passed against a deliberately added
  column until `conftest.py` dropped first. **Any test that asserts an absence must be watched
  failing.**
- **Asserting an absence against the wrong scope.** "No rejected toggle on the form" passed against
  a form that had one, because Radix renders dialogs into a portal and `container` was empty.
- **A test double that repeats its last answer.** Would make an unbounded loop look convergent.
  `ScriptedSeam` raises instead.
- **A guard with nothing to examine.** `test_task_model_config.py`'s first AST walk looked for
  `task="literal"` and found **zero** call sites — every one passes `task=TASK` through a module
  constant. Without its own `assert used`, it would have passed forever while checking nothing.
- **Running a test against the real profile.** It merged a fictional CV into it and replaced the
  contact block. **Always use a scratch user**, seeded `@example.com` — pydantic's `EmailStr`
  rejects `.test`/`.invalid` and the 500 reads as a white-screen app bug.

### Deployment

- **`railway deployment redeploy` as a rollback.** It redeploys the *latest* deployment. A rollback
  also creates a **new** id carrying the **old** commit, so read which version is live from the
  commit.
- **Reading Railway logs for a message string.** Railway **blanks the `message` field** of parsed
  JSON logs. Put anything needed to debug production in `extra={…}` fields.
- **`nc -z` to test whether the database was exposed.** The shared proxy edge accepts connections
  regardless. Speak the protocol and include a control.
- **Trusting a green health check to mean the proxy works.** The frontend's check probes `/`, which
  never traverses `/api/*`. **Three separate proxy misconfigurations all deployed green.**
- **Secret-scanning logs for a low-entropy password.** `careerhq` collides with the project name in
  2000 log lines.

### Reading job postings

- **Returning early on schema.org `JobPosting` metadata.** Wrong twice: 1,591 characters of company
  blurb against 9,447 on the page including the requirements.
- **Asking the model to retype the description.** 52 seconds and a proxy timeout, against 5.4s for
  metadata only. **Never ask a model to echo back text you already have.**
- **Reading a page that ships its own template.** Client-rendered boards serve `{{position.name}}`,
  and the model "extracts" the placeholders. Refuse, do not read.
- **A generic fetch for Comeet.** Needed a vendor adapter.
- **Assuming LinkedIn needs special handling — wrong, repeatedly.** A plain fetch returns 200 and
  ~10k characters.

### Product decisions tried the other way first

- **A `rejected` boolean beside the status.** There is no `rejected` column and its absence is a
  release blocker.
- **One overwritten date field.** `date_added` and `date_applied` are separate.
- **Labelling `EXTRACTED` provenance.** Every fact carries it, so the label said nothing.
- **A second render path for grouped skills.** It cost an affordance every time — Edit, then Add,
  then Remove each went missing.

---

## 5. Exact next steps

### A — Finish slice 005 User Story 1 · **unblocked, owner: whoever picks this up** · 15 tasks

**T049–T054: the six API routes.** Fully specified in
`specs/005-resume-tailoring/contracts/http-api.md`. Everything they call already exists and is
tested — `create_pending_version`, `run_tailoring`, `decide_item`, `approve_version`.

Three things that will bite:

- **`selectinload(ResumeVersion.items)` on every read.** `.items` lazy-loads, and in a route that
  is a 500 rather than a test failure. It already bit twice in this slice.
- **422 must distinguish `no_analysis` from `stale_analysis`.** `TailoringRefused` carries a
  `reason` for exactly this — "run a match analysis" and "re-run it, your profile changed" are
  different actions.
- **T054 says six routes**, not five. `GET /api/versions/{id}/run` was added after
  `/speckit-analyze` found the contract and tasks disagreed.

Then **T055** (ownership: no route accepts a client-supplied owner; another user's version is 404
not 403), and **T056–T063**, the frontend tab.

```bash
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy src
cd ../frontend && npm run lint && npm run typecheck && npm test && npm run build
```

### B — Push `main` · **unblocked, owner: the author's call** · 1 command

Seven commits sit on local `main` and `origin/main` is still at `02f1d4d`. They are **contained in
the pushed branch**, so nothing is at risk — but the planning artifacts are invisible on GitHub's
main branch, and anyone opening a PR will see them as part of the diff.

```bash
git push origin main        # verify first: git log origin/main..main --oneline
```

### C — Slice 003 User Story 3 · **still blocked on the author** · 11 tasks

A JobTracker export saved to `backend/tests/fixtures/jobtracker_export.csv`. **Checked 2026-08-24:
the file has not arrived.** The mapping is written; this proves it against real data.

### D — Measure what has never been measured · **blocked on A** · T085–T087

No real provider call has been made. SC-006 ($0.30) and SC-001 (90s / 3min) are targets. Measure
both paths — first-pass clear and full revision budget — and record in `research.md` R5 the way
slice 004's R8 recorded its own. **If a target is missed, mark it missed in `spec.md`** rather than
adjusting the number.

### E — The three documentation corrections · **unblocked** · T080–T082

- **T080** — `docs/03` §10.1 needs `Awaiting approval`. The code has the state; the domain model
  does not, and a lifecycle described in two places will disagree.
- **T081** — `ports.py`'s docstring says self-critique "belongs in the agent runtime, not here" and
  calls it slice 004. The runtime now exists and is slice 005.
- **T082** — `CLAUDE.md` calls the no-loop boundary "the line the guard actually protects". Nothing
  executable ever asserted it.

### F — Also worth doing when convenient

- **Open the PR.** `https://github.com/nirtituani/CareerHQ/pull/new/005-resume-tailoring`
- **`/security-review` on the branch diff** (T090) — new routes, two migrations, a new user-facing
  surface.
- **Rotate the database password** and restart `pgvector`.
- **Rotate the logo.dev token** hardcoded in public source at `ApplicationTable.jsx:4` in
  `nirtituani/job-tracker-web`.
- **Decide the open question in `spec.md` § Open Decisions**: does `user_corrected` constrain what
  tailoring may rewrite? Undefined in the spec, the design and `docs/03`. Currently corrected facts
  are treated like any other. Worth settling before slice 006, where a retrieved rubric will push
  harder on rewording.

---

## 6. Process reminders

- **Spec-Driven Development** via Spec-Kit: `specify → plan → tasks → analyze → implement →
  verify`. **Do not skip `analyze`** — this slice is the case study. It found two constitution MUSTs
  with zero test coverage, and both gaps were *invariants* rather than features. Feature work
  generates obvious tasks; "nothing changed" does not.
- **Tests first**, and the failure message matters. `ModuleNotFoundError` because the module does
  not exist yet is a valid red.
- **Any test asserting an absence or an invariant must be watched failing.** Four in
  `test_tailoring_schema.py`, plus both critical ones in `test_owner_data_untouched.py` and
  `test_version_immutability.py`, were drilled this session and each named the exact violation.
- **Verify in Docker, then in a browser** on `localhost` — not `127.0.0.1`, which 403s its own
  chunks in Next.js dev with no console error. Every display bug in this project was found by a
  person looking at real data.
- **Backend gates run on the host, never in the container.** `backend/.dockerignore` excludes
  `tests/`, so an in-container pytest collects nothing and looks like a pass.
- **`docker compose build backend && docker compose up -d backend`** after backend code changes.
  `up -d` alone recreates the container from the same baked image.
- **Update `tasks.md` as you go**, and amend a task's text when the implementation deviates. T026
  was amended this slice: the scripted seam is a test double, not an extension of the production
  fixture gateway.
- **`/handoff` before `/clear`.** It does not run automatically.
