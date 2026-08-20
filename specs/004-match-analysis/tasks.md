---
description: "Task list for Match Analysis implementation"
---

# Tasks: Match Analysis

**Input**: Design documents from `/specs/004-match-analysis/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/match-analysis.md](./contracts/match-analysis.md),
[contracts/http-api.md](./contracts/http-api.md), [quickstart.md](./quickstart.md),
[docs/09_Design_Language.md](../../docs/09_Design_Language.md)

**Tests**: Included. Constitution Principle VII makes 80% backend coverage a merge gate, FR-027 to
FR-029 are testing requirements in their own right, and
[contracts/match-analysis.md](./contracts/match-analysis.md) lists nine obligations (T1–T7, T3a,
T3b) that must fail before the implementation satisfying them.

**Organization**: Grouped by user story so each is independently shippable and demo-able.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1 / US2 / US3, mapping to the user stories in spec.md
- Every code task names the exact file it touches

## Task kinds that are not code

- 🔧 **MANUAL** — performed in an external console. States exactly what to do.
- 👁 **OBSERVE** — verified by looking at the running system rather than by a test. Each states
  what to look for **and what failure looks like**.

## Two rules this slice cannot bend

**Watch every absence-asserting test fail first.** `create_all` does not reconcile an existing
table. Slice 003 lost a release-blocker assertion to exactly this — T067 passed against a
deliberately added column until `conftest.py` dropped before creating. Any task below that asserts
something is *absent* or *rejected* must be watched failing for the right reason.

**Rebuild the backend after code changes.** `docker compose up -d backend` restarts the baked
image and silently runs the old code. `docker compose build backend && docker compose up -d backend`.

---

## Phase 1: Setup

- [x] T001 Add `llm_model_match_analysis: str = "anthropic/claude-sonnet-5"` to
      `backend/src/careerhq/config.py`, beside the existing per-task entries. **This ships in the
      same commit as the use case, not after it** — `model_for_task` falls back to
      `llm_provider_model`, which is Opus, so a missing entry runs every analysis at ~2.5× cost
      silently. The same fallback already caught CV extraction once.
- [x] T002 [P] Test in `backend/tests/unit/test_config.py`: `model_for_task("match_analysis")`
      returns the configured Sonnet model and **is not equal to** `llm_provider_model`. Watch it
      fail with T001 reverted — a test that cannot detect the fallback is not a test of it.
      (Contract T6.) **Watched failing**: `assert 'anthropic/claude-opus-5' ==
      'anthropic/claude-sonnet-5'` — the fallback was live, which is the trap itself.
- [x] T003 [P] Confirm `backend/tests/conftest.py` drops before creating, so schema-shaped
      assertions in this slice test the current schema rather than a stale snapshot. If it does
      not, fix it here before anything else asserts a constraint.
      **Verified, no change needed** — `conftest.py:141-142` runs `drop_all` then `create_all`,
      carrying the comment "Dropped first, because `create_all` skips tables that already exist".
      Slice 003 fixed this; the twelve absence-asserting tasks below can rely on it.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Blocks every user story.** The R1 correction is here rather than in US1 because scoring built on
the current `job_description` semantics would be wrong in a way no later task could detect.

### The R1 correction — stop discarding the posting

- [x] T004 Test in `backend/tests/unit/test_extract_job.py`: extracting from posting text returns
      **both** the full body as `job_description` **and** the requirements as a separate list.
      Watch it fail — today the body is discarded and the joined requirements take its place.
- [x] T005 [P] Test in `backend/tests/unit/test_extract_job.py`: a posting yielding **no**
      requirements stores the body as `job_description` and an **empty list**, not `NULL`.
      `NULL` (never captured) and `[]` (captured, none found) are different facts and the whole
      legacy-row decision rests on them staying distinguishable.
- [x] T006 Add `requirements: list[str]` to `JobPostingExtraction` in
      `backend/src/careerhq/domain/schemas/job.py`.
- [x] T007 Change `backend/src/careerhq/application/extract_job.py` to stop collapsing
      requirements into `job_description`. The body becomes `job_description`; the list becomes
      `requirements`. **Amend the comment block that records the old decision** rather than
      deleting it — it explains why the reversal happened.
- [x] T008 [P] Update `backend/src/careerhq/infrastructure/jobs/parse.py` and
      `comeet.py` if either constructs `JobPostingExtraction` positionally.
      **No change needed** — `parse.py:219` constructs with keywords and `comeet.py` does not
      construct one at all. `requirements` defaults to `[]`, which the URL path's metadata merge
      filters out as falsy, so structured data never overwrites the model's list with an empty one.
      One *existing* test did need amending: `test_structured_metadata_wins_over_the_models_reading`
      asserted `job_description` held exactly the joined requirements. That is the behaviour R1
      reverses, so the assertion moved to `requirements` and the body check became a positive one.

### Data model

- [x] T009 Create `backend/src/careerhq/domain/models/match.py` with `MatchAnalysis` and
      `MatchRequirement` per [data-model.md](./data-model.md). Enums for `status`, `band`, `kind`,
      `verdict`, `shortfall`. `cost` is `Numeric(12,6)` — **Decimal, never float**.
- [x] T010 Add `requirements` (`text[]`, nullable) and `current_match_analysis_id`
      (uuid, nullable, `ON DELETE SET NULL`) to `Application` in
      `backend/src/careerhq/domain/models/application.py`.
- [x] T011 Write the Alembic migration in `backend/alembic/versions/`: both tables, both columns,
      the FK, **the `CHECK ((verdict = 'unverified') = (evidence IS NULL))` constraint**, and the
      partial unique index `ON match_analyses (application_id) WHERE status = 'pending'`.
- [x] T012 [P] Test in `backend/tests/integration/test_match_schema.py`: inserting a
      `confirmed` requirement with `evidence = NULL` **raises at the database level**, and a
      `unverified` requirement with evidence also raises. Watch both fail before T011 — this is
      AI-008 enforced where it cannot be bypassed, and a constraint nobody has watched reject
      something is not a constraint. (Invariant I1.)
- [x] T013 [P] Test in `backend/tests/integration/test_match_schema.py`: a second `pending`
      analysis for the same application is rejected by the partial unique index. (Invariant I8,
      FR-007.)
- [x] T014 Run the migration against a real database and confirm both tables, the constraint and
      the index exist by querying `information_schema` — not by trusting the migration ran.
      **Verified** on the dev database: both tables, both nullable columns, both CHECK constraints
      with the expected definitions, and the partial unique index. Data survived — 1 user, 1
      profile, 5 applications — and **all 5 applications came out as legacy rows**
      (`requirements IS NULL`), which is R1's case at 100% of this database. They will read
      *nothing to score against yet* rather than being scored against a requirements list.

### The criteria module

- [x] T015 [P] Test in `backend/tests/unit/test_match_criteria.py`: `overall_score` equals
      `round(direct*0.4 + transferable*0.3 + adjacent*0.2 + impact*0.1)` for a table of known
      inputs. (Contract T3b.)
- [x] T016 [P] Test in `backend/tests/unit/test_match_criteria.py`: band thresholds map correctly
      at every boundary — 75, 74, 55, 54, 35, 34 — because off-by-one at a band edge is the
      failure a mid-range example never shows.
- [x] T017 [P] Test in `backend/tests/unit/test_match_criteria.py`: **a must-have at `gap` caps
      the band at `stretch`** even when the arithmetic yields 90. This rule is in neither source
      and exists because a weighted average hides a failed must-have cheerfully.
- [x] T018 Create `backend/src/careerhq/application/match_criteria.py` holding
      `CRITERIA_VERSION = "v1-weighted"`, the weights, the band thresholds and the must-have cap.
      One module, so a v2 is a new module rather than an edit to history.

### Found while running T049 — three defects the suite could not see

All three were invisible to a green test run, and all three now have tests.

1. **`run_analysis` returned immediately on every real call.** The guard read
   `analysis.status is not MatchStatus.PENDING`. `status` is a `String(16)` column, so a row
   loaded in the background task's own session is the plain string `'pending'` and the identity
   comparison never matched. Every analysis sat `pending` forever — nothing raised, nothing
   logged. Tests missed it because they pass the session that created the row, whose identity map
   still holds the enum member. The regression test uses a second session.
2. **Triggering a run 500'd on `MissingGreenlet`.** `_analysis_out` read
   `analysis.requirements` on a freshly added object, which is a lazy load, and async SQLAlchemy
   cannot do IO there. The existing test accepted `{202, 409}` and always got 409, so the
   fresh-create branch was never exercised. The collection is now initialised at construction.
3. **The shortfall rule was wrong, and the model was right.** A real completion failed validation
   on four `unverified` requirements with no shortfall. Demanding one asks the model to guess
   *why* a profile is silent — no skill, different words, or never written down — which is the
   invented absence the taxonomy exists to prevent, in the field added to make shortfalls
   actionable. Corrected in the schema, the prompt, and migration 0008.

**And one measurement that misses its target.** $0.034470 for a **12**-requirement posting,
against SC-004's $0.03. Output was 2,707 tokens — 78% of the cost, inside R8's predicted 57–86%
band but far above its 1,500-token estimate. R8 assumed three verdicts and no `importance` or
`shortfall` fields. A 38-requirement posting would be substantially worse. **T075 now has a real
number and SC-004 is not currently met** — recorded rather than adjusted.

### Found while doing Phase 2

Neither was in the plan; both are committed with the phase.

- **The circular foreign key must be named.** `applications.current_match_analysis_id` points at
  `match_analyses`, which points back — so the constraint needs `use_alter=True` to be added after
  both tables exist. An *unnamed* altered constraint cannot be dropped, which broke `drop_all` and
  therefore every test needing a clean schema.
- **`conftest.py` now drops the schema, not the tables.** `metadata.drop_all` emits its statements
  from the **metadata** rather than from what the database contains, so it tried to drop a
  constraint the existing test database predated and failed outright. `DROP SCHEMA public CASCADE`
  is also strictly stronger for the original purpose — it removes what `create_all` would not know
  to drop, including a column added by hand, which is exactly the scenario T003 guards against.

---

## Phase 2b: Found during implementation, not in the original plan

T007 has blast radius the plan did not account for. The Add Application form has a **single**
textarea named `job_description`, labelled *Requirements*, with the placeholder *"One requirement
per line…"* and a *"+ Add the requirements"* affordance. It was correct while `job_description`
held the joined requirements list. After T007 it holds the whole posting, so a job added from a
URL pre-fills that box with the entire advert.

These depend on the `requirements` column (T010) and the API returning it, so they run after
Phase 2's data model rather than beside T007.

- [x] T088 [P] Test in `frontend/src/components/__tests__/applications.test.tsx`: the Requirements
      field is populated from `requirements`, one per line — **not** from `job_description`. Watch
      it fail; today the binding is to the posting.
- [x] T089 In `frontend/src/components/applications/add-application.tsx`, bind the Requirements
      textarea to `requirements` and carry `job_description` through the form without displaying
      it in that box. **The posting must survive a form round-trip** — a person who opens the form
      on an extracted job and saves it must not silently discard the text match analysis scores
      against.
      **Verified against the real record**: a PATCH carrying a two-item requirements list left the
      1,890-character posting intact and updated only `requirements`. Before the fix the same edit
      would have replaced the posting with the list, and every later analysis would have scored
      against it while the prompt claimed to be reading a whole advert.

---

## Phase 3: User Story 1 — Learn whether a job is worth pursuing (Priority: P1) 🎯 MVP

**Goal**: a band appears against a job in the applications table a few seconds after saving,
without the person doing anything.

**Independent test**: add a job with a description, wait, and confirm a band appears in the
applications table with no further interaction.

### The completion schema — tests first

- [x] T019 [P] [US1] Test in `backend/tests/unit/test_match_schema.py`: a `MatchRequirementResult`
      with verdict `confirmed`, `partial`, `transferable` or `gap` and **no evidence** raises.
      Four cases, watched failing. (Contract T2, FR-008.)
- [x] T020 [P] [US1] Test in `backend/tests/unit/test_match_schema.py`: verdict `unverified`
      **with** evidence raises. The rule is an equivalence, not an implication. (Contract T3.)
- [x] T021 [P] [US1] Test in `backend/tests/unit/test_match_schema.py`: `shortfall` is `None` if
      and only if the verdict is `confirmed`.
- [x] T022 [P] [US1] Test in `backend/tests/unit/test_match_schema.py`: `direct`, `transferable`,
      `adjacent` and `impact` are each constrained to 0–100 and a value outside raises.
- [x] T023 [US1] Create `backend/src/careerhq/domain/schemas/match.py` — **`MatchJudgement` and
      `JudgedRequirement`**, renamed from the contract's `MatchAnalysis` /
      `MatchRequirementResult` because the ORM row is already `MatchAnalysis` and
      `analyze_match.py` imports both. Same reason the CV extraction schemas carry an `Extracted`
      prefix. Per [contracts/match-analysis.md](./contracts/match-analysis.md),
      with the grounding validator. **The model does not return `overall_score`**; it rates four
      dimensions and the application computes the total.

### The use case — tests first

- [x] T024 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`: a successful run
      writes the analysis `ready` with score, band, verdict, `criteria_version`, **and** model,
      token counts, cost and `is_fixture` — all in one transaction. (FR-017, Principle V.)
