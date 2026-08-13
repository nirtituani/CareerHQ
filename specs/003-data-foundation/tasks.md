---
description: "Task list for Data Foundation implementation"
---

# Tasks: Data Foundation

**Input**: Design documents from `/specs/003-data-foundation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/extraction-seam.md](./contracts/extraction-seam.md),
[contracts/http-api.md](./contracts/http-api.md), [quickstart.md](./quickstart.md),
[docs/09_Design_Language.md](../../docs/09_Design_Language.md)

**Tests**: Included. Constitution Principle VII makes 80% backend coverage a merge gate, and
[contracts/extraction-seam.md](./contracts/extraction-seam.md) lists seven obligations that must
fail before the implementation that satisfies them.

**Organization**: Grouped by user story so each is independently shippable and demo-able.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1 / US2 / US3, mapping to the user stories in spec.md
- Every code task names the exact file it touches

## Task kinds that are not code

- 🔧 **MANUAL** — performed in an external console. States exactly what to do.
- 👁 **OBSERVE** — verified by looking at the running system rather than by a test. Each states
  what to look for **and what failure looks like**.

## Three checks that exist because the thing they protect is invisible

Called out here because they are easy to drop and expensive to lose:

- **T032** — the import-graph test. Principle V holds only while `litellm_gateway.py` is the sole
  importer of `litellm`. Reviewer vigilance is not a mechanism; a test is.
- **T049** — the suite passing with **no API key**, verified by unsetting it rather than by
  assuming the fake was used.
- **T067** — the absence of a `rejected` column. Enforcement is a thing *not* existing, so nothing
  fails when it reappears. It has to be asserted deliberately.

## Path Conventions

Existing web application per plan.md: `backend/src/careerhq/`, `frontend/src/`.

---

## Phase 1: Setup

- [ ] T001 Add `litellm==1.96.2`, `pdfplumber==0.11.10` and `python-docx==1.2.0` to
      `backend/pyproject.toml`. Versions verified against PyPI in research R1/R4 — do not adjust
      them from memory. **PyMuPDF is deliberately excluded**: it is the better extractor and is
      dual-licensed AGPL-3.0, which is an obligation for a deployed web application (R4)
- [ ] T002 [P] Wire `next/font/google` in `frontend/src/app/layout.tsx` for Fraunces, IBM Plex Sans
      and IBM Plex Mono, exposing `--font-fraunces`, `--font-plex-sans`, `--font-plex-mono`.
      `globals.css` already references these with inline fallbacks, so the page renders either way —
      confirm the fonts actually load rather than trusting the fallback (docs/09 §2)
- [ ] T003 [P] Add `AI_PROVIDER`, `ANTHROPIC_API_KEY` and the per-task model settings to
      `.env.example`, each commented with what happens when it is unset: readiness reports
      `not_configured` and import returns 503 naming the setting. `S3_*` entries already exist from
      slice 002
- [ ] T004 Install and confirm the backend still starts: `.venv/bin/pip install -e ".[dev]"`, then
      `docker compose up -d` and check `/api/health/ready` still answers
- [ ] T005 [P] Create `backend/tests/fixtures/` with a single-column sample CV (PDF) and a DOCX
      equivalent, for extraction tests that must not depend on a personal document

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Blocks every user story.** The model and schema modules become packages here; doing it later
means rewriting every import added in between.

- [ ] T006 Convert `backend/src/careerhq/domain/models.py` into a package
      `domain/models/` with `identity.py` holding `User` and `ProfessionalProfile` unchanged, and
      `__init__.py` re-exporting every existing name. **No slice 001 import may change** — verify by
      running the existing suite untouched before writing anything new
- [ ] T007 Convert `backend/src/careerhq/domain/schemas.py` into a package the same way, with
      `__init__.py` re-exporting existing names
- [ ] T008 [P] Write a failing test in `backend/tests/unit/test_config.py` asserting
      `ai_provider_configured` is `False` when no provider settings are present and `True` when they
      are, mirroring `google_oauth_configured`. **Correct red**: `AttributeError`, because the
      property does not exist
- [ ] T009 [P] Write a failing test in `backend/tests/integration/test_health.py` asserting
      readiness reports `ai_provider` as `not_configured` when unset, and that this neither fails
      the check nor masks a real failure — the same obligation slice 002's most important readiness
      test proved for cache and object storage
- [ ] T010 Add `ai_provider`, `anthropic_api_key` and the per-task model map to
      `backend/src/careerhq/config.py`, with `ai_provider_configured`. Secrets use `SecretStr` so
      the T068 error-message protection covers them automatically
- [ ] T011 Add `ai_provider` to the probe set in `backend/src/careerhq/api/routes/health.py`,
      following the existing three-state pattern exactly
- [ ] T012 Extend `frontend/src/components/app-shell.tsx` with the sidebar navigation from
      docs/09 §6.0 — Dashboard, Applications, Profile, Career Advisor, CV Builder, Settings. Career
      Advisor, CV Builder and Settings are marked with the *not built yet* treatment rather than
      being broken links, which is §5's three-empty-states rule applied to navigation. **Without
      this every screen the later phases build is unreachable**, which is why it sits in the
      blocking phase rather than beside the screens it serves
- [ ] T013 Confirm `ruff check`, `ruff format --check`, `mypy src` and `pytest` all pass from
      `backend/`, and that coverage has not dropped below 80%

**Checkpoint**: models and schemas are packages, configuration knows about the provider, and
readiness reports it honestly when absent. Nothing user-visible has changed.

---

## Phase 3: User Story 1 — Reach a populated profile without retyping (Priority: P1) 🎯 MVP

**Goal**: Upload a CV, review what was extracted, correct it, approve — and get a populated
Professional Profile plus a Master Resume.

**Independent Test**: Upload a real CV as a signed-in user with an empty profile. Confirm the
extracted content appears for review *before* anything is stored, corrections survive, and approval
produces exactly one profile and one Master Resume.

### The seam — tests first (contracts/extraction-seam.md)

- [ ] T014 [P] [US1] Test in `backend/tests/unit/test_ports.py`: `StructuredCompletion.complete`
      requires a `schema` and returns a `Completion` whose `.value` is an instance of it.
      **Correct red**: `ImportError` — `application/ports.py` does not exist (obligation O1)
- [ ] T015 [P] [US1] Test in `backend/tests/unit/test_ports.py`: the returned `Completion.usage`
      carries model, input tokens, output tokens and cost. **Correct red**: `ImportError` (O4,
      FR-026)
- [ ] T016 [P] [US1] Test in `backend/tests/unit/test_extraction_gateway.py`: output failing schema
      validation raises rather than returning partial data. **Correct red**: `ImportError` (O2,
      FR-025)
- [ ] T017 [P] [US1] Test in `backend/tests/unit/test_extraction_gateway.py`: model selection
      resolves from the **task name**, and two different task names can resolve to two different
      models. This is what makes docs/08 §3.2.3 expressible in slice 004 — assert it now, while the
      seam has one caller and is cheap to change (O3)
- [ ] T018 [P] [US1] Test in `backend/tests/unit/test_extraction_gateway.py`: `FixtureGateway`
      returns `usage.is_fixture = True`, and the real adapter returns `False`. **Correct red**:
      `ImportError` (R3)

### The seam — implementation

- [ ] T019 [US1] Create `backend/src/careerhq/application/ports.py` with the
      `StructuredCompletion` Protocol, `Completion[T]` and `Usage`, exactly as
      [contracts/extraction-seam.md](./contracts/extraction-seam.md) specifies. This file is what
      slice 004 inherits — the contract document is the spec, not this task's description
- [ ] T020 [US1] Create `backend/src/careerhq/infrastructure/ai/litellm_gateway.py` implementing the
      Protocol over LiteLLM. **This must be the only module in the codebase that imports
      `litellm`** (O5)
- [ ] T021 [P] [US1] Create `backend/src/careerhq/infrastructure/ai/fixture_gateway.py` returning
      canned structured values with `is_fixture = True`. Selected **only** by an explicit
      `AI_PROVIDER=fixture` — never by the absence of a key, because silently returning canned data
      would mean a user uploads their real CV and reviews invented content (R3)
- [ ] T022 [US1] Add `get_structured_completion` to `backend/src/careerhq/api/deps.py`, resolving
      the adapter from configuration and raising a named error when unconfigured. Follow the
      `get_verified_google_claims` pattern — its docstring already calls itself "the seam", and this
      is the same shape for the same reason (O6, O7)

### Document text extraction

- [ ] T023 [P] [US1] Test in `backend/tests/unit/test_documents.py`: text is recovered from the
      sample PDF and DOCX fixtures. **Correct red**: `ImportError`
- [ ] T024 [P] [US1] Test in `backend/tests/unit/test_documents.py`: a PDF with no text layer
      yields empty text and is reported as such, **not** as an empty successful extraction (FR-008)
- [ ] T025 [P] [US1] Create `backend/src/careerhq/infrastructure/documents/pdf.py` using pdfplumber
- [ ] T026 [P] [US1] Create `backend/src/careerhq/infrastructure/documents/docx.py` using python-docx

### Data model

- [ ] T027 [US1] Define the extraction schema in
      `backend/src/careerhq/domain/schemas/extraction.py` — the Pydantic model the LLM must fill,
      covering contact, titles, summary, work experience with per-bullet granularity, skills,
      projects, education, certifications and languages. **Bullets are separate items**, because
      slice 004 tailors and approves at bullet granularity and a text blob makes that impossible
- [ ] T028 [US1] Add `ImportedResume` and `ExtractionItem` to
      `backend/src/careerhq/domain/models/imports.py` per data-model.md §1, including the usage
      audit columns and `is_fixture`
- [ ] T029 [US1] Add profile child entities and `ResumeProfile` to
      `backend/src/careerhq/domain/models/profile.py` per data-model.md §2, each carrying `source`
      so FR-004's provenance survives approval rather than being discarded at it
- [ ] T030 [US1] Write migration `backend/alembic/versions/0003_*.py` for the staging and profile
      tables, including **constraint C4** — `UNIQUE (profile_id) WHERE is_master`

### Behaviour — tests first

- [ ] T031 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: after upload and
      extraction, the profile is still **empty**. This is the whole point of staging — if it fails,
      Principle II is not being enforced (FR-003, FR-007)
- [ ] T032 [US1] Test in `backend/tests/unit/test_architecture.py`: **`litellm` is imported by
      exactly one module**, `infrastructure/ai/litellm_gateway.py`. Walk the source tree and assert
      it. Principle V says business domains must not call AI providers; this is what turns that from
      a rule someone remembers into a property of the import graph (O5)
- [ ] T033 [US1] Test in `backend/tests/unit/test_architecture.py`: `storage_key` is read by
      exactly one module. FR-006 and ADR-013 both rest on the uploaded file never becoming a source
      of truth, and that is a claim about what does **not** read it — so it needs asserting the same
      way T032 asserts the provider boundary, and for the same reason
- [ ] T034 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: approving creates
      exactly one Master Resume, and **approving twice still yields one** — constraint C4 refuses
      the second. A double-clicked button is the realistic path to this bug (SC-004)
- [ ] T035 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: a corrected item is
      stored with the user's value and `source = user_corrected`, and the original extraction is
      not stored as a profile fact (Scenario 2, FR-004)
- [ ] T036 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: an abandoned import
      leaves the profile empty and is discardable (Scenario 6, FR-007)
- [ ] T037 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: a file that is
      neither PDF nor DOCX is rejected with a message naming accepted formats, and nothing is
      stored (FR-001, Scenario 5)
- [ ] T038 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: extraction yielding
      nothing returns 422 with `extraction_error` set — **not** 202 with an empty item list
      (FR-008)
- [ ] T039 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: with no provider
      configured the import endpoint returns **503 naming the missing setting** — not a crash, and
      not a successful response with empty extraction (FR-028, obligation O7). This is the first-run
      path: before credentials are set, every user hits it, and it is the only seam obligation with
      no test until now
- [ ] T040 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: a second import for a
      user who already has a profile does **not** create a second profile, and does not overwrite a
      verified fact without approval (FR-009, constraint C1)
- [ ] T041 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: a high confidence
      value does **not** auto-accept an item — every item arrives `pending` regardless (FR-029).
      Principle II admits no threshold, and this is the test that keeps it that way
- [ ] T042 [P] [US1] Test in `backend/tests/integration/test_import_flow.py`: a failed approval
      leaves nothing behind — no partial profile, no orphaned Master Resume (FR-023)
- [ ] T043 [P] [US1] Extend the route-enumeration test in
      `backend/tests/integration/test_auth.py` so every new import route returns 401 unauthenticated
      and 404 — **not 403** — for another user's import (FR-019, contracts/http-api.md)

### Behaviour — implementation

- [ ] T044 [US1] Create `backend/src/careerhq/application/extract_resume.py`: store the upload,
      extract text, call the seam, persist the staged `ImportedResume` and its items with the usage
      record
- [ ] T045 [US1] Create `backend/src/careerhq/application/approve_import.py`: write accepted items
      to the profile and create the Master Resume **in one transaction** (FR-023, R6)
- [ ] T046 [US1] Create `backend/src/careerhq/api/routes/imports.py` with the endpoints in
      [contracts/http-api.md](./contracts/http-api.md), including the 503 that names the missing
      provider setting (FR-028)
- [ ] T047 [US1] Test in `backend/tests/unit/test_logging.py`: an import failure's log record
      carries its diagnostic detail in **structured fields**, and the message string carries none of
      it (FR-022). Slice 002 established that the deployed platform discards message text entirely,
      so anything needed to debug a production import failure has to survive in `extra={…}`.
      **Correct red**: the fields are absent because nothing populates them yet
- [ ] T048 [US1] Confirm backend gates pass and coverage holds at ≥80%

### The check that keeps the suite honest

- [ ] T049 [US1] **Run the full suite with `ANTHROPIC_API_KEY` and `AI_PROVIDER` unset**, and
      confirm it passes. Verify by unsetting them rather than by assuming the fake was used —
      FR-027 exists so CI never depends on a provider being reachable, and the only way to know is
      to remove the key and watch. **Failure looks like**: a hang, a network error, or a skip

### Frontend

- [ ] T050 [P] [US1] Build the upload screen and its states in
      `frontend/src/app/import/page.tsx` per docs/09 §6.6 — `idle → uploading → extracting →
      extracted | failed`. **Failure must name a likely cause** ("looks like a scan with no text
      layer"), never present an empty review form
- [ ] T051 [US1] Build the review interface in `frontend/src/components/import-review/` per
      docs/09 §6.5: two panes, per-section progress, per-item accept/correct/discard, provenance
      rules and confidence meters, reviewed items collapsing, and the persistent bottom bar
- [ ] T052 [P] [US1] Implement the provenance and confidence primitives in
      `frontend/src/components/provenance.tsx` per docs/09 §5 — **dashed rule for extracted, solid
      for corrected/added**. Colour is never the only channel, so the rule style is the primary
      carrier
- [ ] T053 [P] [US1] Keyboard navigation for the review list: `A` accept, `E` edit, `D` discard,
      `J`/`K` to move. This is the difference between reviewing sixty items and abandoning the
      import, not a nicety (docs/09 §6.5)
- [ ] T054 [P] [US1] Persistent fixture banner in `--color-fixture` whenever `is_fixture` is set,
      visible for the whole review. The one unacceptable outcome is approving invented content into
      a real profile (R3)
- [ ] T055 [P] [US1] Component tests in `frontend/src/components/__tests__/` for the provenance
      primitives and the review item states
- [ ] T056 [US1] Build the Profile screen at `frontend/src/app/profile/page.tsx` per docs/09 §6.4,
      carrying provenance rules into the profile — FR-004 requires the distinction *after* approval,
      not only during review. Its empty state routes to import rather than reporting emptiness

### Verify against the real stack

- [ ] T057 👁 **OBSERVE** [US1] Run the quickstart's User Story 1 walkthrough against
      `docker compose up -d` with a **real CV**: confirm the profile is empty after extraction and
      populated after approval, that a correction survives, and that approving twice leaves one
      Master Resume. **Failure looks like**: profile rows appearing before approval, which means
      staging is not staging
- [ ] T058 👁 **OBSERVE** [US1] Upload a scanned/image-only PDF against the running stack and
      confirm it reads as a **failure**, not an empty form (FR-008, docs/09 §5)
- [ ] T059 [US1] Measure SC-002 against a real CV: at least 80% of work-experience bullets
      extracted and attributed to the correct role. **Do this now, not at the end** — if it misses,
      the honest responses are a better prompt or a stronger model, both configuration under R1,
      and both cheaper to discover here than after the UI is built

**Checkpoint**: a user can turn their existing CV into a reviewed, populated profile. This is the
MVP and slice 004's input.

---

## Phase 4: User Story 2 — Record a job to tailor against (Priority: P2)

**Goal**: Record a job with its description, and open a detail view that later slices can fill.

**Independent Test**: Create an application with a job description and no submitted resume. Confirm
it persists, is visible only to its owner, and opens a detail view showing the full description.

### Tests first

- [ ] T060 [P] [US2] Test in `backend/tests/integration/test_applications.py`: an application is
      valid with **no** submitted resume while in a pre-submission status (FR-011)
- [ ] T061 [P] [US2] Test in `backend/tests/integration/test_applications.py`: two users cannot see
      or retrieve each other's applications; another user's id returns **404, not 403**, so the
      endpoint does not confirm existence (FR-019, contracts/http-api.md)
- [ ] T062 [P] [US2] Test in `backend/tests/integration/test_applications.py`: every status change
      writes a history row, and there is **no update or delete path** to that table (FR-012,
      constraint C6, Constitution IV)
- [ ] T063 [P] [US2] Test in `backend/tests/integration/test_applications.py`: two applications
      naming the same company resolve to **one** company row (FR-014, constraint C2)
- [ ] T064 [P] [US2] Test in `backend/tests/integration/test_applications.py`: `normalized_status`
      cannot be set directly by a request — it is derived from the label. A client-settable
      normalized status is a second source of truth for the same fact (FR-013)

### Implementation

- [ ] T065 [US2] Add `Application`, `Company` and `ApplicationStatusHistory` to
      `backend/src/careerhq/domain/models/application.py` per data-model.md §3. Note `salary_text`
      is **free text**, not min/max — the source stores "90-110k" and "competitive"
      interchangeably (R8)
- [ ] T066 [US2] Write migration `backend/alembic/versions/0004_*.py` with constraints **C2**
      (`UNIQUE (user_id, normalized_name)` on companies) and **C3** (partial
      `UNIQUE (user_id, import_source, import_source_id)` on applications)
- [ ] T067 [US2] Test in `backend/tests/integration/test_applications.py`: **no column named
      `rejected` exists anywhere**, asserted against `information_schema.columns`. FR-016's
      enforcement is an *absence*, so nothing fails when it reappears — this is the only thing that
      would catch it. **Failure looks like**: any row returned. Release blocker
- [ ] T068 [US2] Create `backend/src/careerhq/application/record_application.py` and
      `backend/src/careerhq/api/routes/applications.py` per contracts/http-api.md
- [ ] T069 [P] [US2] Build the applications table at `frontend/src/app/applications/page.tsx` per
      docs/09 §6.2 — dense rows, mono tabular dates, status pill showing the **user's label** with a
      neutral marker where the normalized category differs
- [ ] T070 [P] [US2] Build the dashboard at `frontend/src/app/dashboard/page.tsx` per docs/09 §6.1,
      with the four stat tiles as **filters** — clicking one filters the table and the active tile
      is visibly selected, as JobTracker already does
- [ ] T071 [US2] Build the tabbed application detail at
      `frontend/src/app/applications/[id]/page.tsx` per docs/09 §6.3: `Details | Requirements ◦ |
      Company ◦ | Interview ◦ | Versions`, one primary `Tailor CV` action, and the full job
      description text on `--surface-sunken`
- [ ] T072 [P] [US2] Implement the *not built yet* tab treatment — unbuilt capabilities marked in
      the tab itself so the user never clicks in to discover it. It must never read as **failed**
      or as **empty data**; those are three distinct states (docs/09 §5)
- [ ] T073 👁 **OBSERVE** [US2] Against the running stack: create an application with a real job
      description, change its status, confirm a history row appears, and confirm the detail view
      shows the description in full. **Failure looks like**: the detail view linking out instead of
      showing stored text

**Checkpoint**: slice 004 now has both of its inputs — a profile to tailor and a job to tailor
against.

---

## Phase 5: User Story 3 — Arrive with existing history (Priority: P3)

**Goal**: Import real JobTracker history, with rejection derived rather than stored.

**Independent Test**: Import a real export; confirm normalized statuses match, rejection is
derived, and re-running creates nothing.

- [ ] T074 🔧 **MANUAL** [US3] Export real data from JobTracker (`GET /api/export`) and add it to
      `backend/tests/fixtures/jobtracker_export.csv`, with personal details replaced where
      appropriate. The mapping is already resolved in research R8 — this is the fixture that proves
      it against reality rather than against a guess
- [ ] T075 [US3] Test in `backend/tests/integration/test_jobtracker_import.py`: **idempotency
      first**. Importing the same file twice creates no duplicate applications and no duplicate
      companies, refused by constraint C3 and reported as skipped rather than as errors. Written
      first deliberately — idempotency is the requirement most likely to pass in the happy path and
      break under retry (FR-017, SC-006, data-model.md §4)
- [ ] T076 [P] [US3] Test in `backend/tests/unit/test_jobtracker_mapping.py`: a row with
      `rejected = true` and a status of anything else keeps its **original label** and takes a
      normalized status of `rejected`. This is the FR-016 reconciliation, and it records both how
      far the application got and how it ended (R8 Finding 1)
- [ ] T077 [P] [US3] Test in `backend/tests/unit/test_jobtracker_mapping.py`: an unrecognised
      status label is preserved verbatim, normalized to `other`, and **flagged rather than
      rejected**. JobTracker keeps custom statuses in browser storage, so unfamiliar labels are the
      common case (R8 Finding 3)
- [ ] T078 [P] [US3] Test in `backend/tests/unit/test_jobtracker_mapping.py`: dates parse
      **day-first** — `03/04/2026` is 3 April. An ambiguous or unparseable value is preserved raw
      and reported, never guessed, because a wrong date is worse than an absent one for a Career
      Advisor reasoning over timelines (R8 Finding 4)
- [ ] T079 [P] [US3] Test in `backend/tests/integration/test_jobtracker_import.py`: unmappable rows
      are reported individually while the rest still import, and the transaction contains only rows
      already known to be mappable (FR-018, FR-023, R6)
- [ ] T080 [P] [US3] Test in `backend/tests/unit/test_jobtracker_mapping.py`: the source
      `user_id` is **discarded**. Ownership comes from the session, and importing a foreign user id
      is exactly the vulnerability FR-019 exists to prevent
- [ ] T081 [US3] Create `backend/src/careerhq/application/import_jobtracker.py` — validate and
      partition rows **before** opening the transaction, then import in one commit
- [ ] T082 [US3] Add the import endpoint to `backend/src/careerhq/api/routes/applications.py`
      returning the imported / skipped / rejected report
- [ ] T083 [P] [US3] Build the import screen and its report at
      `frontend/src/app/applications/import/page.tsx`
- [ ] T084 👁 **OBSERVE** [US3] Import the real export against the running stack. Confirm counts,
      that rejection arrived as a status value, and that **re-importing the identical file adds
      nothing**. **Failure looks like**: duplicated applications, meaning C3 did not deploy

**Checkpoint**: the system holds real history for the slice 007 Career Advisor.

---

## Phase 6: Polish & Cross-Cutting Concerns

### Deployment prerequisites

- [ ] T085 🔧 **MANUAL** Create the Railway bucket and set credentials: `railway bucket create`,
      then `railway bucket credentials` into `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_ENDPOINT_URL` /
      `S3_BUCKET`. Verified in R5 that no bucket exists yet and that this needs **no application
      code** — `storage.py` already speaks S3 and slice 002 made the settings optional
- [ ] T086 🔧 **MANUAL** Set `AI_PROVIDER` and `ANTHROPIC_API_KEY` on the deployed backend service
- [ ] T087 👁 **OBSERVE** `curl` deployed `/api/health/ready` and confirm **`object_storage` and
      `ai_provider` both report `ok`**, not `not_configured` (FR-021, FR-028). **Failure looks
      like**: either still `not_configured`, meaning the variables did not reach the running
      container — slice 002's lesson is that variables are injected at container *creation*
- [ ] T088 👁 **OBSERVE** Import a CV on the **deployed** site and confirm the file landed in the
      bucket and that `imported_resumes` recorded model, tokens and cost with `is_fixture = false`.
      **Failure looks like**: `is_fixture = true`, meaning the deployment is serving canned content
      and every extraction so far has been fictional
- [ ] T089 👁 **OBSERVE** Confirm the deployed system holds **both** of slice 004's inputs — a
      populated profile **and** an application carrying real job description text (SC-010). This is
      the slice's own definition of done, and the profile half alone does not meet it
- [ ] T090 👁 **OBSERVE** Run T063's `information_schema` query against the **deployed** database.
      A constraint that holds locally and not in production is not a constraint

### Gates and documentation

- [ ] T091 Run every gate from the host and confirm green: `ruff format --check .`, `ruff check .`,
      `mypy src`, `pytest` from `backend/`; `lint`, `typecheck`, `test`, `build` from `frontend/`.
      Host, not containers — `backend/.dockerignore` excludes `tests/` and a container `next build`
      fails on a directory the dev server owns (CLAUDE.md)
- [ ] T092 [P] Update `README.md` with the CV import flow, the provider-key options, and the bucket
      requirement
- [ ] T093 [P] Update `CLAUDE.md`: slice 003 complete, what carries into slice 004, and any gotcha
      this slice proved with its symptom
- [ ] T094 [P] Update `docs/05_Implementation_Plan.md` and `docs/08_Technical_Spec.md` — slice 003
      complete, slice 004 next, capability status markers moved
- [ ] T095 Walk `specs/003-data-foundation/quickstart.md` end to end **as written** and correct it
      against what actually happens. Slice 001's T069 and slice 002's T052 both found real errors
      this way; documentation nobody has followed is a claim, not a procedure
- [ ] T096 Confirm the scope guards held: **exactly one model call** in the whole slice, no agent
      loop, no embeddings, no vector retrieval, and no job-description summarization. Review the
      full diff — if it contains a second `complete()` call site, slice 004 arrived early

---

## Dependencies & Execution Order

```
Phase 1 Setup
    ↓
