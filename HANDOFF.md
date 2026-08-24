# HANDOFF

**Last updated:** 2026-08-24 · **Commit:** `798dc25` · **Branch:** `005-resume-tailoring`, 5 commits ahead of origin

> **Slice 005 — Resume Tailoring is 91 of 97.** All three user stories are built, tested and
> **reachable in a browser**. The six routes, the Tailor tab, the diff, per-item approval and the
> audit view all work against real data on the local stack.
>
> **The six open tasks are one thing: nothing has ever called a real provider.** T085–T089 measure
> SC-001 (90s/3min) and SC-006 ($0.30) and deploy. **The author has explicitly deferred the real
> Anthropic run** pending their own review of the completed flow — see §5A. Do not spend it without
> asking.
>
> Measured this session: **400 backend tests** (82.98% coverage), **147 frontend** (10 files), ruff,
> mypy, oxlint, tsc and `next build` all clean.
>
> **Seven commits still sit unpushed on local `main`.** Contained in this branch, so nothing is at
> risk. See §5C.

This file is the volatile half of the project's memory: what is true *right now* and what to do
next. `CLAUDE.md` is the durable half — conventions, gotchas, and how the project works. When those
two disagree about status, **this file wins**.

---

## 1. Core goal

CareerHQ is an AI-powered career intelligence platform. A user imports a CV, tracks applications,
and an agent tailors the resume to a specific job description — **with the user's approval on
every change**.

Built solo as a course project on a four-to-six-week budget. Two things are graded requirements and
are not optional: **deployment** (slice 002, done) and the **evaluation harness** (slice 007, not
started).

The seven non-negotiable principles are in `.specify/memory/constitution.md`. Violations of II–IV
are release blockers.

### The roadmap was renumbered on 2026-08-22

Build order now matches slice numbers.

| | Slice | State |
|---|---|---|
| 005 | **Resume Tailoring** | **91/97 — built, unmeasured, undeployed** |
| 006 | Document & Retrieval — RAG over guidelines, PDF export, submit-and-lock | Not started |
| 007 | Evaluation & Benchmark | Not started. **Graded** |
| 008 | Company Research | Droppable (`docs/08` §11) |
| 009 | Career Advisor | Droppable |

**Evaluation has been deferred twice and two slices stand in front of it.** If the budget runs
short, 008 and 009 are what get dropped. Recorded in `docs/05` §5.7 in those words.

**The 005/006 boundary is structural and must stay that way.** RAG is an *input enhancement* via
the `GuidelineSource` port, not a redesign of the tailoring workflow. Slice 006 swaps
`StaticGuidelines` for a retrieval implementation and changes nothing else — no node, no state key,
no finalisation rule. `application/guidelines.py`'s docstring is the argument; it also explains why
the port deliberately has no `top_k`, no scores and no embedding parameters.

---

## 2. Current implementation status

**Measured 2026-08-24, not copied:**

| Gate | Result |
|---|---|
| Backend suite | **400 passed**, 82.98% coverage (gate 80%) |
| Frontend suite | **147 passed** (10 files) |
| ruff format / check | clean |
| mypy strict | clean, 60 source files |
| oxlint / tsc / next build | clean |

| Slice | Tasks | State |
|---|---|---|
| 001 — Platform Foundation | 69 / 69 | Complete |
| 002 — Deployment | 52 / 52 | Complete |
| 003 — Data Foundation | 98 / 109 | US1, US2 done. **US3 blocked on a JobTracker CSV** |
| 004 — Match Analysis | 89 / 89 | Complete, verified in production |
| **005 — Resume Tailoring** | **91 / 97** | **Built. See §5A** |

### Live system

**https://frontend-production-02ac.up.railway.app** — `/` answers 307, readiness reads
`database ok · cache not_configured · object_storage ok · ai_provider ok`.

**Nothing from slice 005 is deployed.** It lives on this branch.

Local database, checked this session: **8 applications, 0 resume_versions**. The zero is correct —
two versions were seeded by hand during the browser walkthroughs and deleted afterwards, because
they were fabricated and had no business in a real record.