- [x] T025 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`: requirement rows
      are written with ordinal, kind, verdict, shortfall and evidence, in posting order.
- [x] T026 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`: a completion that
      fails validation leaves the analysis `failed` with an `error`, and **the application is
      still readable and editable**. (Contract T4, FR-026.)
- [x] T027 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`: the profile is
      byte-for-byte unchanged across a run. (Contract T7, FR-012, Invariant I6.)
- [x] T028 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`:
      `imported_match_rating` is unchanged by a run. (FR-013.)
- [x] T029 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`: an application
      with `requirements IS NULL` (a legacy row) is **never scored** — no analysis row is created.
      (Invariant I7, R1.)
- [x] T030 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`: an application
      with `requirements = []` is also not scored, and this is not an error. (FR-006.)
- [x] T031 [US1] Create `backend/src/careerhq/application/analyze_match.py` — the third
      `complete()` call site. `task="match_analysis"`, `schema=MatchAnalysis`. Renders the whole
      profile and the whole posting. **No loop, no tools, no reaction to its own output.**
- [x] T032 [US1] Write the prompt in `backend/src/careerhq/application/analyze_match.py`,
      honouring P1–P7 in
      [contracts/match-analysis.md](./contracts/match-analysis.md). P4 and P5 are the two that
      decide whether the output is honest: silence is `unverified`, never `gap`; and all five
      verdicts must be used rather than collapsing to a binary.
