---
description: "Task list for Deployment implementation"
---

# Tasks: Deployment

**Input**: Design documents from `/specs/002-deployment/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/readiness.md](./contracts/readiness.md),
[quickstart.md](./quickstart.md)

**Tests**: Included. Constitution Principle VII makes 80% backend coverage a merge gate, and
[contracts/readiness.md](./contracts/readiness.md) lists six obligations that must fail before
the implementation that satisfies them.

**Organization**: Grouped by user story so each is independently shippable and demo-able.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1 / US2 / US3, mapping to the user stories in spec.md
- Every code task names the exact file it touches

## Two task kinds that are not code

This slice is unusual — a third of it cannot be automated, and pretending otherwise would produce
a task list that lies about what it takes to finish.

- 🔧 **MANUAL** — the author performs it in an external console. It states exactly what to enter.
- 👁 **OBSERVE** — verified by looking at the deployed system, not by running a test. FR-015
  exists because `ENVIRONMENT=production` has never executed anywhere; reading the source proves
  nothing about it. Each states what to look for **and what failure looks like**.

## Path Conventions

Existing web application per plan.md: `backend/src/careerhq/`, `frontend/src/`, with
`railway.toml` and documentation at the repository root.

---

## Phase 1: Setup

**Purpose**: Deployment configuration that lives in the repository rather than only in a console.

- [ ] T001 [P] Create `railway.toml` at the repository root declaring, per service: the backend's
      pre-deploy command `alembic upgrade head` and healthcheck path `/api/health/ready`
      (research.md R3, R4). Config-as-code so the deployment is reviewable in a diff rather than
      discoverable only by clicking through a web console
- [ ] T002 [P] Update `.env.example` to document `REDIS_URL` and the `S3_*` block as **optional**,
      with a comment saying why: they are unset in deployment until slices 003/004 need them, and
      setting placeholder values would make the application believe it has a cache
- [ ] T003 [P] Add `ENVIRONMENT=production` and `PUBLIC_BASE_URL` to the deployment section of
      `.env.example` with a comment that `PUBLIC_BASE_URL` must match the OAuth redirect URI
      registered with Google exactly

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Make the backend able to start without a cache and object storage.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. This is not a
sequencing preference — `REDIS_URL` and the four `S3_*` settings are currently required fields
with no defaults, so a Postgres-only deployment raises `ValidationError` at import and never
reaches any endpoint (research.md R1). Every later task is unreachable until this lands.

### Tests first

- [ ] T004 [P] Write a failing test in `backend/tests/unit/test_config.py` asserting that
      `Settings` constructs successfully when `REDIS_URL` and every `S3_*` value are absent
- [ ] T005 [P] Write a failing test in `backend/tests/unit/test_config.py` asserting
      `cache_configured` and `object_storage_configured` are `False` when unset and `True` when
      set, mirroring the existing `google_oauth_configured` tests
- [ ] T006 [P] Write a failing test in `backend/tests/unit/test_config.py` asserting that
      `DATABASE_URL` and `SESSION_SECRET` remain **required** — a missing `SESSION_SECRET` must
      still raise, naming the field without printing its value (T068 protection, data-model.md)

### Implementation

- [ ] T007 Make `redis_url` and the four `s3_*` fields optional (`| None = None`) in
      `backend/src/careerhq/config.py`, and add `cache_configured` / `object_storage_configured`
      properties beside the existing `google_oauth_configured`. Follow that field's comment — it
      describes this exact situation for a different dependency
- [ ] T008 [P] Make `backend/src/careerhq/infrastructure/redis.py` raise a specific named error
      when a client is requested and `cache_configured` is `False`, rather than constructing a
      client from `None`. Absence must fail loudly at first use, since it no longer fails at
      startup (plan.md Constitution Check)
- [ ] T009 [P] Make `backend/src/careerhq/infrastructure/storage.py` fail the same way when
      `object_storage_configured` is `False`
- [ ] T010 [P] Write tests in `backend/tests/unit/test_config.py` asserting both accessors raise
      their named error when unconfigured — proving the failure moved rather than vanished

**Checkpoint**: The backend starts with only `DATABASE_URL` and `SESSION_SECRET` set. Verify
locally by running the backend with `REDIS_URL` and `S3_*` unset before continuing.

---

## Phase 3: User Story 1 — Reach CareerHQ from anywhere (Priority: P1) 🎯 MVP

**Goal**: The application is publicly reachable over HTTPS, and its readiness report is honest
about what it checked.

**Independent Test**: From a device with no project setup — a phone on mobile data is the
strictest version — open the address and confirm the sign-in page renders over HTTPS. Separately
fetch readiness and confirm it names what it checked.

### Tests first — the six obligations from contracts/readiness.md

- [ ] T011 [P] [US1] Test in `backend/tests/integration/test_health.py`: all dependencies
      configured and healthy → all three `ok`, overall `ok`, HTTP 200 *(may already exist; assert
      it still passes unchanged)*
- [ ] T012 [P] [US1] Test in `backend/tests/integration/test_health.py`: cache and object storage
      unconfigured → both report `not_configured`, overall `ok`, HTTP 200
- [ ] T013 [P] [US1] Test in `backend/tests/integration/test_health.py`: cache unconfigured **and**
      database unreachable → database `error`, cache `not_configured`, overall `error`, HTTP 503.
      **This is the most important test in the slice** — it proves `not_configured` neither causes
      failure nor masks a real one
- [ ] T014 [P] [US1] Test in `backend/tests/integration/test_health.py`: a failing probe returns
      the exception class name and **not** the driver's message, which names the internal host,
      port and database user (T068)
- [ ] T015 [P] [US1] Test in `backend/tests/integration/test_health.py`: all three dependency keys
      are present in every response regardless of configuration, so a consumer never distinguishes
      "key missing" from "dependency missing"
- [ ] T016 [P] [US1] Test in `backend/tests/integration/test_health.py`: a configured probe that
      exceeds the timeout reports `error` and the response still returns

### Implementation

- [ ] T017 [US1] Derive the probe set from configuration in
      `backend/src/careerhq/api/routes/health.py` — probe a dependency if and only if it is
      configured; report `not_configured` otherwise; compute overall status from **checked**
      dependencies only. Keep the existing timeout and disclosure behaviour untouched
- [ ] T018 [US1] Confirm coverage stays ≥80% and `ruff check`, `ruff format --check` and
      `mypy src` all pass from `backend/`

### Deploy

- [ ] T019 🔧 **MANUAL** [US1] In the Railway project, create a **backend** service from this
      repository with root directory `backend/`. Do **not** generate a public domain — it is
      reached through the frontend over the private network
- [ ] T020 🔧 **MANUAL** [US1] Create a **frontend** service from this repository with root
      directory `frontend/`, and **generate a public domain**. Record the domain; every later task
      needs it
- [ ] T021 🔧 **MANUAL** [US1] Set the backend service variables: `ENVIRONMENT=production`,
      `DATABASE_URL=${{pgvector.DATABASE_URL}}`, `SESSION_SECRET` (generate with
      `openssl rand -hex 32`), `PUBLIC_BASE_URL=https://<frontend-domain>`. **Leave `REDIS_URL`
      and every `S3_*` variable unset** — that is what makes readiness report `not_configured`