### What slice 005 built

**The agent runs.** Four nodes — plan, draft, review, revise — orchestrated by LangGraph, each
calling the existing `complete()` seam. Bounded at two revisions, escalating Sonnet → Opus on the
second by **task name**, which keeps `docs/08` §3.2.3 configuration rather than a branch.

**LangGraph orchestrates and owns nothing.** Persistence, business state, audit, ownership and
finalisation stay in `tailor_resume.py`. The test of that boundary: deleting every LangGraph import
and rewriting the graph as a loop would require no schema change and no change to any use case.

**The severity split runs in the use case, before any row is written.** An `ungrounded` finding
discards its proposal and restores the owner's wording, so a fabricated claim has no persisted
representation and can never reach an approve button.

**Six routes, all owner-scoped.** `POST /applications/{id}/tailor`, `GET /versions/{id}`,
`PATCH /versions/{id}/items/{item_id}`, `POST /versions/{id}/approve`, `GET /versions/{id}/run`,
`GET /applications/{id}/versions`. Another owner's resource is 404, never 403.

**The Tailor tab.** Five states rendered distinctly, per-item accept/reject/edit, findings nested
under the proposals they concern, the confidence score labelled so it cannot be read as the match
score, and an audit disclosure showing the plan, the protected gaps, per-task models, tokens and
cost.

### What is NOT built

- **No real provider call has ever been made.** Every test runs against a scripted double. SC-006
  ($0.30) and SC-001 (90s / 3min) are **unmeasured targets**.
- **Slice 005 is not deployed.**
- **FR-017 has no test that answers it** — whether a tailored resume claims anything the owner did
  not do is a judgement a person has to make (T087).

---

## 3. Files modified

Slice 005 spans `f414caf..798dc25`. Regenerate with:

```bash
git diff --name-status f414caf~1..HEAD -- backend/src frontend/src
```

### Read these first

| File | Why |
|---|---|
| `specs/005-resume-tailoring/contracts/tailoring-workflow.md` | O1–O8. The LangGraph/CareerHQ boundary, and the test of it |
| `backend/src/careerhq/application/tailor_resume.py` | The use case: preconditions, execution, finalisation, persistence, the reaper |
| `backend/src/careerhq/application/finalisation_rules.py` | The severity split, versioned. Where Principles II and III are reconciled |
| `backend/src/careerhq/application/guidelines.py` | **The 005/006 boundary.** Read before touching slice 006 |
| `frontend/src/components/applications/tailor-tab.tsx` | The five states, and why each is distinct |

### Backend source

```
NEW  api/routes/tailoring.py                (the six routes)
NEW  application/tailor_resume.py           application/finalisation_rules.py
NEW  application/guidelines.py              (GuidelineSource port + static rubric)
NEW  application/agents/tailoring/{graph,state,prompts,__init__}.py
NEW  domain/models/tailoring.py             domain/schemas/tailoring.py
MOD  config.py                              (five llm_model_tailor_* entries)
MOD  ports.py                               (T081 — the docstring was describing slice 004)
MOD  main.py                                (router registration)
MIG  0010_resume_versions · 0011_version_items_and_findings
```

### Frontend source

```
NEW  components/applications/tailor-tab.tsx        tailor-diff-item.tsx
MOD  lib/api.ts                     (six calls; ApiError now carries the unflattened detail)
MOD  components/applications/detail-tabs.tsx       (the Tailor tab)
MOD  app/applications/[id]/page.tsx (removed the stale disabled "Tailor CV" button)
MOD  app/globals.css                (**the shadcn token bridge — see §4**)
```

### Tests