- [x] T033 [US1] In `backend/src/careerhq/application/analyze_match.py`, truncate an over-long
      posting **at the end, and record that it was truncated**.
      Never from the middle — requirements cluster in the second half. (P1.)

### Wiring it to saving a job

- [x] T034 [P] [US1] **Written in `backend/tests/integration/test_match_api.py`** rather than
      `test_match_analysis.py` — it exercises the route, so it belongs with the other endpoint
      tests. Saving an
      application creates the analysis row `pending` **in the same transaction**, and the response
      returns without waiting for the completion. (FR-004, FR-005.)
- [x] T035 [US1] Create the analysis row and dispatch the FastAPI background task from
      `backend/src/careerhq/application/record_application.py`.
- [x] T036 [US1] In `backend/src/careerhq/application/analyze_match.py`, ensure a background
      failure moves the row to `failed` rather than leaving it
      `pending` forever. An exception with nowhere to go is the known weakness of fire-and-forget;
      the `pending` row exists precisely so failure has somewhere to land.
- [x] T037 [P] [US1] Test in `backend/tests/integration/test_match_analysis.py`: an analysis that
      completes after its application is deleted is discarded without error.

### API

- [x] T038 [P] [US1] Test in `backend/tests/integration/test_match_api.py`: `GET
      /api/applications/{id}/match` returns the right `state` for each of the four cases —
      `running`, `ready`, `failed`, `nothing_to_score`. **The server decides the state**; a client
      inferring "no score means failed" is the conflation FR-022 forbids.
