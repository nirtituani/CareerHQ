# Tasks: Resume Tailoring

**Feature**: `005-resume-tailoring` | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

**Format**: `[ID] [P?] [Story] Description with file path`

`[P]` = parallelisable (different files, no incomplete dependency). `[US1]`/`[US2]`/`[US3]` map to
the user stories in [spec.md](spec.md).

---

## Path Conventions

Backend `backend/src/careerhq/`, tests `backend/tests/`, migrations `backend/alembic/versions/`,
frontend `frontend/src/`. **Backend gates run on the host, never in the container** —
`backend/.dockerignore` excludes `tests/`, so an in-container pytest collects nothing and looks
like a pass.

**Tests first.** Write the test, run it, confirm it fails *for the right reason*, then implement.
`ImportError` because the module does not exist is a valid red; a test that passes before
implementation is a broken test.

---

## Phase 1: Setup

**Sequenced first because the dependency creates the hole the guard must cover** (research R2).
T001 and T002 land in the **same commit**.

- [X] T001 Add `langgraph>=1.2.11,<1.3` to `backend/pyproject.toml`, with a comment beside it recording that `langgraph-checkpoint-postgres` is deliberately **not** installed and why (research R1) — an absent dependency with no note is indistinguishable from an oversight
- [X] T002 Widen `forbidden` to `("litellm", "anthropic", "openai", "langchain_anthropic", "langchain_openai", "langchain_community")` in `backend/tests/unit/test_architecture.py::test_the_application_layer_imports_no_provider_sdk`, with a comment explaining that `langchain_core` is deliberately permitted because LangGraph's own types come from it
- [X] T003 **Watch T002 fail**: add `import anthropic` to a scratch module under `application/`, confirm the test names that file, remove it. A gate nobody has watched fail is not a gate
- [X] T004 [P] Add `llm_model_tailor_plan`, `llm_model_tailor_draft`, `llm_model_tailor_review`, `llm_model_tailor_revise`, `llm_model_tailor_revise_escalated` to `backend/src/careerhq/config.py` — Sonnet, Sonnet, **Opus**, Sonnet, **Opus**
- [X] T005 [P] Write `backend/tests/unit/test_task_model_config.py` asserting every `task=` literal in `application/` has a matching `llm_model_<task>` setting. Watch it fail by removing one entry — the fallback is Opus and the failure is silent
- [X] T006 Verify LangGraph's state-merge semantics against the **installed** version — confirm that a key without a reducer is overwritten and that `Annotated[list, operator.add]` appends — and record the finding in `research.md` R3. Do not build the graph on an assumption here (research R3)
- [X] T007 Run `docker compose build backend && docker compose up -d backend` and confirm the stack is healthy with the new dependency

**Checkpoint**: dependency in, guard widened and watched failing, model config complete.

---

## Phase 2: Foundational (blocks every user story)