```
NEW  backend/tests/support/{scripted_seam,tailoring_fixtures,__init__}.py
NEW  backend/tests/integration/test_tailoring_api.py         (25)
NEW  backend/tests/integration/test_tailoring_ownership.py   (10)
NEW  backend/tests/integration/test_tailoring_workflow.py    (15)
NEW  backend/tests/integration/test_tailoring_{preconditions,reaper,schema,concurrency}.py
NEW  backend/tests/integration/test_{owner_data_untouched,version_immutability,version_status_transitions}.py
NEW  frontend/src/components/__tests__/tailor.test.tsx       (30)
NEW  frontend/src/components/__tests__/tailor-findings.test.tsx (7)
MOD  backend/tests/integration/test_auth.py  (**the enumeration was checking zero routes**)
MOD  frontend/src/components/__tests__/tokens.test.ts (a Tailwind theme-colour gate)
```

---

## 4. What failed

The expensive part of this project's memory. **Append-only — never delete an entry.** Each of these
was tried and did **not** work; re-attempting any of them costs real time.

### Gates that were not gates (slice 005 — three of them, all shipping green)

- **`app.routes` stopped containing included routers.** FastAPI 0.141 wraps them as
  `_IncludedRouter` objects with no `path` attribute at all. `test_every_non_public_route_requires_a_session`
  walked `app.routes` and skipped any path containing `{`, so it matched only `/api/docs` and
  `/api/openapi.json` — both public, both skipped. **The gate was examining zero routes and
  passing**, and had been since slice 003 added the first parameterised route. Enumerate from
  `app.openapi()["paths"]`, which is what a client can actually reach, **and assert how many you
  examined** — the count is the only part that would have caught either failure.
- **An undeclared Tailwind theme colour generates no rule and no warning.** `src/components/ui/` is
  shadcn, written against `bg-primary`, `bg-accent`, `border-input`, `ring-ring`. None were declared
  in `@theme`, so `bg-primary` computed to `rgba(0, 0, 0, 0)` and **all twenty default `<Button>`s
  in the application rendered as bare text**, for three slices. It survived a passing build, tsc,
  lint, 130 tests and the existing `var(--token)` scan, because none of them ask whether a class
  name *resolves*. It survived human use because `outline` and `ghost` are *meant* to be
  transparent — two variants of three looked perfect. Found by opening the Tailor tab in a browser.
  `@theme inline` is required, not `@theme`, or the values freeze at compile time and dark mode
  never applies.
- **A `-k` selector that matches nothing reports a cheerful pass.** Drilling the disclosure gate
  with `-k leak` selected **zero** tests and printed no failure; it read as "the drill did not
  fire". The test name did not contain "leak" — a fixture argument did. **Read the
  `N deselected` count**, always.

### Slice 005 — the agent runtime

- **Assuming a LangGraph state key accumulates.** It does not. A key with no reducer is
  **overwritten**, measured against the installed 1.2.11. Applied to `usage` that keeps **one**
  record out of seven — an incomplete audit under Principle V, a cost figure wrong by up to 7×, and
  *nothing raises*. `Annotated[list, operator.add]` is required.
- **Believing the import guard covered the application layer.** It forbade exactly one package,
  `litellm`. Adding LangGraph made it actively worse: `langchain-core` arrives transitively, so
  `langchain_anthropic` became one install away, and the idiomatic LangGraph example binds a model
  *inside the node*. Now six packages.
- **Believing anything asserted "no call site loops".** Nothing executable ever did, and as of this
  slice the claim is **false** — the graph loops by design. Corrected in `ports.py` and `CLAUDE.md`
  (T081, T082). The real guard is the import-graph test.
- **Thinking the checkpointer could be avoided.** `langgraph-checkpoint` is a hard transitive
  dependency. What is declined is `langgraph-checkpoint-postgres`, a **separate** package.
- **`dataclasses.replace()` on a Pydantic model.** `DraftedItem` is a `BaseModel`; use
  `model_copy(update=...)`.
- **A table-driven loop over `(model, kind, accessor)` tuples** in `_render_master`. Three lines
  shorter and completely untypeable. Written out explicitly.
- **`TailoringRun.__new__()` to build an unsaved instance.** Bypasses SQLAlchemy's instrumentation;
  the first `setattr` fails with `'NoneType' object has no attribute 'set'`.