- [ ] T022 🔧 **MANUAL** [US1] Set the frontend service variable
      `BACKEND_URL=http://backend.railway.internal:8000`
- [ ] T023 🔧 **MANUAL** [US1] Confirm the backend service's pre-deploy command and healthcheck
      path are applied from `railway.toml`; set them in the console if the file is not picked up
- [ ] T024 [US1] Deploy both services and confirm the backend reaches a healthy state. If it never
      goes healthy, fetch `/api/health/ready` directly — the healthcheck points at readiness, so a
      readiness bug blocks the entire deployment (research.md R4)

### Verify (SC-001, SC-003, SC-008)

- [ ] T025 👁 **OBSERVE** [US1] Open `https://<frontend-domain>` from a device with no project
      setup and confirm the sign-in page renders over HTTPS. **Failure looks like**: a certificate
      warning, or the page loading over plain HTTP
- [ ] T026 👁 **OBSERVE** [US1] `curl -s https://<frontend-domain>/api/health/ready` and confirm
      `database` is `ok` while `cache` and `object_storage` are `not_configured`, with overall
      `ok`. **Failure looks like**: either reporting `ok` — nothing is deployed to be `ok` about,
      the endpoint is lying and FR-006 is violated — or reporting `error`, which would mean the
      probe is not following configuration
- [ ] T027 👁 **OBSERVE** [US1] Confirm the frontend's `/api/*` proxy actually reaches the backend
      over Railway's private network. **Failure looks like**: the page loading normally while
      every API request fails — Railway's private network is IPv6 and Docker's is IPv4, so this
      cannot reproduce locally (research.md R6)
- [ ] T028 👁 **OBSERVE** [US1] Attempt to connect to the database from outside the deployment and
      confirm it fails (SC-008). **Failure looks like**: a successful connection, meaning the
      database has a public endpoint it should not have

**Checkpoint**: CareerHQ is publicly reachable and reports its health truthfully. This is a
complete, demonstrable increment even if no one can sign in yet.

---

## Phase 4: User Story 2 — Sign in on the public site (Priority: P2)