- [X] T008 [P] Create `backend/src/careerhq/domain/models/tailoring.py` with `ResumeVersion` per [data-model.md](data-model.md) — including the **named** `use_alter` foreign key to `tailoring_runs` (an unnamed one cannot be dropped and breaks `drop_all` outright)
- [X] T009 [P] Add `TailoringRun` to `backend/src/careerhq/domain/models/tailoring.py` — `plan` and `guidelines_used` as `jsonb`, `cost` as `Numeric(12,6)` never float, `is_fixture`
- [X] T010 [P] Add `ResumeVersionItem` to `backend/src/careerhq/domain/models/tailoring.py` — `original_text` copied not referenced, `final_text` materialised, `decision` enum
- [X] T011 [P] Add `ReviewerFinding` to `backend/src/careerhq/domain/models/tailoring.py` — closed `kind` set, `quoted_text` required for `ungrounded` as a check constraint
- [X] T012 Add the `VersionStatus` enum (`draft`, `tailoring`, `reviewing`, `awaiting_approval`, `ready`) to `backend/src/careerhq/domain/models/tailoring.py`. **Do not add `exported` or `submitted`** — a state nothing can reach is a claim the code does not support
- [X] T013 Export the new models from `backend/src/careerhq/domain/models/__init__.py`
- [X] T014 Write `backend/alembic/versions/0010_resume_versions.py` — `resume_versions`, `tailoring_runs`, the named `use_alter` FK, and `uq_resume_versions_one_in_flight_per_application` as a **partial unique index** (FR-004 belongs in the schema; an application-level check can be raced by a double-click)
- [X] T015 Write `backend/alembic/versions/0011_version_items_and_findings.py` — `resume_version_items`, `reviewer_findings`, and the `ungrounded`-quotes-text check constraint
- [X] T016 Run `alembic upgrade head` then `alembic downgrade -2` and back, against a real database, to prove both migrations reverse
- [X] T017 Confirm `backend/tests/conftest.py` drops the schema before creating. `create_all` does not reconcile an existing table, so every schema-shaped assertion below would silently check a stale snapshot
- [X] T018 [P] Write `backend/tests/integration/test_tailoring_schema.py` asserting there is **no `failed` value** in the version status enum and **no `is_stale` column** anywhere. Watch both fail by adding them temporarily (data-model.md, *Two absences*)
- [X] T019 [P] Create `backend/src/careerhq/domain/schemas/tailoring.py` — `TailoringPlan`, `TailoredDraft`, `ReviewResult` Pydantic schemas. **Draft and Revise return item ids with changed text, never the whole resume** (research R5: output is 57–86% of cost and the slow half of a completion)
- [X] T020 Add a validator to `ReviewResult` requiring `quoted_text` on every `ungrounded` finding, and **forbidding** an item reference on `uncovered` findings (research R9 — a field the model has no honest basis to fill is what broke slice 004's `unverified`)
- [X] T021 [P] Write `backend/tests/unit/test_tailoring_schema_validation.py` covering both rules in T020
- [X] T022 Create `backend/src/careerhq/application/guidelines.py` — the `GuidelineSource` protocol and `Guideline` dataclass exactly as [contracts/tailoring-workflow.md](contracts/tailoring-workflow.md) O6 specifies. **No `top_k`, no scores, no embedding parameters**
- [X] T023 Implement `StaticGuidelines` in `backend/src/careerhq/application/guidelines.py` — 10–15 rules, each carrying a `source` (research R6)
- [X] T024 Create `backend/src/careerhq/application/finalisation_rules.py` with `FINALISATION_RULES_VERSION = "v1-severity"`, the severity table, and the confidence threshold as a named constant with its uncalibrated status stated in the docstring — modelled on `match_criteria.py`, where changing a constant is a **new version, never an edit**
- [X] T025 Write `backend/tests/unit/test_finalisation_rules.py` — an `ungrounded` finding discards its item's proposal and restores `original_text`; `overstated` and `uncovered` survive untouched. Pure functions, no database, no provider
- [X] T026 **Amended during implementation**: built as a test double at `backend/tests/support/scripted_seam.py`, *not* in `infrastructure/ai/fixture_gateway.py`. That adapter is production code selected by `AI_PROVIDER=fixture` for demos; scripting a sequence of differing answers is purely a test concern, and putting the API there would ship a mechanism only tests use. Returns a **sequence per task name**, one entry per call, and raises rather than repeating its last answer when the script runs out (research R10)
- [X] T027 Write `backend/tests/unit/test_scripted_seam.py` proving successive calls to one task name return successive results, that exhausting the script raises rather than repeating (a repeated last answer would make an unbounded loop look convergent), and that a scripted answer still faces the real schema

**Checkpoint**: schema, schemas, rules and test infrastructure exist. No workflow yet.

---

## Phase 3: User Story 1 — Turn a job into a tailored resume I approved (P1) 🎯 MVP

**Goal**: request tailoring on a scored job, get a draft, accept or reject each proposal, save a
version.

**Independent test**: open a scored job, request tailoring, wait, accept everything, confirm — a
saved version exists that differs from the master in ways shown before agreeing to them.

### Tests for User Story 1

- [ ] T028 [P] [US1] Write `backend/tests/integration/test_tailoring_preconditions.py` — 422 with no completed analysis, 422 with a stale one, and the two messages differing (FR-001)
- [ ] T029 [P] [US1] Write `backend/tests/integration/test_tailoring_workflow.py::test_clears_review_first_time` — three calls, one usage record each, no revision
- [ ] T030 [P] [US1] Add `test_one_revision_then_clears` — five calls; the second draft is what persists
- [ ] T031 [P] [US1] Add `test_full_budget_exhausted` — seven calls, the second revision uses `tailor_revise_escalated`, finalisation still runs (FR-013)
- [ ] T031a [P] [US1] Add `test_invalid_model_output_fails_the_run` to `backend/tests/integration/test_tailoring_workflow.py` — drive **each** node (plan, draft, review, revise) with a fixture returning output that fails schema validation, and assert for every one: the run records `status='failed'` with a `failure_reason`, the version returns to `draft` and is readable, and no partial items or findings were written (FR-006, FR-037)
- [ ] T031b [P] [US1] Add `test_a_failed_run_can_be_retried` — after a failed run, a second `POST .../tailor` is accepted rather than 409'd, because the partial index only holds for `tailoring` and `reviewing` (FR-007)
- [ ] T032 [P] [US1] Add `test_usage_accumulates` asserting **seven** usage records on the full path. This is the R3 failure: without an append reducer only the last survives and nothing raises
- [ ] T033 [P] [US1] Add `test_ungrounded_claim_never_persisted` — the proposal is absent from every row, `original_text` stands, the finding persists (FR-018, FR-046). **Watch it fail** before trusting it
- [ ] T033a [P] [US1] Add `test_guidelines_used_are_persisted` — after a run, `tailoring_runs.guidelines_used` holds every guideline the nodes consumed **and each one's `source`**. Without this FR-016 is a column nobody fills, and slice 007's retrieval-quality metric has nothing to measure (FR-016)
- [ ] T033b [P] [US1] Add `test_rejecting_every_proposal_yields_the_master` — reject every item, approve, and assert the saved version's content equals the master resume exactly, with no error and status `ready` (SC-005). The cheapest end-to-end test of the approval path, and quickstart §2 already promises it exists
- [ ] T034 [P] [US1] Write `backend/tests/integration/test_tailoring_concurrency.py` — a second request while one is in flight returns 409 (FR-004), asserted against the partial index rather than the code path
- [ ] T035 [P] [US1] Write `backend/tests/integration/test_owner_data_untouched.py` — snapshot **every owner-owned table** (the match analysis, and the profile's contact, titles, summaries, experiences, bullets, skills, projects, education, certifications, languages, military service, volunteering) before a run and assert byte-identical after, for a run that **succeeds**, one that **fails**, and one that is **abandoned and reaped** (FR-011, FR-021). Constitution Principle II is non-negotiable and this is the only thing that checks it
- [ ] T036 [P] [US1] Write `backend/tests/integration/test_version_status_transitions.py` exercising every transition **against a re-read record** (FR-047) — the `is`-versus-`==` bug that left every slice-004 analysis stuck on `pending` under a green suite
- [ ] T036a [P] [US1] Write `backend/tests/integration/test_version_immutability.py` — create a version, then mutate the profile (edit a bullet, add an experience, remove a skill) and its source master, then **reload the version in a fresh session** and assert every item's `original_text`, `proposed_text` and `final_text` are unchanged and `source_profile_updated_at` still holds the creation-time value (FR-030, FR-031, SC-007). Constitution Principle IV — *profile updates MUST NOT alter existing Resume Versions* — and `data-model.md` copies text rather than referencing it precisely so this holds. The fresh session matters for the same reason it does in T036

### Implementation for User Story 1

- [ ] T037 [US1] Create `backend/src/careerhq/application/agents/tailoring/state.py` — the frozen `TailoringState` dataclass with **append reducers on `usage` and `findings`** (research R3, verified in T006)
- [ ] T038 [US1] Create `backend/src/careerhq/application/agents/tailoring/prompts.py` with the plan prompt — consumes the match analysis, produces emphasis, de-emphasis, and the gaps that must not be misrepresented (FR-009, FR-010)
- [ ] T039 [US1] Add the draft prompt to `prompts.py` — works **from the plan**, never deriving its own strategy (FR-005 of the design's commitments); returns item ids with changed text only
- [ ] T040 [US1] Add the review prompt to `prompts.py` — grounding, overstatement, coverage, and a confidence score, with the closed `kind` set stated explicitly (FR-012)
- [ ] T041 [US1] Add the revise prompt to `prompts.py`, taking the findings as input
- [ ] T042 [US1] Create `backend/src/careerhq/application/agents/tailoring/graph.py` — four nodes, each state-in/state-out, calling `complete()` and the guideline port and nothing else (contract O2). **No node holds a session or writes**
- [ ] T043 [US1] Add the conditional edge in `graph.py` — bounded at two revisions, escalating by **task name** on the second (`tailor_revise_escalated`), never by a branch on model (contract O4, O7)
- [ ] T044 [US1] Create `backend/src/careerhq/application/tailor_resume.py` — `create_pending_version` creating version and run **synchronously in one transaction** before the background work starts (FR-003)
- [ ] T045 [US1] Add the precondition check to `tailor_resume.py`, reusing the existing read-time staleness comparison rather than adding a flag (FR-001, data-model.md)
- [ ] T046 [US1] Add `run_tailoring` to `tailor_resume.py` — invokes the graph, applies `finalisation_rules`, and writes version, items, findings, usage **and `guidelines_used` with each guideline's source** (FR-016) **in one transaction** (contract O3). Assign collections at construction to avoid `MissingGreenlet` on serialisation
- [ ] T047 [US1] Add the abandoned-run reaper to `tailor_resume.py` with a **named threshold constant** and the reasoning beside it — it must not release a run legitimately in its second revision (research R7)
- [ ] T048 [P] [US1] Write `backend/tests/integration/test_tailoring_reaper.py` covering both sides of that threshold
- [ ] T049 [US1] Create `backend/src/careerhq/api/routes/tailoring.py` with `POST /api/applications/{id}/tailor` per [contracts/http-api.md](contracts/http-api.md) — 202, 409, 422 distinguishing both causes, 404
- [ ] T050 [US1] Add `GET /api/versions/{id}` returning the version, items and nested findings; empty items while `tailoring` or `reviewing`
- [ ] T051 [US1] Add `PATCH /api/versions/{id}/items/{item_id}` — accept, reject, edit; reject restores `original_text` and **triggers no AI work** (FR-026)
- [ ] T052 [US1] Add `POST /api/versions/{id}/approve` — every still-`pending` item counts as accepted (FR-025, the import-review precedent), transition to `ready`, **start nothing** (FR-028)
- [ ] T053 [US1] Add `GET /api/applications/{id}/versions` for the list view
- [ ] T053a [US1] Add `GET /api/versions/{id}/run` per [contracts/http-api.md](contracts/http-api.md) — the audit record: plan, attempts, guidelines used with sources, per-task models, tokens, cost, finalisation rules version and timings (FR-034). Its own endpoint rather than a field on the version, because it is inspection rather than the document, and slice 007 reads it programmatically
- [ ] T054 [US1] Register the router in `backend/src/careerhq/api/routes/__init__.py` and confirm the existing route-enumeration test now covers all **six** as authenticated
- [ ] T055 [P] [US1] Write `backend/tests/integration/test_tailoring_ownership.py` — no route accepts a client-supplied owner, and another user's version is 404 not 403
- [ ] T056 [US1] Add the five API calls to `frontend/src/lib/api.ts`
- [ ] T057 [US1] Create `frontend/src/components/applications/tailor-diff-item.tsx` — original, proposed, decision controls. **One component for every source kind**; a second render path costs an affordance every time
- [ ] T058 [US1] Create `frontend/src/components/applications/tailor-tab.tsx` — the five states rendered distinctly (FR-039), progress while running, the diff when awaiting approval
- [ ] T059 [US1] Add the Tailor tab to `frontend/src/components/applications/detail-tabs.tsx`, ordered by the work rather than by build order
- [ ] T060 [US1] Show the AI-generated marker, model name, cost and `is_fixture` on the version (FR-022)
- [ ] T061 [P] [US1] Write `frontend/src/components/__tests__/tailor.test.tsx` covering the five states and the accept/reject controls
- [ ] T062 [US1] Run `docker compose build backend && docker compose up -d backend`, then the full flow in a **browser on `localhost`** — not `127.0.0.1`, which 403s its own chunks in dev with no console error
- [ ] T063 [US1] Confirm every stored value reaches the screen, reading the models' own columns — the check that found four display bugs in slice 003 that the suite could not

**Checkpoint 🎯 MVP**: a job becomes a tailored, approved resume version.

---

## Phase 4: User Story 2 — See what the Reviewer thought, beside the thing it thought about (P2)

**Goal**: each proposal carries the Reviewer's finding about *that* proposal; the draft carries a
confidence score.

**Independent test**: run tailoring where evidence for one requirement is thin; the finding appears
against that item, and the confidence score is visible and not confusable with the match score.

### Tests for User Story 2

- [ ] T064 [P] [US2] Add `test_findings_attach_to_their_item` to `backend/tests/integration/test_tailoring_workflow.py` — item-level findings nest under items, `uncovered` findings appear only at draft level (FR-042)
- [ ] T065 [P] [US2] Add `test_clean_draft_still_reports_confidence` — a run with no findings still returns a score, so a clean result is visibly a result
- [ ] T066 [P] [US2] Write `frontend/src/components/__tests__/tailor-findings.test.tsx` — a finding renders against its item and never as a banner

### Implementation for User Story 2

- [ ] T067 [US2] Persist `confidence_score` on the version in `tailor_resume.py` and expose it in `GET /api/versions/{id}`
- [ ] T068 [US2] Render per-item findings in `frontend/src/components/applications/tailor-diff-item.tsx`, visually subordinate to the proposal they concern
- [ ] T069 [US2] Render draft-level `uncovered` findings in `tailor-tab.tsx`, separately from item findings
- [ ] T070 [US2] Render the confidence score in `tailor-tab.tsx` **labelled distinctly from the match score** (FR-043) — different questions, different units, never one number
- [ ] T071 [P] [US2] Extend `frontend/src/components/__tests__/tokens.test.ts` coverage to the new components — an undefined CSS custom property fails silently and differently per property, and `fill:` renders black on a dark ground
- [ ] T072 [US2] If a progress reveal is animated, build it so **removing the animation lands on the finished state** — `prefers-reduced-motion` collapses animations to 0.01ms, so a base of "empty" plus an animation that fills it shows zero to everyone who reduces motion
- [ ] T073 [US2] In a browser: confirm a person can tell *the agent is reviewing* from *it is your turn* (FR-040) — the state this slice added; if it looks like the one before it, the amendment bought nothing

**Checkpoint**: approval is a judgement rather than a formality.

---

## Phase 5: User Story 3 — Fix the wording myself (P3)

**Goal**: a rejected proposal's restored text can be replaced by hand, and stays identifiable as
the owner's.

**Independent test**: reject a proposal, edit the restored text, confirm, reopen — the text is
there and marked owner-authored.

### Tests for User Story 3

- [ ] T074 [P] [US3] Add `test_edited_item_is_distinguishable` to `backend/tests/integration/test_tailoring_workflow.py` — `decision = 'edited'` distinguishes owner text from both proposal and original (FR-027)
- [ ] T075 [P] [US3] Add a 422 case for `decision = 'edited'` with absent or empty `text`

### Implementation for User Story 3

- [ ] T076 [US3] Handle `edited` in `PATCH /api/versions/{id}/items/{item_id}` — `final_text` becomes the supplied text
- [ ] T077 [US3] Add a plain text field to `tailor-diff-item.tsx`, revealed on rejection. **A text field, not an editor** — a WYSIWYG resume editor is an explicit project non-goal
- [ ] T078 [US3] Mark owner-edited items in the interface, mirroring how profile corrections show `user_corrected`
- [ ] T079 [P] [US3] Extend `frontend/src/components/__tests__/tailor.test.tsx` for the edit path

**Checkpoint**: all three stories complete.

---

## Phase 6: Polish, measurement and deployment

- [ ] T080 Amend `docs/03_Domain_Model.md` §10.1 to add `Awaiting approval` between `Reviewing` and `Ready` (research R8). A lifecycle described in two places will disagree
- [ ] T081 Update the `ports.py` docstring, which says self-critique "belongs in the agent runtime, not here" and names it slice 004 — the runtime now exists and is slice 005
- [ ] T082 Correct `CLAUDE.md`, which describes the no-loop boundary as "the line the guard actually protects". Nothing executable ever asserted it; the import-graph guard is the real one
- [ ] T083 [P] Run the full backend gates on the host: `pytest` at ≥80%, `ruff format --check`, `ruff check`, `mypy src`
- [ ] T084 [P] Run the full frontend gates: `lint`, `typecheck`, `test`, `build`
- [ ] T085 Measure a real run on a real posting — both the first-pass-clear and full-revision-budget paths — and record tokens, cost and elapsed time in `research.md` R5, the way slice 004's R8 recorded its own
- [ ] T086 Compare the measurement against SC-006 ($0.30) and SC-001 (90s / 3min). **If missed, mark missed in `spec.md`** rather than adjusting the target — slice 004 did exactly this with SC-004
- [ ] T087 Read a tailored resume as a person and ask whether it claims anything the owner did not do. FR-017 has no test that answers this
- [ ] T088 Deploy and verify on the live system: a real run with `is_fixture = false`, a real model name, real token counts, a real cost
- [ ] T089 Query the deployed database with the mandatory `PGHOST=localhost PGPORT=5432` override — the running container carries a stale host from a deleted proxy, and Railway recycles those ports, so the default address now serves another tenant's database
- [ ] T090 Run `/security-review` on the branch diff — four new routes, two migrations, and a new owner-facing surface
- [ ] T091 Update `HANDOFF.md` and `docs/08_Technical_Spec.md` §6.1 status markers

---

## Dependencies

```
Phase 1 (T001–T007)  ── T001+T002 same commit; T003 watches T002 fail
        ↓
Phase 2 (T008–T027)  ── T026 (fixture sequences) blocks T031/T032/T033
        ↓
Phase 3 / US1 (T028–T063)  🎯 MVP — independently shippable
        ↓
Phase 4 / US2 (T064–T073)  needs US1's version and diff surface
        ↓
Phase 5 / US3 (T074–T079)  needs US1's PATCH route
        ↓
Phase 6 (T080–T091)
```

**US2 and US3 are independent of each other** and may be built in either order once US1 lands.

**T035 and T036a are the two invariant tests**, added after `/speckit-analyze` found them missing.
Both correspond to constitution MUSTs that no task verified — Principle II (owner data is not
modified) and Principle IV (a version does not change when the profile does). The pattern is worth
noting: the gaps were both *invariants*, not features. Feature work generates obvious tasks;
"nothing changed" does not, which is exactly why slice 003's absence tests had to be written
deliberately.

**T026 is the hidden critical path.** Until the fixture gateway returns sequences, T031, T032 and
T033 cannot be written — and those cover the revision bound, the usage accumulation, and the
grounding discard. An untestable path is an untested path, which is how slice 004 shipped nine
defects under a green suite.

## Parallel opportunities

- **Phase 2**: T008–T011 are one file and must be sequential, but T018, T019, T021 and T027 run in
  parallel with each other and with the migration work
- **Phase 3 tests**: T028–T036a are fifteen independent tests across six files, all parallel
- **Phase 3 frontend**: T057 and T061 can proceed against the contract before the backend lands
- **Phase 6**: T083 and T084 in parallel; T080–T082 are three independent documents

## Implementation strategy

**Ship US1 alone if the budget tightens.** It delivers a tailored, approved resume — the flagship's
whole claim — and both later stories refine confidence rather than capability.

**The order within US1 is not negotiable**: tests T028–T036a before implementation T037–T063. Slice
004 is the case study for why. Nine defects shipped under a green suite, and every one was found by
running the thing rather than by testing it — so the tests exist to make the *mechanisms* provable,
and T062, T063, T073 and T087 exist because tests never found a display bug in this project.