- [x] T039 [P] [US1] Test in `backend/tests/integration/test_match_api.py`: the endpoint returns
      404 — not 403 — for another user's application, so it cannot enumerate ids.
- [x] T040 [P] [US1] Test in `backend/tests/integration/test_match_api.py`: `cost` serialises as a
      **string**, never a float.
- [x] T041 [US1] Add `GET /api/applications/{id}/match` to
      `backend/src/careerhq/api/routes/applications.py` per
      [contracts/http-api.md](./contracts/http-api.md).
- [x] T042 [US1] Add the compact match summary (`state`, `band`, `overall_score`) to
      `GET /api/applications` in `backend/src/careerhq/api/routes/applications.py`, via **one join** on `current_match_analysis_id` — not one query
      per row.
- [x] T043 [P] [US1] Test in `backend/tests/integration/test_match_content.py`: every stored
      analysis and requirement column reaches the API response, read from the models' own columns.
      Slice 003's equivalent found a fourth dropped display bug on its first run — a fixture only
      contains what its author thought to include. (Contract T5, FR-029.)

### Frontend

- [x] T044 [P] [US1] Test in `frontend/src/components/__tests__/match.test.tsx`: the four states
      render distinctly, and *nothing to score* is **not** styled as an error.
- [x] T045 [US1] Create `frontend/src/components/applications/match-score.tsx` — the band for the
      table and the tab header. **Shows the band, never a bare percentage** (FR-001a).