**Goal**: A real Google sign-in works on the public address, and the production security
configuration is confirmed by observation for the first time in the project's life.

**Independent Test**: On a device with no prior session, complete a real Google sign-in against
the public address, then confirm exactly one account and one profile exist and that signing in
again creates neither.

- [ ] T029 🔧 **MANUAL** [US2] In the Google Cloud console, on the OAuth 2.0 client, add to
      **Authorized redirect URIs** exactly:
      `https://<frontend-domain>/api/auth/callback` — no trailing slash. Google matches by exact
      string, so a near miss fails at the provider with an error describing a mismatch rather than
      what to fix. This step cannot be automated
- [ ] T030 🔧 **MANUAL** [US2] Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on the backend
      service from the same OAuth client

### Verify identity (SC-002)

- [ ] T031 👁 **OBSERVE** [US2] In a private window, sign in with Google at
      `https://<frontend-domain>` and confirm arrival at the dashboard. **Failure looks like**: a
      `redirect_uri_mismatch` at Google, meaning T029's value does not match `PUBLIC_BASE_URL`
- [ ] T032 👁 **OBSERVE** [US2] In the `pgvector` service Console, confirm counts are `1|1` after
      first sign-in. **Failure looks like**: `1|0`, meaning the profile was not created in the
      same transaction as the user
- [ ] T033 👁 **OBSERVE** [US2] Sign out, sign in again, and confirm counts are **still** `1|1`.
      **Failure looks like**: `1|2` — the UNIQUE constraint did not deploy, which is a
      Principle I violation and a release blocker
- [ ] T034 👁 **OBSERVE** [US2] Decline consent at Google and confirm the outcome is explained and
      no account or profile is created

### Verify production security — FR-015, the first execution ever (SC-004)

- [ ] T035 👁 **OBSERVE** [US2] `curl -sI https://<frontend-domain>` and confirm a
      `Strict-Transport-Security` header is present. **Failure looks like**: no such header,
      meaning `is_production` is not true in the deployed environment
- [ ] T036 👁 **OBSERVE** [US2] `curl -sI http://<frontend-domain>` and confirm a redirect to the
      `https://` address. **Failure looks like**: a 200 served over plain HTTP
- [ ] T037 👁 **OBSERVE** [US2] In the browser, after signing in, open DevTools → Application →
      Cookies and confirm the session cookie carries **`Secure`** and **`HttpOnly`**. Do this in a
      browser rather than with `curl` — the browser is what enforces these flags. **Failure looks
      like**: either flag unchecked, meaning the session can be sent over plain HTTP or read by
      page scripts
- [ ] T038 [US2] Record what was actually observed in T035–T037 in `specs/002-deployment/`, not
      what was expected. This configuration had never executed before this slice; the observation
      is the evidence FR-015 requires
- [ ] T039 👁 **OBSERVE** [US2] Search the deployed backend logs for the literal values of
      `SESSION_SECRET`, `GOOGLE_CLIENT_SECRET` and the database password, covering startup and at
      least one completed sign-in. **Failure looks like**: any occurrence at all (FR-017). Slice
      001 found a crash that printed `SESSION_SECRET` in full precisely because it was the code
      meant to protect it — deployed logging is new ground and has never been checked this way

**Checkpoint**: The deployed system authenticates real users under production security settings
that have now been seen working rather than assumed.

---

## Phase 5: User Story 3 — Merged work reaches the site automatically (Priority: P3)

**Goal**: Merging deploys, failing gates do not, and rollback is a practised procedure rather than
a theory.

**Independent Test**: Merge a trivial visible change and confirm it appears with no further
action. Separately merge a change that fails a gate and confirm the site is unchanged.

- [ ] T040 🔧 **MANUAL** [US3] Enable **Wait for CI** on both services in Railway. Without it a
      merge deploys immediately and CI results arrive too late to prevent anything (FR-020)
- [ ] T041 [US3] Merge a trivial, visible change to `main` and confirm it reaches the public site
      with no manual step. Watch with `gh run watch` (SC-005)
- [ ] T042 [US3] **Watch the gate fail.** On a branch, deliberately break a test, merge it, and
      confirm the public site is **unchanged** and the failure is visible in Actions. Then revert.
      A gate nobody has watched fail is not a gate — this is the same discipline CLAUDE.md
      requires when adding any gate (SC-006)
- [ ] T043 👁 **OBSERVE** [US3] Confirm the pre-deploy command ran by finding `alembic upgrade
      head` output in the deployment logs. On the first deploy it will report nothing to apply,
      because the deployed database is already current — that is the expected result, not a
      skipped step (data-model.md)
- [ ] T044 👁 **OBSERVE** [US3] Practise a rollback: redeploy the previous deployment and confirm
      the site returns to it. Do this before an incident requires it (FR-023, SC-007)