Phase 2 Foundational  ← blocks everything; models/schemas become packages here
    ↓
Phase 3 US1 (P1)  ─── MVP. Slice 004's profile input
    ↓
Phase 4 US2 (P2)  ─── slice 004's job-description input
    ↓
Phase 5 US3 (P3)  ─── history for slice 007; needs T074's real export
    ↓
Phase 6 Polish
```

**US1 and US2 are independent** once Phase 2 lands — they touch different models, different routes
and different screens. US3 depends on US2's `Application` model and on nothing in US1.

**MVP is US1 alone.** It delivers the thing that has no substitute: a populated profile without
retyping a career history.

**US1 + US2 is the smallest combination that unblocks slice 004** — and that is a fact about the
source data rather than a judgement, since JobTracker carries no job description text at all
(R8 Finding 2), so US3 cannot supply tailoring input even in principle.

## Parallel Opportunities

- **Phase 1**: T002, T003, T005 together
- **Phase 2**: T008 and T009 together (different files)
- **Phase 3 seam tests**: T014–T018 together
- **Phase 3 behaviour tests**: T031, T034–T043 together
- **Phase 3 frontend**: T050, T052, T053, T054, T055 alongside backend work
- **Phase 4 tests**: T060–T064 together
- **Phase 5 mapping tests**: T076–T080 together after T075
- **Phase 6 docs**: T092, T093, T094 together