- [x] T046 [US1] Add the Match column to
      `frontend/src/components/applications/applications-view.tsx`, sortable by the underlying
      score since four bands make a poor sort key.
- [x] T047 [P] [US1] Add the match types and fetchers to `frontend/src/lib/api.ts`.

### Verify against the real stack

- [x] T048 👁 **OBSERVE** [US1] Run [quickstart.md](./quickstart.md) step 1 **before spending
      anything**: confirm `model_for_task("match_analysis")` differs from the Opus fallback.
      **Confirmed on the running stack**: `anthropic/claude-sonnet-5` against a fallback of
      `anthropic/claude-opus-5`.
- [x] T049 👁 **OBSERVE** [US1] Run quickstart steps 2 and 3 against the running stack. Confirm
      the row reads `ready`, a band consistent with the score, `criteria_version = v1-weighted`,
      a real model, real token counts, a real cost and **`is_fixture = false`**. `is_fixture =
      true` means the fixture adapter answered and nothing was really scored.

      **Run against a real posting on 2026-08-20. Result: `ready`, score 56, band `stretch`,
      `v2-importance`, `claude-sonnet-5`, 3,700 in / 2,707 out, $0.034470, `is_fixture = false`.**
      Grounding check returned **0** violations. Verdict spread was confirmed 4, unverified 4,
      partial 3, transferable 1, gap 0 — no collapse to a binary (P5 holding).

      It found **three defects**, none of which the suite could see. See *Found while running
      T049* below.

**Checkpoint**: a band appears against a job without asking. US1 is shippable here.

---

## Phase 4: User Story 2 — See why it fits and what is missing (Priority: P2)

**Goal**: the reasoning behind the band, with every supported verdict quoting the profile.

**Independent test**: open a scored job and confirm each supported requirement shows profile text,
and missing must-haves are distinguishable from missing preferences.

- [ ] T050 [P] [US2] Test in `frontend/src/components/__tests__/match.test.tsx`: all **five**
      verdicts render distinctly, and `transferable` is visually distinct from `confirmed`.
      Showing adjacent experience as direct experience is the fabrication FR-011b forbids.
- [ ] T051 [P] [US2] Test in `frontend/src/components/__tests__/match.test.tsx`: `unverified` is
      visually distinct from `gap`. *Not mentioned* is not *does not have* (FR-011a).
- [ ] T052 [P] [US2] Test in `frontend/src/components/__tests__/match.test.tsx`: no verdict uses
      the failure treatment reserved by docs/09 §3, and every verdict is distinguishable **by
      glyph alone** so it survives greyscale and colour blindness (FR-023, docs/09 §7).
- [ ] T053 [P] [US2] Test in `frontend/src/components/__tests__/match.test.tsx`: the analysis is
      labelled AI-generated and shows its model and cost (FR-010).
- [ ] T054 [US2] Create `frontend/src/components/applications/match-tab.tsx`: the band and
      one-sentence verdict; **WHY IT FITS** with evidence; **WHAT'S MISSING** with must-haves
      first; and the requirement list as chips with a coverage count.
- [ ] T055 [US2] Make Match the **second** tab, after Details, in
      `frontend/src/components/applications/detail-tabs.tsx`.
- [ ] T056 [P] [US2] In `frontend/src/components/applications/match-tab.tsx`, show the
      wording/evidence/capability shortfall on each unmet requirement, so
      the list carries a next step rather than only a problem (FR-011c).
- [ ] T057 [P] [US2] Render the full posting behind a disclosure on the Details tab in
      `frontend/src/components/applications/detail-tabs.tsx`, with
      `requirements` continuing to show as bullets — so nothing changes on screen for a person who
      liked the old view.
- [ ] T058 [P] [US2] Handle the legacy row (`requirements === null`) in
      `frontend/src/components/applications/detail-tabs.tsx` and `match-tab.tsx`: *nothing to score against yet*, with an offer to re-add the job. **Not an error**,
      and not a score.