**Checkpoint**: Every later slice now ships continuously rather than accumulating an undeployed
backlog.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T045 [P] Add the deployment section to `README.md` covering deploy, reading logs, and
      rollback — including the asymmetry that application rollback is cheap, schema rollback is
      conditional on the migration being reversible, and business data is **never** rolled back
      under Principle IV (FR-024). An operator reads this during an incident, so it must be where
      they will look. It must also state **the exact OAuth redirect URI** and its exact-match
      requirement (FR-012 — the value currently lives only in T029 and a slice artifact, neither
      of which is the project's documentation), and **where to see which version is live, whether
      the last deploy succeeded, and why it failed** (FR-022)
- [ ] T046 [P] Record in `CLAUDE.md` the gotchas this slice proved, with the symptom for each,
      since neither names its own cause: Railway's private network is IPv6 while Docker's is IPv4;
      and Wait for CI waits on **all** GitHub check suites, so a merge can silently never deploy
      while this repository's CI is green
- [ ] T047 [P] Update `CLAUDE.md`'s current-state section: slice 002 complete, the public URL,
      and what carries into slice 003
- [ ] T048 [P] Update `docs/05_Implementation_Plan.md` §5 and §10 — slice 002 complete, slice 003
      next
- [ ] T049 [P] Update `docs/08_Technical_Spec.md`: close Q2 (readiness following configuration),
      mark the production security path as verified rather than unproven in §4.2, and record the
      deployed URL in §1.2
- [ ] T050 Confirm the scope guards held: no user-visible behaviour changed other than the address
      the system is reached at (FR-025, SC-009). Review the full diff against `main` — if it
      contains an application feature, the slice drifted
- [ ] T051 Run every gate from the host and confirm green: `ruff format --check .`, `ruff check .`,
      `mypy src`, `pytest` from `backend/`; `npm run lint`, `npm run typecheck`, `npm test`,
      `npm run build` from `frontend/`
- [ ] T052 Walk `README.md`'s deployment section end to end **as written**, and correct it against
      what actually happens — deploy, find the status of that deployment, and return to the
      previous version, using only the documentation (SC-007, FR-022). This is the slice-002
      equivalent of slice 001's T069, which corrected the quickstart against a real clean-clone run
      and found genuine errors. Documentation nobody has followed is a claim, not a procedure

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup. **Blocks everything** — the backend cannot start
  without it, so no deployment can succeed and no story can be verified
- **US1 (Phase 3)**: Depends on Foundational. This is the MVP
- **US2 (Phase 4)**: Depends on US1 — there is nothing to sign in to until the site is reachable
- **US3 (Phase 5)**: Depends on US1. Independent of US2; a deployment pipeline can be proven
  without authentication working
- **Polish (Phase 6)**: Depends on the stories whose outcomes it documents

### The critical path

```text
T007 (optional config) → T017 (configuration-driven probes) → T024 (deploy healthy)
    → T026 (readiness honest) → T029 (OAuth URI) → T031 (real sign-in)
```

Everything else hangs off this spine. T007 is the single most blocking task in the slice.

### Parallel opportunities

- Phase 1: T001–T003 are independent files
- Phase 2: T004–T006 together; then T008 and T009 together
- US1: T011–T016 are all in one file but independent cases — write them together, then T017
- Polish: T045–T049 are five different files

### Manual and observation tasks cannot be parallelised with code

T019–T023, T029–T030 and T040 are performed by the author in external consoles. T025–T028,
T031–T039, T043–T044 and T052 require a deployed system. Neither can be batched with implementation
work, and both must be sequenced after the deployment they inspect.

---

## Implementation Strategy

### MVP first (User Story 1 only)

Setup → Foundational → US1, then **stop and validate**. At that point CareerHQ is publicly
reachable with an honest health report — demonstrable to anyone with the URL, and the substrate
every later slice ships onto. Sign-in and continuous deployment are genuine additions on top, not
prerequisites for that value.

### Incremental delivery

Setup + Foundational → US1 (demo: open the URL from a phone) → US2 (demo: sign in on the public
site) → US3 (demo: merge a change and watch it appear) → Polish.

### Notes

- **The Google OAuth client must exist before T029**, but nothing earlier depends on it. The
  frontend domain does not exist until T020, so T029 cannot be done in advance — this ordering is
  forced, not chosen.
- **Commit after each task or logical group**; the branch is `002-deployment`.
- **T042 is the task most likely to be skipped and the one most worth doing.** Watching the gate
  fail is the only evidence it works.
- **If the diff grows an application feature, stop.** FR-025 and SC-009 exist to catch that, and
  T050 is the checkpoint.
