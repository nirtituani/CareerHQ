# Tasks: Role-Aware Company Research

**Input**: Design documents from `/specs/010-role-aware-research/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: included and ordered first — "Tests first" is project law (CLAUDE.md), and every new
gate must be watched failing (testing rule 1). Where a task says **drill**, that means: break
the implementation deliberately, confirm the test names the exact violation, restore.

**Organization**: by user story, after a foundational phase that reshapes storage, defines the
seam, and extracts the legacy renderer (both US3 and US4 depend on it — see Dependencies).
US1 alone is a shippable MVP.

**Revision note (2026-08-31)**: updated after the first `/speckit-analyze` pass — I1 (legacy
renderer moved to Foundational as T012), C1 (new T037), C2 (folded into T011), C3 (folded into
T018), C4 (truncation specified in T013/T015 and data-model.md). Task IDs renumbered.

## Format: `[ID] [P?] [Story] Description`

## Path Conventions

Web app: `backend/src/careerhq/`, `backend/tests/`, `frontend/src/`. All paths below are real.

---

## Phase 1: Setup

- [X] T001 Add `research_provider`, `research_fallback_enabled`, `research_provider_timeout_seconds`, `research_posting_max_chars` settings with defaults per data-model.md §Configuration in `backend/src/careerhq/config.py`, and mirror them in `.env.example` (no secrets; `tavily_api_key` already exists)
- [X] T002 [P] Define `ResearchProviderUnavailable` and `ResearchProviderRejected` exception types (carrying an optional cost basis, per contract invariant 4) in `backend/src/careerhq/application/ports.py`

---

## Phase 2: Foundational (blocking all stories)

**Purpose**: the storage reshape, the seam, and the legacy renderer extraction. Nothing
user-visible yet.

- [X] T003 Write the migration drill test: inserting a row into `role_research_snapshots` then running migration 0020 must fail with the emptiness-guard message; on an empty table it must produce `application_research_snapshots` and the rewritten `research_sources` constraint — in `backend/tests/integration/test_migration_0020.py` (red: migration file does not exist yet)
- [X] T004 Write model tests for `ApplicationResearchSnapshot`: insert-only semantics, status transitions running→succeeded/failed only, `cost_basis` check constraint, one-running-per-application partial unique — extend `backend/tests/unit/test_research_models.py` (red: model not reshaped yet)
- [X] T005 Write schema tests for `ApplicationResearch` (`app-v1`): all fields required, `how_identified` non-empty, list bounds 1..12, and a JSON Schema assertion that **every property carries a `description`** (the provider 400s otherwise — research.md D1) in `backend/tests/unit/test_application_research_schema.py`
- [X] T006 Implement migration `backend/alembic/versions/0020_application_research.py` per research.md D2: emptiness guard first; rename table; drop `company_research_snapshot_id`; rename `findings`→`sections`; add `produced_by`, `cost_basis` (+ check constraint); carry over constraints/indexes under new names; rename `research_sources.role_snapshot_id`→`application_snapshot_id` and hand-rewrite `ck_research_sources_exactly_one_snapshot` (Alembic does not diff check constraints). **Drill T003 before ticking**
- [X] T007 Reshape `RoleResearchSnapshot`→`ApplicationResearchSnapshot` (and `ResearchSource.application_snapshot_id`) in `backend/src/careerhq/domain/models/research.py`, rewriting the class docstring to this slice's contract; run T004 green
- [X] T008 [P] Add `ApplicationResearch` (+ `CompanyIdentification`) to `backend/src/careerhq/domain/schemas/research.py` with conditional requirements expressed in `Field(description=...)` (validators do not serialise — 005 lesson); run T005 green
- [X] T009 Write port-contract tests for `ResearchOutcome` invariants 1–3 (exactly one of usage/cost_estimate; shape↔prompt_version pairing; posting_text optional) in `backend/tests/unit/test_research_provider_port.py` (red: port does not exist)
- [X] T010 Add `ResearchProvider` protocol, `ResearchOutcome`, `ProviderSource` to `backend/src/careerhq/application/ports.py` per contracts/research-provider-seam.md; run T009 green
- [X] T011 Re-scope persistence: application-scoped `create_pending_application_research` / `complete_application_research` / `fail_research` / `current_application_research` / `reusable_application_research` (reuse per application, D6; `cost_basis` derived from which cost the outcome carried; failure records its basis) in `backend/src/careerhq/application/research_persistence.py`, with tests extended in `backend/tests/integration/test_research_persistence.py` — tests first, including: failure never evicts the last success; a failed run's cost basis is non-null (SC-006); and **abandoned-run behaviour** — a `running` row older than `research_max_duration_seconds` stops blocking new runs and stops being reported as in-flight, while the row itself is never rewritten by the reader (FR-016)
- [X] T012 [P] Extract the current tiered renderer **verbatim** from `frontend/src/components/applications/company-tab.tsx` into `frontend/src/components/applications/research-legacy.tsx`, with a rendering test on a real 008-shaped fixture in `frontend/src/components/applications/__tests__/research-legacy.test.tsx`. Foundational because both US3 (fallback runs emit the tiered shape) and US4 (legacy snapshots) render through it; a second render path costs an affordance every time — extract, don't rewrite (testing rule 9)

**Checkpoint**: suite green; schema reshaped; seam defined; legacy renderer standalone; no route
changed yet.

---

## Phase 3: User Story 1 — Research for this application (P1) 🎯 MVP

**Goal**: provider-produced, role-aware, sections-first research for an application with a JD.

**Independent test**: quickstart.md §2 on the Pango fixture — correct entity, seven sections, no
tier labels, reuse free.

- [X] T013 [P] [US1] Write Tavily adapter tests against recorded POC-shaped responses (success; content-as-string and content-as-object; schema-violating output → `ResearchProviderRejected`; timeout/transport → `ResearchProviderUnavailable`; request body carries `output_schema` with descriptions, `model="mini"`, untrusted-data framing and the three D4 instruction clauses; **posting text longer than `research_posting_max_chars` is truncated from the end and the truncation recorded** as `{"posting_truncated": true, "posting_chars_sent": N}` in the outcome's `model_config_used` contribution — assert on the request the double captured, not on constants) in `backend/tests/unit/test_tavily_research.py`
- [X] T014 [P] [US1] Write use-case tests with a scripted provider double: assembles input from the owned application only; calls the port once; persists snapshot + sources; provider sources carry no excerpts; `produced_by`/`prompt_version` stamped; refused when a run is in flight — in `backend/tests/unit/test_research_application.py`
- [X] T015 [US1] Implement `backend/src/careerhq/infrastructure/research/tavily_research.py` per the adapter behaviour contract (httpx, config timeout, posting truncation per T013's rule, `cost_estimate` at documented rate with raw basis into `model_config_used`; never polls the usage endpoint); run T013 green
- [X] T016 [US1] Implement `backend/src/careerhq/application/research_application.py`: assemble (company, domain, role title, posting via `scoreable_posting()`), call the port, validate outcome pairing, persist; run T014 green
- [X] T017 [US1] Rewire `backend/src/careerhq/api/routes/research.py`: application-scoped POST/GET per contracts/api-research.md (reuse answer, 409 in-flight, response `shape`/`produced_by`/`cost_basis`/`freshness`), provider selected next to `get_web_search` by `research_provider`; update `backend/tests/integration/test_research_api.py` and `test_research_reuse.py` to the new scope — tests first; re-assert the OpenAPI route count in the enumeration test
- [X] T018 [P] [US1] Write frontend tests for the sections view: seven sections render from an `app-v1` payload; **no fact/interpretation/inference text anywhere in the rendered output** (assert against the full render target, mindful of portals — testing rule 3); entity identification visible; provider sources render attributed without verified-quote affordances; **the three freshness states render distinctly** — `fresh` unadorned, `aging` shows the research's age, `stale` flags it and suggests refresh (FR-013) — in `frontend/src/components/applications/__tests__/research-sections.test.tsx`
- [X] T019 [US1] Implement `frontend/src/components/applications/research-sections.tsx` (sections-first, quiet provenance, freshness states per T018) and dispatch on `shape` in `frontend/src/components/applications/company-tab.tsx`; update types in `frontend/src/lib/api.ts`; run T018 green; keep polling keyed on application id
- [X] T020 [US1] Verify in Docker + browser per quickstart.md §2 (scratch user, Pango fixture JD; one billable provider run) — record actual latency and cost basis here: recorded: 22 s wall (after two provider-contract fixes the first run surfaced — schema dialect and pending-envelope polling, each captured as a unit test); snapshot recorded $0.456 `estimate`; usage API later attributed ≈14 credits (≈$0.11) per research run, so the estimate overstates ~4× in the conservative direction. Verified in the browser: identification leads, seven sections, no tier vocabulary, role content engages the JD.
- [X] T021 [US1] Drill the SC-008 gate: temporarily render a tier badge in the sections view, confirm T018 fails naming it, restore

**Checkpoint**: US1 shippable. Applications with a JD get role-aware research; everything else
unchanged.

---

## Phase 4: User Story 2 — Research without a posting (P2)

**Goal**: no-posting applications get honest company-only research through the same flow.

**Independent test**: quickstart.md §3.

- [X] T022 [P] [US2] Write tests: with `scoreable_posting → None`, the use case passes `role_title=None, posting_text=None`; the adapter's input omits role framing and asks for company-only research; the validated result's role sections explain the absence (validator accepts thin-but-explained, rejects silent-empty) — extend `backend/tests/unit/test_research_application.py` and `test_tavily_research.py`
- [X] T023 [US2] Implement the no-posting branch as parameter plumbing (no second pipeline — D7) across `research_application.py` and `tavily_research.py`; run T022 green
- [X] T024 [P] [US2] Frontend: role sections render the explanation state without pretending content; test in `frontend/src/components/applications/__tests__/research-sections.test.tsx`
- [X] T025 [US2] Verify in Docker + browser per quickstart.md §3 (one billable provider run), including the paste-JD-then-refresh path; record actuals: recorded: 51 s; company-only research proceeded, role sections explained the missing posting. Notable: with no posting AND no domain, a collided name resolved to the wrong same-named company — the accepted degraded mode, made visible by the identification tripwire (FR-007 working as designed). Paste-JD-then-refresh path exercised via the JD-bearing sibling application.

---

## Phase 5: User Story 3 — The provider is down (P3)

**Goal**: configured fallback or honest failure; never silent degrade.

**Independent test**: quickstart.md §4. Depends on T012 (the fallback's tiered output renders
through the extracted legacy view).

- [X] T026 [P] [US3] Write builtin-adapter tests: wraps `research_company()` unchanged; returns `v2-dense`/`builtin`/exact usage/verified excerpts; and fallback-decision tests: provider `Unavailable` + fallback on → builtin outcome persisted as `produced_by="builtin"`; fallback off → failed run with reason class, previous success still current — in `backend/tests/unit/test_builtin_provider.py` and extended `test_research_application.py`
- [X] T027 [US3] Implement `backend/src/careerhq/infrastructure/research/builtin_provider.py` and the fallback decision in the use case per D8; run T026 green
- [X] T028 [US3] API + frontend: `failure_reason` is a class name only (detail to operator log — assert on the record the route emitted, filtered by logger name; testing rule 11); tiered fallback payload renders via the T012 legacy view with `produced_by` quietly shown; extend `backend/tests/integration/test_research_api.py` and frontend tests
- [X] T029 [US3] Verify in Docker per quickstart.md §4 (bad key → fallback on, then off; env change needs `up -d`, not restart); record behaviour: recorded: a broken key downs BOTH paths (one key serves provider and fallback), producing an honest failure — `ResearchProviderUnavailable`, estimate basis, previous success still served. The fallback-succeeds path was exercised in Docker by a real provider 400 earlier the same day (builtin ran: $0.032 Gemini, tiered shape, verified excerpts). `RESEARCH_FALLBACK_ENABLED=false` verified through the environment; `.env` restored byte-identical.

---

## Phase 6: User Story 4 — Old research still readable (P3)

**Goal**: 008-era snapshots coexist, byte-identical, still rendered.

**Independent test**: quickstart.md §5. Depends on T012 (legacy view already extracted).

- [X] T030 [P] [US4] Write read-path tests: legacy company snapshot served as `shape="tiered"`, `produced_by="legacy-company"` only when the application has no application snapshot; new snapshot takes precedence once present; stored legacy `sections` untouched (hash-compare before/after a new run) — in `backend/tests/integration/test_research_legacy_coexistence.py`
- [X] T031 [US4] Implement the legacy leg of `current_application_research` in `research_persistence.py`; run T030 green
- [X] T032 [US4] Verify in Docker + browser per quickstart.md §5 with a seeded 008-shape row (rendered via the T012 legacy view); record the before/after hash check: recorded: md5(sections::text) `638ec1e12755a2670d197e1d6b5f1509` identical before and after a new run; legacy GET served `tiered`/`legacy-company`/`recorded` and rendered in the browser with tiers, quotes and failed-source rows intact.

---

## Phase 7: Polish & Cross-Cutting

- [X] T033 [P] Extend the architecture gate: `application/` imports no `httpx` and no provider SDK; the Tavily Research adapter is imported only from `api/routes/research.py` — extend `backend/tests/unit/test_architecture.py` and **drill it** (add a forbidden import, watch it fail, remove)
- [X] T034 [P] SC-007 sentinel test: seed a scratch profile containing a sentinel string, run the use case with a capturing double, assert the sentinel appears nowhere in any assembled provider input — in `backend/tests/integration/test_research_no_profile_leak.py`
- [X] T035 [P] Cost-basis reporting test: estimates and recorded costs never summed unlabelled in any API response; both bases appear correctly across a provider run and a fallback run — extend `backend/tests/integration/test_research_api.py`
- [X] T036 Run the full gate suite on the host (backend pytest/ruff/mypy; frontend lint/typecheck/test/build) and the migration drill (quickstart.md §6) on a disposable database
- [X] T037 **Measure SC-001** on at least 5 real applications, including at least one name-collided company (the Pango class): run research through the UI/API against real application data, and record per-application entity-resolution outcomes (correct / wrong / honest-uncertain, with the identification's reasoning) as **measured facts in this file and HANDOFF.md — never in fixtures or committed files**. JDs, provider outputs, and any personal data stay outside the repository (project data-safety rules). Billable: ~5 provider runs; record actual spend: recorded: 4/5 correct entities, 1/5 honest-uncertain (no public web presence — declared, zero sources), 0/5 wrong, including one deliberately name-ambiguous employer; 41/42 listed sources on-entity (one competitor-comparison page). Aggregates only here by design — employer names stay out of this public repository. Spend: within the Tavily plan (usage API posted hours late: 129 research + 13 search credits across ALL slice runs and probes).
- [X] T038 Update living documents to match what was actually built: `docs/08_Technical_Spec.md` status markers, `CLAUDE.md` research section (Layer 1/Layer 2 description is superseded), `HANDOFF.md` (state + the D2 correction + T037's measurements), add slice 010 to `docs/05_Implementation_Plan.md`'s slice table, and mark 008's spec as partially superseded by 010 in `specs/008-company-research/spec.md` header — amend, never rewrite history
- [X] T039 Run `/security-review` over the branch diff (new outbound HTTP surface: posting text sent to a third-party API — confirm no secrets/PII beyond posting content, untrusted-data framing, error-detail discipline)
- [X] T040 Full quickstart.md pass end-to-end on the Docker stack with the scratch user; delete everything seeded; record total actual spend: performed as the staged verifications above (§2 T020, §3 T025, §4 T029, §5 T032, §6 via `test_migration_0020` on its scratch database) plus gates and cleanup; scratch `@example.com` user deleted with everything it owned. Total marginal spend: ~142 Tavily plan credits ($0 cash) + ≈$0.065 Gemini across two builtin runs.

---

## Dependencies

- Phase 1 → Phase 2 → all story phases. Phase 2 is strictly blocking (storage + seam +
  **T012, the legacy renderer, which both US3 and US4 render through** — this is the explicit
  resolution of the first analysis pass's I1 finding).
- US1 (Phase 3) blocks nothing but is the MVP; US2 depends on US1's use case and UI existing.
- US3 depends on Phase 2 (port, T012) and touches US1's use case — start after T016 lands.
- US4 depends on Phase 2 (persistence, T012) and can run parallel to US2/US3.
- Polish (Phase 7) last; T033/T034/T035 may start any time after their targets exist; T037
  requires US1 complete (and benefits from US2 for no-posting rows among the real five).

## Parallel Execution Examples

- After T011: T012, T013, T014, T018 in parallel (different files).
- After T016: US2 (T022) ∥ US3 (T026) ∥ US4 (T030).
- Phase 7: T033 ∥ T034 ∥ T035.

## Implementation Strategy

MVP = Phases 1–3 (T001–T021): role-aware research for JD-bearing applications, provider-only.
Stop-and-verify at each checkpoint; every billable verification task records actuals inline.
Incremental delivery: US2 (honest no-posting), then US3 (resilience), then US4 (history), then
polish. Tick boxes as tasks complete and amend task text where implementation deviates — a task
list that lies is worse than none.

## Implementation deviations (amended as required — a task list that lies is worse than none)

- `research_windows.py` gained `Freshness.AGING` (plan said "unchanged"): FR-013's three states
  need three values; two old boundary tests were updated to the new contract.
- T015 grew two provider-contract behaviours the Docker verification forced: the output schema is
  inlined to `properties`+`required` (pydantic's `$defs`/`$ref`/`title` are refused with a 400)
  and a `pending` envelope is polled by request id. Both asserted in `test_tavily_research.py`.
- T012's legacy renderer extraction ran inside Phase 2 as planned post-remediation; the tiered
  view also kept the freshness labels the old header carried.
- T035 is satisfied by the api tests' per-run `cost_basis` assertions (provider=estimate,
  fallback/legacy=recorded, failure non-null): no endpoint aggregates costs, so there is nothing
  that could sum the two bases unlabelled.
- T039 (`/security-review`): zero findings at the confidence bar; its one hardening note —
  filter `company_identification.website` to http(s) like source URLs — was applied in
  `research-sections.tsx` with a test.
- T038's docs pass also fixed pre-existing staleness: `docs/05`/`docs/08` still called slice 008
  "Planned" although it shipped.
