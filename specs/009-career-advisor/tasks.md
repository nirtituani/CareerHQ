# Tasks: Career Advisor Agent with Career Memory

**Input**: Design documents from `specs/009-career-advisor/` — [spec.md](spec.md),
[plan.md](plan.md), [research.md](research.md) (D1–D15), [data-model.md](data-model.md),
[contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: mandatory (Constitution VII; "Tests first" — write the test, watch it fail for
the right reason, then implement). Every gate task below names the drill: break the
behaviour, confirm the test names the violation, restore.

**Two invariants this list must not lose** (product owner, tasks approval):

1. **`left_open` is an explicit agent decision, never a default.** A reasoning output that
   simply *omits* a previously active memory fails the run (T027); `left_open` requires a
   stated reason (schema + gate). No code path may fill in `left_open` for a forgotten id.
2. **Retrieval into reasoning input is proven at the boundary.** At least one test (T026)
   inspects the actual rendered reasoning input and finds every prior active memory in it
   — asserting how many it found (a zero-memory prompt must fail the assertion, not pass
   it vacuously). The lifecycle is demonstrable as retrieve → reason over prior memory →
   disposition → persist, from what the run actually did.

**Organization**: by user story, so each is independently implementable and testable.
Paths are repo-relative; backend paths omit the `backend/src/careerhq/` prefix's
repetition only in prose, never in tasks.

---

## Phase 1: Setup

**Purpose**: constants, configuration and schemas every story reads.

- [x] T001 Create `backend/src/careerhq/application/advisor_rules.py`: `ADVISOR_RULES_VERSION = "v1-advisor"`, `SMALL_SAMPLE_FLOOR = 5`, `ACTIVE_MEMORY_CAP = 25`, `RUN_ABANDONED_AFTER = timedelta(minutes=10)`, `CAUSAL_PHRASES` (versioned first guess, per the `CONFIDENCE_THRESHOLD` discipline — the module docstring says so and says why changing any constant is a new version)
- [x] T002 Add `llm_model_advisor_grouping` (Haiku) and `llm_model_advisor_reason` (Sonnet) to `backend/src/careerhq/config.py` with the standard comment naming the Opus-fallback pricing trap; extend the existing model-for-task test to cover both names, asserting the count of task entries it examined
- [x] T003 [P] Write `backend/src/careerhq/domain/schemas/advisor.py`: `EvidenceFact`, `GroupingProposal`/`ProposedGroup`, `AdvisorReasoning`/`ProposedMemory`/`Disposition` per [contracts/reasoning-contract.md](contracts/reasoning-contract.md) — every conditional rule in `Field(description=...)` (a `model_validator` does not serialise, and the schema is the whole contract the gateway sends); `Disposition.reason` described as required for `retire` **and `leave_open`** (invariant 1)

## Phase 2: Foundational (blocking all stories)

**Purpose**: tables and the run skeleton. No story can start before these.

- [x] T004 Write the failing model tests first in `backend/tests/unit/test_advisor_models.py`: table names, the four `career_memories` CHECK constraints from [data-model.md](data-model.md), `uq_advisor_run_one_pending_per_user` partial index, `uq_memory_disposition_once_per_run`, `ck_memory_disposition_reason` covering `retired` **and** `left_open`; run them, confirm they fail with `ImportError` (the valid red)
- [x] T005 Create `backend/src/careerhq/domain/models/advisor.py`: `AdvisorRun`, `CareerMemory`, `MemoryDisposition` per data-model.md, with the deliberate-absence docstrings (no cap constraint — COUNT-shaped; no `is_stale` — the `match.py` argument); String columns for statuses (the `is`-vs-`==` enum gotcha noted at the column)
- [x] T006 Write migration `backend/alembic/versions/0021_career_advisor.py` by hand for the CHECK constraints (Alembic does not diff them); name every constraint; upgrade the local dev database and verify with `\d career_memories` that all four CHECKs exist
- [x] T007 Drill one schema gate: temporarily write a `retired` memory with `retired_reason = NULL` through a raw statement and confirm the database refuses with `ck_career_memory_retired_reason`; restore. (A gate nobody has watched fail is not a gate.)
- [x] T008 Implement `create_pending_run` / `is_abandoned` in `backend/src/careerhq/application/advise_career.py` on the `analyze_match.py` pattern: pending row committed before any provider call, per-user partial-unique race closed in the schema, abandoned rows read as failed and never block; unit tests including the two-clicks race (second insert violates the index) and the abandoned-row recovery
- [x] T009 Register `backend/src/careerhq/api/routes/advisor.py` in `main.py`'s `create_app` with stub routes so the existing 401-enumeration test picks the paths up (it asserts how many routes it examined — the count changes, on purpose); assert all five contract routes return 401 unauthenticated
- [x] T046 **The FR-017 boundary gate** (added by the analyze remediation, G1; belongs to this phase — execute after T005): a deterministic architecture test in `backend/tests/unit/test_advisor_boundary.py` on the `test_a_submitted_resume_is_insert_only` whitelist pattern, proving **only the Advisor capability reads or writes `CareerMemory`** (and `MemoryDisposition`, `AdvisorRun`): walk `src/` for every mention of the three class names — construction, column reference, `select`, annotation, and handing the class to a helper — and fail on any file outside the whitelist (`domain/models/advisor.py`, `application/advise_career.py`, `application/advisor_evidence.py`, `application/advisor_grounding.py`, `api/routes/advisor.py`, migrations); **assert the count of files walked is > 0** (a gate with nothing to examine passes forever), and drill it: temporarily reference `CareerMemory` from `application/tailor_resume.py`, confirm the failure names that file, restore

**Checkpoint**: schema live, run lifecycle safe, routes owned, the memory boundary gated. Stories can begin.

## Phase 3: User Story 1 — First analysis: history becomes evidence-backed memories (P1)

**Goal**: one run turns raw history into grounded, denominator-carrying active memories,
with honest insufficient-data and empty states.

**Independent test**: seed a scratch user with applications and outcomes only (no match
analyses), run, and verify every persisted claim recomputes from the seeded rows; the
insufficient-data answer appears for skill patterns; no-history spends nothing.

- [x] T010 [P] [US1] Write failing tests for the evidence pack in `backend/tests/unit/test_advisor_evidence.py`: each Tier 1 family from research D10 (status distribution, rejection rate, volume by month, time-in-status, `imported_match_rating` distribution, **match-analysis coverage**) produces `EvidenceFact`s with numerator, denominator, date range and `record_ids`; determinism (same rows → identical pack, FR-006); precomputed percentages so the model never has arithmetic to do; requirements-NULL rows appear in no skill denominator
- [x] T011 [US1] Implement `backend/src/careerhq/application/advisor_evidence.py` to those tests: pure functions over loaded rows (relationships assigned at load with `selectinload` — the `MissingGreenlet` rule), fact ids as deterministic slugs, `basis` sentence per fact
- [x] T012 [P] [US1] Write failing tests for the creation-side grounding gate in `backend/tests/unit/test_advisor_grounding.py`: citation-existence (unknown `fact_id` → discard), numeral grounding (a claim digit absent from cited facts → discard; date-range years allowed; a claim with zero citations → discard), causality phrase → discard, **denominator presence (G2): every persisted claim contains at least one cited fact's explicit `numerator/denominator` pair, and a claim with no numbers at all fails this check rather than bypassing it**, floor forces `tentative` (denominator 4 → tentative even when the model said otherwise — the honest downgrade, not a refusal), contradiction between two fresh creates on one `(kind, scope)` (higher priority survives), **cap with the defined evaluation order (G4): dispositions apply conceptually first, creates count against the post-disposition active set — the at-cap case (25 active, one create + one retire in the same run) is valid and ends at 25, and a naive pre-disposition count is the drilled failure** — then overflow discards in priority order. The `leave_open` → `left_open` action mapping (proposal verb → recorded participle) lives in this module alone and is covered here (I1). Every discard emits a log record with `extra={run_id, gate, detail}` — **assert on the record this module emitted, filtered by logger name** (testing rule 11) — and the discard/apply counters are returned to the caller
- [x] T013 [US1] Implement the creation-side gate in `backend/src/careerhq/application/advisor_grounding.py` to those tests
- [x] T014 [US1] Write the reasoning-prompt renderer and its test: evidence facts rendered `[fact: <id>] <value> (n=<num>/<den>, <range>)`, rules block (floor, cap, digits-from-facts, denominators-in-claims, no causal language, never a distribution instruction — the "most real profiles" lesson); test walks every rendered fact line back to a pack fact and **asserts the count of lines examined**
- [x] T015 [US1] Implement `run_advisor` (first-run path) in `backend/src/careerhq/application/advise_career.py`: pack → render → one `complete()` call (task `advisor_reason`) wrapped in `UsageRecorder` → creation gate → apply **in one transaction** (memories + disposition rows with `action='created'` + run completion with `ops_proposed/applied/discarded`, both models, tokens, cost). Never raises (the `run_analysis` contract); a failure marks `failed` with a user-safe kind, records `ExtractionFailedError.usage`, and touches no memory row. The scripted double **reads fact ids and figures out of the rendered prompt** (testing rule 4) and raises on repeat calls (`ScriptedSeam` precedent)
- [x] T016 [US1] Integration test `backend/tests/integration/test_advisor_first_run.py`: seeded scratch history through the real use case (double at the seam only) → memories persisted with frozen evidence; **SC-001 audit**: for every persisted memory, every numeral in the claim is found in its frozen evidence and every cited fact recomputes from the database rows named by `record_ids` — assert the number of memories audited is > 0 and equals what the run reported applying
- [x] T017 [US1] Failure honesty test: a seam that raises mid-run → run `failed`, cost recorded (not `$0` — the graph-that-raises lesson), zero memory rows written, error text names a kind not a detail (`str(ValidationError)` embeds `input_value=` — `safe_validation_errors()` applies)
- [x] T018 [US1] Implement `GET /api/advisor`, `POST /api/advisor/runs` (202/409/409-no-history), `GET /api/advisor/runs/{id}` in `backend/src/careerhq/api/routes/advisor.py` per [contracts/advisor-api.md](contracts/advisor-api.md), background task via the `_score_in_background` pattern; route tests: 202 body is the pending row, second POST 409s, no-history 409s **before** any run row exists, coverage block always present, orderings (`priority DESC NULLS LAST`)
- [x] T019 [P] [US1] Add advisor client functions and types to `frontend/src/lib/api.ts` (memory, run, coverage shapes from the contract)
- [x] T020 [US1] Build `frontend/src/app/advisor/page.tsx` + `frontend/src/components/advisor/`: memory cards (claim, evidence with denominators, scope, priority **with its `priority_reason` rendered wherever a priority is shown — FR-022 requires the reasoning stated, A1**, as-of), run trigger with visible in-progress state (poll by run id, **keyed on the record id** — local state survives route changes), honest empty state, insufficient-data/coverage line, failure state that keeps serving the previous memories; Vitest tests including: the empty state names what is needed, and the run-status assertion waits for the *run* fetch, not the page load (the `waitFor` race lesson — two effects resolve independently)
- [x] T021 [US1] Flip `/advisor` to `ready: true` in `frontend/src/components/sidebar-nav.tsx` (the stale-"Soon"-marker rule: this happens in the same story that makes the page real, not before, not after); test asserts the nav renders a link, not the Soon span — **query inside the nav container**, portals lie (testing rule 3)

**Checkpoint**: US1 demoable end to end — the MVP.

## Phase 4: User Story 2 — The memory lifecycle (P1)

**Goal**: the second run retrieves prior memories, reasons over them, and dispositions
every one — confirm / supersede / retire / left_open — with lineage the user can read.

**Independent test**: run, mutate history in three directions, run again; verify the three
outcomes, the disposition log's completeness, and (boundary test) that the prior memories
were in the reasoning input.

- [ ] T022 [P] [US2] Write failing tests for disposition application in `backend/tests/unit/test_advisor_dispositions.py`: `confirm` advances `last_confirmed_at` and writes a disposition row with `evidence_delta` from `fresh_fact_ids`, frozen `evidence` byte-identical before/after; `supersede` inserts the new memory with `supersedes_id`, old row → `superseded`, content columns untouched; `retire` requires a reason; **`leave_open` requires a reason and writes an explicit `left_open` row — there is no code path that defaults an unmentioned memory to `left_open`** (invariant 1: construct a reasoning output omitting one active memory id and assert the *run fails* with the omission named, rather than any disposition being synthesised)
- [ ] T023 [US2] Implement disposition application in `advise_career.py`/`advisor_grounding.py` to those tests: completeness check `set(active+tentative ids) == set(disposition memory_ids)` before anything persists (a shortfall fails the run — FR-013's "run defect"), forward-only status transitions (a `superseded`/`retired` row re-read from the database refuses resurrection — **test through a second session**, the enum-identity-map gotcha), reconciliation so no two surviving actives share `(kind, scope)`
- [ ] T024 [US2] Extend the prompt renderer: active/tentative memories as `[memory: <uuid>] (<status>, kind, scope, confirmed <date>) "<claim>"` with frozen figures; the disposition instruction naming all four actions and that every `[memory: …]` id must appear in exactly one disposition. **Absence test (G3, FR-014)**: with superseded and retired rows present in the database, assert their ids appear in **no** `[memory:]` line — the absence asserted against the `[memory:]` marker specifically, not the whole prompt (dismissed rows legitimately appear via `[dismissed:]`), and assert the count of `[memory:]` lines examined equals the active+tentative count
- [ ] T025 [US2] Extend the immutability guard: a test in the `application/immutability.py` drill style asserting `claim`, `kind`, `scope_kind`, `scope_value`, `evidence`, `supersedes_id`, `recreates_dismissed_id`, `advisor_run_id`, `created_at` cannot be modified after insert; watch it fail by temporarily permitting one write, restore
- [ ] T026 [US2] **The boundary retrieval test** (invariant 2), `backend/tests/integration/test_advisor_memory_retrieval.py`: first run creates N ≥ 2 memories; second run's scripted seam **captures the rendered reasoning input it was actually called with** and the test asserts (a) every one of the N prior memory ids appears in that input, (b) N is asserted — a run with zero prior memories fails this test rather than passing vacuously, (c) the claims travel with their ids (the double reads them out of the prompt to build its dispositions — proving a model *could*), and (d) **the G3 exclusion at the boundary**: a superseded and a retired memory existing before run 2 appear in no `[memory:]` entry of the captured input, while a dismissed one appears only via `[dismissed:]`. This is retrieve → reason over prior memory → disposition → persist, demonstrated from what the run did, not from plumbing
- [ ] T027 [US2] Lifecycle integration test `backend/tests/integration/test_advisor_lifecycle.py` (the SC-002 walk): seed → run 1 → mutate history to confirm one / contradict one / moot one → run 2 → assert: one `confirmed` (with delta), one `superseded` (lineage link, old evidence intact), one `retired` (reason), disposition rows for **every** pre-run-2 active memory exactly once (`uq_memory_disposition_once_per_run` plus a count equality against the pre-run active set), the omission case from T022 drilled at this level too, and **the A2 failure case: a third run whose seam raises mid-disposition leaves the existing active memory set byte-for-byte unchanged** (compare a full serialisation of every memory row before and after — id, status, claim, evidence, timestamps — not just counts) while the failed run still records its reason and cost (SC-005 on the run that matters most: the one with memories at stake)
- [ ] T028 [US2] Implement `GET /api/advisor/memories/{id}` (memory + lineage walk + disposition history; any status readable; 404 cross-user); route test walks a three-deep supersession chain
- [ ] T029 [US2] Frontend lifecycle surface in `frontend/src/components/advisor/`: new/confirmed/superseded/retired badges after a run ("since the last analysis"), lineage view on a memory (chain with dates and what changed), history section (superseded/retired readable); Vitest tests query within the rendering container

**Checkpoint**: the graded lifecycle is real and drilled. This plus US1 is the defensible slice.

## Phase 5: User Story 3 — Skill-level patterns from analysed postings (P2)

**Goal**: grouping-mediated Tier 2 facts and memories that grow with match analyses,
honest at small N.

**Independent test**: seed several match analyses with shared skills under varied
wordings; verify counts flow through the stored grouping and verdicts are respected.

- [ ] T030 [P] [US3] Write failing tests for grouping validation in `test_advisor_grounding.py`: unknown member id → group dropped and recorded; an id in two groups of one `group_kind` → second dropped; surviving groups only feed counting; the grouping lands in the evidence of any memory citing its facts (FR-007's auditability)
- [ ] T031 [US3] Implement the grouping step in `advise_career.py`: render enumerated titles `[app: <uuid>] <title>` and requirement rows `[req: <uuid>] <verbatim> (verdict, importance)`; one `complete()` call (task `advisor_grouping`, Haiku) — **skipped entirely** when nothing qualifies (no Tier 2 data, <2 distinct titles), with a test asserting the seam was not called (a run must not spend a completion to learn nothing)
- [ ] T032 [US3] Tier 2 fact families in `advisor_evidence.py`: per-verdict requirement frequency over surviving skill groups, match score by role-family group, all denominators scoped to analysed applications; test walks every Tier 2 fact's `record_ids` to real `match_requirements` rows and asserts gap-memories count `gap`/`partial` verdicts, never `confirmed`
- [ ] T033 [US3] Floor behaviour end to end in `test_advisor_lifecycle.py`: 4 analysed postings → the skill memory persists as `tentative` with its denominator in the claim; a later run with 6 → the disposition path promotes `tentative → active`; below-floor withholding renders the insufficient-data fact instead
- [ ] T034 [US3] Frontend: tentative marking (visibly provisional, denominator stated), coverage line driven by the coverage fact ("skill patterns grow as applications get match analyses"), grouping visible inside a memory's evidence ("read as AWS: 16 requirements"); Vitest tests

**Checkpoint**: Tier 2 grows organically; honesty floor demonstrated both directions.

## Phase 6: User Story 4 — The user curates what the advisor remembers (P3, droppable)

**Goal**: dismissal as retirement, enforced against recreation in two layers.

**Independent test**: dismiss → gone from active with reason; re-run unchanged → not
recreated; change evidence materially → recreated as new with history visible.

- [ ] T035 [P] [US4] Write failing tests: `POST /api/advisor/memories/{id}/dismiss` → 200 retires with `user_dismissed`, 409 on terminal rows (re-termination refused), 404 cross-user; the deterministic recreation gate (same `(kind, scope)`, identical `(fact_id, numerator, denominator)` tuples → discard-with-record; changed tuples → survives carrying `recreates_dismissed_id`)
- [ ] T036 [US4] Implement the dismiss route and the recreation gate (`advisor.py` routes + `advisor_grounding.py`); dismissed memories render in the reasoning input as `[dismissed: <uuid>] "<claim>" — dismissed by the user; do not recreate` (extend T024's renderer test: the marker is present, **and its id set is asserted against the dismissed rows** — count what you examined)
- [ ] T037 [US4] Lifecycle-level dismissal test in `test_advisor_lifecycle.py`: dismiss → run on unchanged data → claim absent from actives and the discard recorded on the run (`ops_discarded > 0` distinguishable from found-nothing); mutate evidence → run → recreated as new, `recreates_dismissed_id` set, dismissal readable in history
- [ ] T038 [US4] Frontend: dismiss action on a memory card (explicit, not hidden behind a second render path — the affordance-per-render-path lesson), "dismissed by you" in history, dismissal lineage on a recreated memory; Vitest tests

## Phase 7: Polish, verification, documentation

- [ ] T039 [P] Extend `backend/tests/integration/test_profile_content.py`-style content coverage to the advisor read path: every stored memory column the contract exposes reaches the API (the suite has never caught a display bug — this is the mechanism that comes closest)
- [ ] T040 [P] Confirm the architecture import gate covers the new modules (`test_the_application_layer_imports_no_provider_sdk` walks `application/` — verify the new files are in its walk and the walked-module count went **up**; if the count is not asserted today, assert it now)
- [ ] T041 Run the full backend gates on the host from `backend/` (`pytest` with PostgreSQL up — skipped tests cover nothing and trip the coverage gate; `ruff format --check`, `ruff check`, `mypy` strict) and the frontend gates (`lint`, `typecheck`, `test`, `build`); record the numbers
- [ ] T042 Execute [quickstart.md](quickstart.md) against the Docker stack in a browser with a scratch `@example.com` user (never `.test`): all seven scenarios including the lifecycle walk, dismissal, failure honesty (`docker compose up -d backend` after the `.env` change — `restart` does not reread it; `build` first — the backend mounts nothing); delete everything seeded by hand and count the real profile's rows before and after
- [ ] T043 Measure and record in this file's completion notes: wall-clock per run, cost per run from `advisor_runs` (SC-006, SC-007), and the SC-004 outcome against production-shaped data
- [ ] T044 Update the living documents truthfully: `docs/05_Implementation_Plan.md` and `docs/08_Technical_Spec.md` slice-009 rows (status + what shipped), `docs/07_Capabilities.md` §3.5 (mark the lightweight-prioritization delivery and the **explicitly deferred** richer roadmap — clarification Q1, never silently dropped), `CLAUDE.md` architecture section if the advisor earns a durable subsection; HANDOFF per `/handoff`
- [ ] T045 Deploy: merge-gated by review; after deploy, `alembic upgrade head` ran in pre-deploy (read the deploy log), readiness 200, `/advisor` serves for the real account with the honest coverage line ("N of 97 analysed") — read the live version from the **commit**, never the deployment id

---

## Dependencies & execution order

- **Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2)** are strictly ordered: the
  lifecycle needs a first run to disposition.
- **Phase 5 (US3)** depends on Phase 3 (the pack and gate) and touches the same renderer
  as Phase 4 — do it after US2 to avoid merge churn in `advise_career.py`.
- **Phase 6 (US4)** depends on Phase 4 (retirement machinery) and is droppable.
- **Phase 7** last; T044/T045 only after everything above holds.

**Parallel opportunities**: T003 with T001–T002; T010/T012 together (different test
files); T019 alongside T015–T017; T030 with T029; T035 with T034; T039/T040 together.
T046 (numbered out of order by the analyze remediation) runs in Phase 2 after T005 and
parallel to T008–T009.
Within a story, test-writing tasks marked [P] can precede their implementations in one
sitting — the failing-first order is the constraint, not the calendar.

## Implementation strategy

**MVP = Phase 1–3 (US1)**: demoable first run on real Tier 1 data. **The slice is not
done at MVP** — US2 is the requirement (the product owner's invariants live in T022,
T026, T027), and US1+US2 is the defensible unit. US3 rides the same machinery; US4 is
the first thing to drop under pressure, by design.

One checkout, one test database: `CAREERHQ_TEST_DATABASE_URL=…/careerhq_test_009` when a
second worktree is in play (the DROP SCHEMA collision is a recorded wrong-conclusion
generator). Tick boxes as tasks complete; amend task text where reality deviates — a task
list that lies about what happened is worse than none.