- **A module-level `pytest.mark.asyncio`** in a file that is half pure functions. It fails the sync
  tests outright — and warns rather than fails when the function is `async def` but not awaited.
- **`session.expire_all()` before re-reading.** The next attribute access does IO synchronously,
  which async SQLAlchemy answers with `MissingGreenlet`. Use an awaited `session.refresh(obj)`.
- **`json.load` in strict mode against the GitHub Actions API.** Control characters in commit
  messages break it. `strict=False`.

### Slice 005 — the routes and the interface

- **`is` against a `String`-column enum, again.** `approve_version` compared
  `item.decision is ProposalDecision.PENDING`. Items loaded by a route come from a session that did
  not write them, so `decision` is a plain `str` and the branch never fired: **approval silently
  accepted nothing.** This is the identical defect slice 004 shipped in `run_analysis`, invisible
  for the identical reason — the existing tests hold the session that created the row. Use `==`,
  and exercise the path through a second session.
- **Returning the stringified exception to the client.** `run_tailoring` wrote
  `f"{type(exc).__name__}: {exc}"` into two columns that two endpoints return verbatim and the
  interface renders in an alert, while logging only the class. **The detail went to the browser and
  the type went to the operator** — inverted from the T068 rule in `health.py`. A
  `psycopg.OperationalError` stringifies to the internal IP, port and database user. Found by T090.
- **A data-modifying CTE's INSERT is invisible to an UPDATE in the same statement.** Linking a
  freshly-inserted `tailoring_run` back to its `resume_version` inside one `WITH` chain matched
  **zero rows** and reported success — the UPDATE's targets come from the snapshot taken before the
  statement ran. Two statements.
- **Drilling a test can hit a database constraint before the assertion.** T064's first drill —
  misattributing a finding to an arbitrary row — was refused by
  `ck_reviewer_findings_uncovered_has_no_item`. A stronger answer than the test was asking for, but
  it does not drill the test. Flattening the attachment to `None` is the realistic regression.
- **A Python replace-script that asserts before writing drops *all* edits when one string does not
  match.** The `tasks.md` ticks for T083/T084/T090 were silently lost while the code commit went
  through, because a single em-dash phrase differed. Write each edit independently, or verify the
  file afterwards.
- **A stale "not built yet" marker is worse than a missing one.** The detail header carried a
  disabled `Tailor CV` button titled "arrives in the next release", directly above the working tab.
  The original reasoning — a button that looks live and does nothing is worse than one admitting it
  is not ready — was right while it was true.

### Slice 005 — assumptions about existing code that were wrong

