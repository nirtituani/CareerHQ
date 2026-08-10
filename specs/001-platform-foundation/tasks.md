---
description: "Task list for Platform Foundation implementation"
---

# Tasks: Platform Foundation

**Input**: Design documents from `/specs/001-platform-foundation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md)

**Tests**: Included. The spec requires them (FR-020 through FR-023, SC-007) and Constitution
Principle VII makes 80% backend coverage a merge gate, so test tasks are not optional here.

**Organization**: Grouped by user story so each is independently implementable and demo-able.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1 / US2 / US3, mapping to the user stories in spec.md
- Every task names the exact file it touches

## Path Conventions

Web application layout per plan.md: `backend/src/careerhq/`, `frontend/src/`, with
`docker-compose.yml` and `.github/` at the repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository scaffolding and tooling. Nothing runs yet.

- [x] T001 Create the directory tree from plan.md: `backend/src/careerhq/{api/routes,application,domain,infrastructure}/`, `backend/tests/{unit,integration}/`, `backend/alembic/versions/`, `frontend/src/{app,components,lib}/`
- [x] T002 [P] Create `backend/pyproject.toml` pinning FastAPI 0.141, SQLAlchemy 2.0, Alembic 1.19, Pydantic 2.13, pydantic-settings 2.14, Authlib 1.7, psycopg 3.3, redis 8.1, boto3, pyjwt, uvicorn; dev group pytest 9.1, pytest-asyncio, pytest-cov, httpx, ruff 0.16, mypy 2.3
- [x] T003 [P] Configure Ruff (format + lint, line length 100) and mypy (strict on `src/careerhq`) in `backend/pyproject.toml`
- [x] T004 [P] Configure pytest and coverage in `backend/pyproject.toml`: asyncio mode auto, `--cov=careerhq`, `testpaths = ["tests"]`
- [x] T005 [P] Initialize the frontend in `frontend/` with Next.js 16.3 App Router, TypeScript 7.0, Tailwind CSS 4.3 (`@theme` in `src/app/globals.css` — Tailwind 4 has no `tailwind.config.js`)
- [x] T006 [P] Initialize shadcn/ui in `frontend/` — `components.json`, the `cn` helper in `src/lib/utils.ts`, and `clsx`/`tailwind-merge`/`lucide-react` installed. ⚠️ **The four components (`button`, `avatar`, `dropdown-menu`, `skeleton`) are added in User Story 2 when the shell first consumes them** — adding unused components now would be dead code that lint would flag
- [x] T007 [P] Add the proxy rewrite in `frontend/next.config.ts`: `/api/:path*` → `${BACKEND_URL}/api/:path*` (research.md R-003)
- [x] T008 [P] Write `backend/Dockerfile` (python:3.12-slim, non-root user, uv or pip install, entrypoint script placeholder)
- [x] T009 [P] Write `frontend/Dockerfile` (**node:24-alpine** — matching the local Node version rather than the 22 originally planned, dev target with hot reload, production standalone target)
- [x] T010 [P] Write `.env.example` covering `DATABASE_URL`, `REDIS_URL`, `S3_*`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, `SESSION_TTL_DAYS`, `LLM_PROVIDER_MODEL`, `ANTHROPIC_API_KEY`, `EMBEDDING_MODEL` — with comments, no real values
- [x] T011 [P] Add `backend/.dockerignore` and `frontend/.dockerignore`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The application skeleton every story needs.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T012 Implement `Settings(BaseSettings)` in `backend/src/careerhq/config.py` — required secrets typed without defaults so a missing value raises at import (research.md R-007, FR-005, FR-006). Include the AI configuration seam with no client code behind it: `llm_provider_model` defaulting to `anthropic/claude-opus-5`, optional `anthropic_api_key`, and `embedding_model` defaulting to a local sentence-transformers model (research.md R-008)
- [x] T013 [P] Implement structured JSON logging plus an `X-Request-ID` middleware in `backend/src/careerhq/infrastructure/logging.py` — generate an ID when absent, echo it in the response header, bind it to every log record (FR-008)
- [x] T014 [P] Implement the async engine, `async_sessionmaker`, and `get_db` dependency in `backend/src/careerhq/infrastructure/database.py`
- [x] T015 Implement the app factory in `backend/src/careerhq/main.py` — instantiate FastAPI with `docs_url="/api/docs"`, attach the logging middleware, register routers
- [x] T016 Scaffold Alembic in `backend/alembic.ini` and `backend/alembic/env.py` configured for async SQLAlchemy and reading the URL from `Settings`
- [x] T017 [P] Write shared fixtures in `backend/tests/conftest.py`: app instance, `httpx.AsyncClient` over `ASGITransport`, and a database session wrapped in a rolled-back transaction (research.md R-009)

**Checkpoint**: The app imports and starts, but serves nothing yet.

---

## Phase 3: User Story 1 — Start the whole platform with one command (Priority: P1) 🎯 MVP

**Goal**: `docker compose up` brings up every service and the health check reports each dependency
by name.

**Independent Test**: From a clean clone with configuration filled in, run the documented startup
command and confirm the health endpoint reports the system and all three dependencies healthy, and
that the API documentation page renders.

### Tests for User Story 1

> Write these first and confirm they fail before implementing.

- [x] T018 [P] [US1] Test `GET /api/health` returns 200 with `status: ok` in `backend/tests/integration/test_health.py`
- [x] T019 [P] [US1] Test `GET /api/health/ready` returns 200 and names database, cache, and object_storage when all reachable, in `backend/tests/integration/test_health.py`
- [x] T020 [P] [US1] Test readiness returns 503 and names the failing dependency, **parameterized across all three** (database, cache, object_storage) so each is proven independently, in `backend/tests/integration/test_health.py` (SC-008 says 100% of outage cases, so one case is not enough)
- [x] T021 [P] [US1] Test that constructing `Settings` without a required secret raises `ValidationError` naming the field, in `backend/tests/unit/test_config.py` (FR-006)

### Implementation for User Story 1

- [x] T022 [P] [US1] Implement the Redis client and `ping()` probe in `backend/src/careerhq/infrastructure/redis.py`
- [x] T023 [P] [US1] Implement the S3-compatible client and bucket-head probe in `backend/src/careerhq/infrastructure/storage.py`
- [x] T024 [US1] Implement `GET /api/health` and `GET /api/health/ready` in `backend/src/careerhq/api/routes/health.py` — probes run concurrently via `asyncio.gather`, each with a 2 s timeout, per-dependency latency reported, 503 when any fails; report `version` read from the installed package metadata (contracts/api.md)
- [x] T025 [US1] Register the health router and set OpenAPI title/version in `backend/src/careerhq/main.py` (FR-007)
- [x] T026 [US1] Write migration `backend/alembic/versions/0001_extensions.py` — `CREATE EXTENSION IF NOT EXISTS vector` and `pgcrypto`, with a working downgrade (FR-004)
- [x] T027 [US1] Write `backend/entrypoint.sh` running `alembic upgrade head` then `uvicorn`, and wire it as the Dockerfile entrypoint (FR-003)
- [x] T028 [US1] Add a `minio-init` service to `docker-compose.yml` that creates the configured bucket and exits — the readiness probe heads the bucket, so it must exist *before* the backend starts or readiness fails on a first run
- [x] T029 [US1] Write the rest of `docker-compose.yml`: postgres (`pgvector/pgvector:pg17`), redis, minio, backend, frontend — named volumes, a healthcheck on each long-running service, and `depends_on` where backend waits on postgres/redis `service_healthy` and on `minio-init` `service_completed_successfully`
- [x] T030 [US1] Run the User Story 1 section of [quickstart.md](./quickstart.md) end to end, including the fail-fast and dependency-outage checks

**Checkpoint**: The platform starts with one command and honestly reports its own health. This is
the MVP — everything after this builds on a running system.

---

## Phase 4: User Story 2 — Sign in and reach a personal workspace (Priority: P2)

**Goal**: Google sign-in provisions the account and its single empty Professional Profile, lands
the user on a personalized dashboard, and keeps every user's data isolated.

**Independent Test**: Visit the app signed out, complete Google sign-in, confirm arrival at an
empty workspace showing your identity, sign out, and confirm the workspace is unreachable.

### Tests for User Story 2

- [x] T031 [P] [US2] Test first sign-in creates exactly one user and one profile, in `backend/tests/integration/test_provisioning.py` (FR-010)
- [x] T032 [P] [US2] Test a returning user reuses the existing account and creates no second profile, in `backend/tests/integration/test_provisioning.py` (FR-011)
- [x] T033 [P] [US2] Test **concurrent** first sign-in for the same Google subject yields exactly one user and one profile, in `backend/tests/integration/test_provisioning.py` (SC-004, research.md R-004)
- [x] T034 [P] [US2] Test unauthenticated access is refused, in `backend/tests/integration/test_auth.py` (FR-014, SC-003). Two layers: (a) `GET /api/auth/me` and `GET /api/profile` each return 401 with no cookie, an expired cookie, and a tampered cookie; (b) **enumerate `app.routes`** and assert every route outside an explicit public allowlist (`/api/health*`, `/api/auth/google/*`, `/api/docs`, `/api/openapi.json`) returns 401 unauthenticated — so a future endpoint added without auth fails CI instead of shipping open
- [x] T035 [P] [US2] Test user A's session cannot read user B's profile, in `backend/tests/integration/test_isolation.py` (SC-005, FR-015)
- [x] T036 [P] [US2] Test logout expires the cookie and is safe to call twice, in `backend/tests/integration/test_auth.py`
- [x] T037 [P] [US2] Test the callback with a denied/cancelled consent redirects to login with an error and creates no account, in `backend/tests/integration/test_auth.py`
- [x] T038 [P] [US2] Test the callback rejects a missing or mismatched `state` with 400, in `backend/tests/integration/test_auth.py`

### Implementation for User Story 2

- [x] T039 [P] [US2] Define `User` and `ProfessionalProfile` SQLAlchemy models in `backend/src/careerhq/domain/models.py` per [data-model.md](./data-model.md), including both UNIQUE constraints
- [x] T040 [P] [US2] Define Pydantic response schemas (`UserOut`, `ProfileOut`) in `backend/src/careerhq/domain/schemas.py` matching contracts/api.md
- [x] T041 [US2] Write migration `backend/alembic/versions/0002_users_profiles.py` creating both tables with `UNIQUE(google_sub)` and `UNIQUE(user_id)` declared inline, plus a working downgrade
- [x] T042 [P] [US2] Implement JWT encode/decode and cookie set/clear helpers in `backend/src/careerhq/infrastructure/security.py` — HttpOnly, SameSite=Lax, Secure when not local, Max-Age from `SESSION_TTL_DAYS` (FR-016)
- [x] T043 [P] [US2] Define the verified-claims seam in `backend/src/careerhq/api/deps.py`: a `get_verified_google_claims` dependency that performs the Authlib token exchange and ID-token verification, returning a typed `GoogleClaims` object. **The callback route must depend on this rather than calling Authlib inline** — overriding it is how T031–T033 and T037 exercise real provisioning, cookie issuance, and redirect logic without a network call to Google (research.md R-009)
- [x] T044 [US2] Implement idempotent provisioning in `backend/src/careerhq/application/provision_user.py` — `INSERT ... ON CONFLICT DO NOTHING` then select, user and profile in one transaction (FR-010, FR-011)
- [x] T045 [US2] Implement `GET /api/auth/google/login` in `backend/src/careerhq/api/routes/auth.py` — Authlib client, `state` in a short-lived HttpOnly cookie, reject absolute `next` values (contracts/api.md)
- [x] T046 [US2] Implement `GET /api/auth/google/callback` in `backend/src/careerhq/api/routes/auth.py` — validate state, resolve claims via the T043 dependency, call provisioning, issue the session cookie, redirect
- [x] T047 [US2] Implement the `get_current_user` dependency in `backend/src/careerhq/api/deps.py` — decode the cookie, load the user, raise 401 on any failure including a `sub` that no longer exists
- [x] T048 [US2] Implement `GET /api/auth/me` and `POST /api/auth/logout` in `backend/src/careerhq/api/routes/auth.py`
- [x] T049 [US2] Implement `GET /api/profile` in `backend/src/careerhq/api/routes/profile.py` — resolves the profile from the session only; no route accepts a client-supplied ID (FR-015)
- [x] T050 [P] [US2] Implement the typed fetch wrapper in `frontend/src/lib/api.ts` — same-origin requests, 401 handling, typed responses
- [x] T051 [P] [US2] Build the sign-in page at `frontend/src/app/login/page.tsx` with a "Continue with Google" action and an error state for a declined consent
- [x] T052 [US2] Build the authenticated shell in `frontend/src/components/app-shell.tsx` and `frontend/src/components/user-menu.tsx` — navigation plus name/email/avatar and a sign-out action (FR-017)
- [x] T053 [US2] Build the empty dashboard at `frontend/src/app/dashboard/page.tsx` stating no data exists yet and what will appear there (FR-018)
- [x] T054 [US2] Add the route guard in `frontend/src/middleware.ts` redirecting unauthenticated visitors from protected paths to `/login` (FR-014). This checks cookie *presence* only — middleware has no access to the signing secret, so an expired or forged cookie renders the page and is then refused by the API. Authorization lives at the API boundary; the guard is a redirect convenience, not a security control
- [x] T055 [US2] Add a non-technical API-unreachable state that recovers automatically once the backend is healthy, in `frontend/src/components/api-unavailable.tsx` and the dashboard route (FR-019)
- [x] T056 [US2] Run the User Story 2 section of [quickstart.md](./quickstart.md), including the database row-count check and the HttpOnly cookie inspection

**Checkpoint**: A real person can sign in and reach their own workspace. Stories 1 and 2 both work
independently.

---

## Phase 5: User Story 3 — Every change is automatically checked (Priority: P3)

**Goal**: Style, type, test, and build checks run on every push and fail loudly with specifics.

**Independent Test**: Push a branch containing a deliberate style violation, type error, and
failing test; confirm the pipeline fails and names each problem; fix and confirm it passes.

- [x] T057 [P] [US3] Configure Vitest and Testing Library in `frontend/vitest.config.ts` and add a rendering test for the app shell in `frontend/src/components/__tests__/app-shell.test.tsx`
- [x] T058 [P] [US3] Add a Playwright smoke test covering the signed-out redirect to login in `frontend/e2e/auth.spec.ts`
- [x] T059 [P] [US3] Add `lint`, `test`, and `build` scripts to `frontend/package.json`
- [x] T060 [US3] Enforce the coverage floor with `--cov-fail-under=80` in `backend/pyproject.toml` (SC-007)
- [x] T061 [US3] Write `.github/workflows/ci.yml` — backend job (ruff format --check, ruff check, mypy, pytest with a Postgres service container) and frontend job (lint, test, build), both on push and pull request (FR-020, FR-021)
- [x] T062 [US3] Document the equivalent local commands in `README.md` so developers get identical results to CI (FR-022)
- [x] T063 [US3] Verify the pipeline actually fails: push a branch with a deliberate formatting error, an unannotated function, and a failing assertion; confirm each is named; then fix and confirm green

**Checkpoint**: All three stories are independently functional and the work is protected from
regression.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T064 [P] Write `README.md` — what CareerHQ is, prerequisites, the one-command start, the local check commands, and links to the spec artifacts
- [x] T065 [P] Correct the embeddings section of `docs/06_Technology_Stack.md` — the interface is configurable with local sentence-transformers as the default, because Anthropic provides no embeddings endpoint (constitution correction) ✅ Also named Anthropic Claude as the primary LLM provider in the section immediately above, which listed three providers with no primary and so contradicted the corrected embeddings text
- [x] T066 [P] Fill in the empty `docs/05_Implementation_Plan.md` — point to the `specs/` artifacts as the executable plan and record the six-slice roadmap ✅ **Pulled forward out of the polish phase and completed before implementation** — a roadmap is an orientation document, and orientation is worth more at the start than at the end
- [x] T067 [P] Complete the truncated sections of `docs/04_System_Design.md` — Knowledge Platform, deployment, security, and observability ✅ The document stopped at section 15; all four were missing entirely rather than half-written. Added as sections 16–19, each with a diagram, purpose, responsibilities, and design decisions, and each ending with an explicit **Status** line saying whether it is built or designed — security and observability are built and verified in this slice, the Knowledge Platform arrives in 004, deployment in 002. The hosting provider is left as an open decision with an ADR due when slice 002 starts, rather than invented here
- [x] T068 Review cookie and header security: confirm `HttpOnly`, `SameSite=Lax`, `Secure` outside local, and that no secret appears in logs or error responses ✅ **Cookies were already correct** — both the session cookie and Authlib's OAuth state cookie carry `HttpOnly`, `SameSite=Lax`, and `Secure`/`https_only` tied to `is_production`. The review found three real gaps instead: (1) pydantic echoes the rejected input in its validation message, so a too-short `SESSION_SECRET` was printed **in full** in the container startup log — `get_settings()` now rebuilds the message from field names and error types, withholding the value for any `SecretStr` field; (2) `/api/health/ready` returned the driver's exception text to an **unauthenticated** caller, which for a real PostgreSQL failure names the internal IP, port, and database user — the body now carries the exception class only, with the full detail kept in the log; (3) no response carried `X-Content-Type-Options`, `X-Frame-Options`, or `Referrer-Policy` — a `SecurityHeadersMiddleware` now adds them to every response including errors, with HSTS added only in production
- [ ] T069 Run the whole of [quickstart.md](./quickstart.md) from a fresh clone on a clean Docker state and fix anything that does not match

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: needs Setup — blocks every user story
- **US1 (Phase 3)**: needs Foundational
- **US2 (Phase 4)**: needs Foundational. Technically independent of US1's health endpoints, but in
  practice you want US1's Compose stack running to exercise sign-in against a real database
- **US3 (Phase 5)**: needs Foundational. CI is more useful once there is code to check, so it
  lands after US1 and US2 in a solo build
- **Polish (Phase 6)**: after the stories you intend to ship

### Within each story

Tests before implementation. Models before services, services before endpoints, backend before the
frontend that consumes it.

### Critical path

T012 (settings) → T015 (app factory) → T024 (health) → T029 (compose) → T041 (schema) → T043
(claims seam) → T044 (provisioning) → T046 (callback) → T053 (dashboard). Everything else hangs
off this spine.

### Parallel opportunities

- Phase 1: T002–T011 are all independent files
- Phase 2: T013, T014, and T017 can run alongside each other after T012
- US1: all four tests (T018–T021) in parallel; then T022 and T023 in parallel
- US2: all eight tests (T031–T038) in parallel; then T039, T040, T042, T050, T051 in parallel
- US3: T057, T058, T059 in parallel

---

## Parallel Example: User Story 2

```bash
# Write all eight tests together — they touch three separate files and must fail first:
Task: "Test first sign-in creates one user and one profile in backend/tests/integration/test_provisioning.py"
Task: "Test returning user creates no second profile in backend/tests/integration/test_provisioning.py"
Task: "Test concurrent first sign-in yields one user and one profile in backend/tests/integration/test_provisioning.py"
Task: "Test unauthenticated requests return 401 in backend/tests/integration/test_auth.py"
Task: "Test cross-user isolation in backend/tests/integration/test_isolation.py"

# Then the independent building blocks:
Task: "Define User and ProfessionalProfile models in backend/src/careerhq/domain/models.py"
Task: "Define response schemas in backend/src/careerhq/domain/schemas.py"
Task: "Implement JWT and cookie helpers in backend/src/careerhq/infrastructure/security.py"
Task: "Implement the fetch wrapper in frontend/src/lib/api.ts"
Task: "Build the sign-in page in frontend/src/app/login/page.tsx"
```

Note that T043 (the verified-claims seam) is **not** parallelizable with the tests above — the
tests override it, so it has to exist first. It is the one task in this phase that gates the rest.

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **stop and validate** against the
quickstart. At that point you have a reproducible, self-reporting environment — genuinely useful
on its own, and the thing every later slice needs.

### Incremental delivery

Setup + Foundational → US1 (demo: one command, all healthy) → US2 (demo: sign in, land on your
dashboard) → US3 (demo: CI catches a deliberate break) → Polish.

### Notes

- The Google OAuth client must exist before T056 can be verified, but not before any earlier task
  — the T043 claims seam makes the whole backend auth flow testable without it. Create it while
  Phase 1–3 work is underway so it never lands on the critical path.
- Commit after each task or logical group; the branch is `001-platform-foundation`.
- Two migrations rather than one: `0001_extensions` belongs to US1 (environment readiness) and
  `0002_users_profiles` to US2 (identity). This keeps each story independently shippable and
  refines the single-migration note in data-model.md.