- [ ] T059 👁 **OBSERVE** [US2] Run quickstart step 4 and **read the evidence against your own
      profile**. Every supported requirement must quote text you recognise. A plausible sentence
      that is not in your profile is the failure this feature exists to prevent, and no automated
      check will catch it.
- [ ] T060 👁 **OBSERVE** [US2] Run quickstart step 4's verdict-spread query. If everything is
      `confirmed` or `gap` with nothing `partial`, `transferable` or `unverified`, the model has
      collapsed to a binary: the score is inflated and the gap list is manufactured. Every row
      would be individually valid, so **nothing in the schema catches this** — only the spread does.
- [ ] T061 👁 **OBSERVE** [US2] Run quickstart step 5 in **greyscale** and confirm all four states
      and all five verdicts remain distinguishable.

**Checkpoint**: the band is explained and the explanation is grounded.

---

## Phase 5: User Story 3 — Trust a score that has gone stale (Priority: P3)

**Goal**: a score computed before a profile edit says so, and can be re-run by hand.

**Independent test**: complete an analysis, edit the profile, reopen the job, confirm staleness is
surfaced and a re-run can be triggered.

- [ ] T062 [P] [US3] Test in `backend/tests/integration/test_match_api.py`: `stale` is true when
      the profile's `updated_at` is newer than the analysis's `created_at`, and false otherwise.
      **The server computes it**; the client only renders the offer.
- [ ] T063 [P] [US3] Test in `backend/tests/integration/test_match_analysis.py`: editing a profile
      triggers **no** re-scoring of any application (FR-025). Watch it fail against an
      implementation that helpfully rescores.
- [ ] T064 [P] [US3] Test in `backend/tests/integration/test_match_analysis.py`:
      `current_match_analysis_id` **never** points at a non-`ready` analysis, across a re-run that
      succeeds and one that fails. (Invariant I3, FR-015.)
- [ ] T065 [P] [US3] Test in `backend/tests/integration/test_match_analysis.py`: a failed re-run
      leaves the previous `ready` analysis displayed and the previous score intact. This is the
      difference between a re-run and a gamble.
- [ ] T066 [P] [US3] Test in `backend/tests/integration/test_match_analysis.py`: a successful
      re-run **retains** the previous analysis row. Append-only, because calibration is measured
      over history. (FR-014, Invariant I2.)
- [ ] T067 [P] [US3] Test in `backend/tests/integration/test_match_api.py`: `POST
      /api/applications/{id}/match` returns 409 when one is already in flight, and 422 when there
      is nothing to score. Not 202, and not 500.
- [ ] T068 [P] [US3] Test in `backend/tests/integration/test_match_analysis.py`: **no code path
      updates a `ready` analysis or deletes any analysis** — a source-tree scan, in the manner of
      slice 003's status-history test. An append-only table stays append-only only while nothing
      can write to it another way. (Invariant I2.)
- [ ] T069 [P] [US3] Test in `backend/tests/integration/test_match_analysis.py`: a stored `band`
      is not recomputed when band thresholds change. Re-banding history would rewrite what the
      person was told. (Invariant I5a.)
- [ ] T070 [US3] Add `POST /api/applications/{id}/match` to
      `backend/src/careerhq/api/routes/applications.py`. **No request body** — a model, criteria
      version or prompt from the client would put cost and behaviour under the browser's control.
- [ ] T071 [US3] Advance `current_match_analysis_id` only on `ready`, in the same transaction as
      the result, in `backend/src/careerhq/application/analyze_match.py`.
- [ ] T072 [P] [US3] Add the staleness notice and re-run control to
      `frontend/src/components/applications/match-tab.tsx`.
- [ ] T073 [P] [US3] Keep the previous band visible while a re-run is in flight, in
      `frontend/src/components/applications/match-score.tsx`. It must not blank to a spinner.
- [ ] T074 👁 **OBSERVE** [US3] Run quickstart step 7. Confirm the notice appears, **no other job
      was re-scored**, the previous band stays visible throughout the re-run, and the analysis
      count went up rather than the old row being replaced.

**Checkpoint**: all three user stories complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T075 **Re-measure cost against a real analysis.** R8's figures ($0.022–0.026) assumed three
      verdicts and no `shortfall` field; five verdicts with grounded gaps produce more output, and
      output is 57–86% of the bill. Update [research.md](./research.md) R8 with measured numbers
      and confirm SC-004 ($0.03/job) still holds. If it does not, say so rather than adjusting the
      criterion.