- **`MatchAnalysis` has a `profile_id`.** It does not; only `application_id`.
- **`Application.current_analysis_id`.** It is `current_match_analysis_id`.
- **`MatchRequirement.text`.** The column is `text`, the Python attribute is **`text_`**.
- **A new `ItemDecision` enum.** `provenance.ItemDecision` already exists for the import reviewer.
  The tailoring one is `ProposalDecision`, and the vocabularies differ for a real reason: import
  review *discards*, tailoring *rejects* (the owner's wording stands).
- **`api/routes/__init__.py` is where routers are registered.** It is empty; every router is
  included in `main.py`'s `create_app`.

### Slice 004 — match analysis (every one passed a green suite)

- **`is` against an enum on a value read from the database.** See above; it recurred this slice.
- **A lazy relationship on a freshly added object** raises `MissingGreenlet` as a 500 when
  serialised. Assign collections at construction; the routes need `selectinload`.
- **Demanding a `shortfall` on `unverified`.** A real completion failed validation and the model was
  right: the profile's silence gives no basis for choosing one. The same trap was avoided in advance
  in slice 005 — an `uncovered` finding carries no item reference, enforced by a check constraint.
- **Reporting a cap that did not bite.** `capped_by` named a requirement whenever one *could* cap.
- **`var(--fg)` where the token is `--foreground`.** An undefined custom property fails silently and
  differently per property; three uses were `color:` and looked right by accident, the fourth was
  `fill:` and rendered black on a dark ground.
- **Building a CSS reveal the natural way round.** Reduced motion collapses animations to 0.01ms, so
  a base of "empty" plus an animation that fills it shows **zero** to everyone who reduces motion.
  **Slice 005 needed the rule the opposite way round**: the tailoring spinner has no value yet, so a
  full ring resting still would read as a finished run and an empty one as a failure. It rests on a
  quarter arc and the step name carries the meaning.
- **Trusting `drop_all` against an existing test database.** It emits from the *metadata*, not the
  database. `conftest.py` drops the schema. A `use_alter` constraint must also be **named**.
- **Assuming a stuck run could be recovered.** The in-flight guard answered 409 to the one action
  that recovers it. Hit three times, each needing SQL by hand.
- **Estimating output tokens.** R8 projected ~1,500 and measured **2,811** — 87% low.
- **A score computed independently of the thing it summarises.** v2 asked for four abstract
  dimensions; a real job returned eight requirements addressed and a score of 48 against an honest
  84.
- **Telling a model how to distribute its answers.** *"Most real profiles are mostly `partial`…"*
  made the model push verdicts down to comply.

### Testing (all slices)

- **Trusting the suite to catch display bugs. It never once has.** Contact fields, bullet
  attribution, skill categories, project URLs, and now every button in the application — all found
  by a person looking at real data.
- **`create_all` against an existing test database.** It does not reconcile an existing table.
  `conftest.py` drops the schema first. **Any test that asserts an absence must be watched failing.**
- **Asserting an absence against the wrong scope.** "No rejected toggle on the form" passed against
  a form that had one, because Radix renders dialogs into a portal and `container` was empty.
- **A test double that repeats its last answer.** Would make an unbounded loop look convergent.
  `ScriptedSeam` raises instead.
- **A guard with nothing to examine.** `test_task_model_config.py`'s first AST walk found **zero**
  call sites. Without its own `assert used`, it would have passed forever while checking nothing.
  Three more instances of this class shipped in slice 005 — see the top of this section.
- **Running a test against the real profile.** It merged a fictional CV into it and replaced the
  contact block. **Always use a scratch user**, seeded `@example.com` — pydantic's `EmailStr`
  rejects `.test`/`.invalid` and the 500 reads as a white-screen app bug.

### Deployment

- **`railway deployment redeploy` as a rollback.** It redeploys the *latest* deployment. A rollback
  also creates a **new** id carrying the **old** commit, so read which version is live from the
  commit.
- **Reading Railway logs for a message string.** Railway **blanks the `message` field** of parsed
  JSON logs. Put anything needed to debug production in `extra={…}` fields. This is why T090's fix
  puts `str(exc)` in `extra`, not in the message.
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
- **Reading a page that ships its own template.** Client-rendered boards serve `{{position.name}}`.
  Refuse, do not read.
- **A generic fetch for Comeet.** Needed a vendor adapter.
- **Assuming LinkedIn needs special handling — wrong, repeatedly.** A plain fetch returns 200.

### Product decisions tried the other way first

- **A `rejected` boolean beside the status.** There is no `rejected` column and its absence is a
  release blocker.
- **One overwritten date field.** `date_added` and `date_applied` are separate.
- **Labelling `EXTRACTED` provenance.** Every fact carries it, so the label said nothing. **The same
  reasoning governs the finding-attempt marker in slice 005**: it appears only when an item was
  flagged in more than one review pass.
- **A second render path for grouped skills.** It cost an affordance every time — Edit, then Add,
  then Remove each went missing. **This is why T077 was amended**: Edit is a peer of Accept and
  Reject rather than a field revealed by rejection, so there is one render path.

---

## 5. Exact next steps

### A — The real provider run · **blocked on the author, deliberately** · T085–T087

**The author has deferred this pending their own review of the completed flow.** They said they
would approve it explicitly afterwards. **Do not run it without that.**

Everything is in place: click **Tailor for this job** on any application with a `ready`,
non-stale match analysis. Four of the eight local applications qualify.

Measure **both** paths — first-pass clear, and full revision budget — and record tokens, cost and
elapsed time in `research.md` R5, the way slice 004's R8 recorded its own. Then compare against
**SC-006 ($0.30)** and **SC-001 (90s / 3min)**. **If a target is missed, mark it missed in
`spec.md`** rather than adjusting the number; slice 004 did exactly this with SC-004.

T087 is not automatable: read the tailored resume as a person and ask whether it claims anything
the owner did not do. FR-017 has no test that answers this.

```bash
docker compose up -d && open http://localhost:3000   # localhost, never 127.0.0.1
```

### B — Deploy slice 005 · **blocked on A** · T088, T089

A real run on the live system with `is_fixture = false`, a real model name, real token counts and a
real cost. Then verify the deployed database:

```bash
railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway \
  -c 'SELECT count(*) FROM resume_versions;'"
```

**The `PGHOST`/`PGPORT` override is not optional.** The running container carries a stale host from
a deleted proxy, and Railway recycles those ports — the default address now serves **another
tenant's** database and answers the PostgreSQL protocol.

### C — Push `main` · **unblocked, owner: the author's call** · 1 command

Seven commits sit on local `main` and `origin/main` is behind. They are **contained in the pushed
branch**, so nothing is at risk — but the slice-005 planning artifacts are invisible on GitHub's
main branch.

```bash
git log origin/main..main --oneline   # verify first
git push origin main
```

### D — Open the PR · **unblocked** · 1 command

Five commits are ahead of `origin/005-resume-tailoring`. Push, then:
`https://github.com/nirtituani/CareerHQ/pull/new/005-resume-tailoring`

### E — Slice 003 User Story 3 · **still blocked on the author** · 11 tasks

A JobTracker export saved to `backend/tests/fixtures/jobtracker_export.csv`. **Checked 2026-08-24:
the file has not arrived.** The mapping is written; this proves it against real data.

### F — Decide the open question in `spec.md` § Open Decisions · **owner: the author**

Does `user_corrected` constrain what tailoring may rewrite? Undefined in the spec, the design and
`docs/03`. Currently corrected facts are treated like any other. **Worth settling before slice
006**, where a retrieved rubric will push harder on rewording.

### G — Housekeeping · **unblocked**

- **Rotate the database password** and restart `pgvector`.
- **Rotate the logo.dev token** hardcoded in public source at `ApplicationTable.jsx:4` in
  `nirtituani/job-tracker-web`.

---

## 6. Process reminders

- **Spec-Driven Development** via Spec-Kit: `specify → plan → tasks → analyze → implement →
  verify`. **Do not skip `analyze`** — it found the two invariant tests this slice, and all three
  documentation corrections (T080–T082).
- **Tests first**, and the failure message matters. `ModuleNotFoundError` because the module does
  not exist yet is a valid red.
- **Any test asserting an absence or an invariant must be watched failing** — and check the
  `deselected` count, because a `-k` filter that matches nothing looks exactly like a pass.
- **When implementation predates a test** (US1 built most of US2 and US3), ticking the task on
  inspection is a lie. Break the implementation, watch the test name it, restore.
- **Verify in Docker, then in a browser** on `localhost` — not `127.0.0.1`, which 403s its own
  chunks in Next.js dev with no console error. **Every display bug in this project was found by a
  person looking at real data, including all twenty invisible buttons.**
- **Seed test data against a scratch user, and delete anything fabricated afterwards.** Two hand-
  seeded versions were used for the browser walkthroughs this session and removed; the local count
  is back to zero.
- **Backend gates run on the host, never in the container.** `backend/.dockerignore` excludes
  `tests/`, so an in-container pytest collects nothing and looks like a pass.
- **`docker compose build backend && docker compose up -d backend`** after backend code changes.
  `up -d` alone recreates the container from the same baked image. The frontend hot-reloads.
- **Update `tasks.md` as you go**, and amend a task's text when the implementation deviates. Four
  were amended this slice — T054, T056, T072 and T077 — and each amendment records why.
- **`/handoff` before `/clear`.** It does not run automatically.