- [ ] T076 [P] Amend `docs/05_Implementation_Plan.md` §5.4. It defines slice 004 as the Resume
      Tailoring Agent; match analysis was pulled out ahead of it. **Decide the numbering** — either
      renumber the tailoring agent to 005 and cascade, or record that 004 split — and make the
      roadmap say the same thing as this spec.
- [ ] T077 [P] Update `docs/08_Technical_Spec.md` capability status markers for what is now built.
- [ ] T078 [P] Update `docs/07_Capabilities.md` if match analysis warrants its own entry rather
      than living under the Resume Optimizer.
- [ ] T079 [P] Update `CLAUDE.md` with what carries into the tailoring agent, and any gotcha this
      slice proved. The seam now has **three** call sites.
- [ ] T080 [P] Regenerate `HANDOFF.md` with `/handoff` — measured numbers, not copied.
- [ ] T081 [P] Confirm `infrastructure/ai/litellm_gateway.py` is still the only module importing
      `litellm`, and that `domain/` imports no framework code. (Seam obligation O5, Principle V.)
- [ ] T082 Confirm the scope guards held: **no agent loop, no embeddings, no vector retrieval, and
      no call site reacting to its own output.** T096 of slice 003 amended this guard to allow
      multiple call sites; three is still three independent calls.
- [ ] T083 Run every gate from the host and confirm green: `ruff format --check .`, `ruff check .`,
      `mypy src`, `pytest` at ≥80%; frontend `lint`, `typecheck`, `test`, `build`. **Gates run on
      the host, not in the container** — `backend/.dockerignore` excludes `tests/`, so
      `docker compose exec backend pytest` collects nothing and looks much like a pass.
- [ ] T084 👁 **OBSERVE** Walk [quickstart.md](./quickstart.md) end to end **as written** and
      correct it where it is wrong. Slice 001's T069, slice 002's T052 and slice 003's T095 each
      found real errors this way.
- [ ] T085 🔧 **MANUAL** Set `LLM_MODEL_MATCH_ANALYSIS` on the deployed backend service, **before**
      deploying — a variable that arrives after the build is too late for anything read at build
      time, and this one is read at runtime but still needs to exist before the first analysis runs.
- [ ] T086 👁 **OBSERVE** Run quickstart's deployed section: score a real job on the deployed
      system and confirm a real model, a real cost and `is_fixture = false`. `ai_provider: ok` is a
      construction check — a present-but-wrong key still reports healthy, so only this proves it.
- [ ] T087 👁 **OBSERVE** Confirm the deployed database holds at least one `ready` analysis with
      grounded requirement rows: `SELECT count(*) FROM match_requirements WHERE (verdict =
      'unverified') <> (evidence IS NULL);` must return **0**.

---

## Dependencies

```
Phase 1 Setup        ─── T001–T003
        │
Phase 2 Foundational ─── T004–T018   ← blocks everything; R1 correction lives here
        │
        ├─ Phase 3 US1 (P1) ─── T019–T049   🎯 MVP, independently shippable
        │        │
        │        ├─ Phase 4 US2 (P2) ─── T050–T061   needs an analysis to explain
        │        │
        │        └─ Phase 5 US3 (P3) ─── T062–T074   needs an analysis to go stale
        │
Phase 6 Polish       ─── T075–T087
```

**US2 and US3 are independent of each other** — both need US1, neither needs the other.

## Parallel execution

- **Phase 2 schema tests**: T012, T013 together after T011
- **Phase 2 criteria tests**: T015, T016, T017 together, before T018
- **US1 schema tests**: T019–T022 together, before T023
- **US1 use-case tests**: T024–T030 together, before T031
- **US1 API tests**: T038–T040 together, before T041
- **US2 component tests**: T050–T053 together, before T054
- **US3 tests**: T062–T069 together, before T070
- **Phase 6 docs**: T076–T080 together

## Implementation strategy

**MVP is Phase 1 + Phase 2 + Phase 3 (T001–T049).** That delivers the whole point of the feature:
a band appears against a job without being asked for. US2 explains it and US3 keeps it honest over
time, but neither is required for the capability to be real.

**Do not start Phase 3 before Phase 2 is complete.** The R1 correction changes what
`job_description` means; scoring built on the old meaning would be wrong in a way that produces
entirely normal-looking output.
