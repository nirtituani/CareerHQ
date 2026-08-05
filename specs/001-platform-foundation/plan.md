# Implementation Plan: Platform Foundation

**Branch**: `001-platform-foundation` | **Date**: 2026-08-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-platform-foundation/spec.md`

## Summary

Stand up the running skeleton every later CareerHQ slice builds on: a Docker Compose environment
(Postgres with pgvector, Redis, MinIO), a layered FastAPI backend with versioned migrations and a
dependency-aware health check, Google OAuth sign-in that provisions a user and their single empty
Professional Profile on first login, a Next.js authenticated shell with an empty dashboard, and
CI that runs lint, type checks, and tests on every change.

The two decisions that shape the implementation: the **one-profile-per-user invariant is enforced
by database UNIQUE constraints**, not application checks, because concurrent first sign-ins would
defeat any check-then-insert; and the **frontend proxies `/api/*` to the backend**, making every
request same-origin so there is no CORS surface and no cross-origin cookie handling.

No AI code ships in this slice — only named configuration fields so the resume-tailoring slice
has a seam to plug into.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7.0 (frontend)

**Primary Dependencies**: FastAPI 0.141, SQLAlchemy 2.0 (async), Alembic 1.19, Pydantic 2.13 +
pydantic-settings 2.14, Authlib 1.7, psycopg 3.3; Next.js 16.3 (App Router), React 19.2,
Tailwind CSS 4.3, shadcn/ui

**Storage**: PostgreSQL 17 with pgvector (business data), Redis 8 (cache/workflow state — never a
source of truth), MinIO (S3-compatible object storage)

**Testing**: pytest 9.1 + pytest-asyncio + httpx ASGI transport (backend, ≥80% coverage);
Vitest + Testing Library, Playwright smoke (frontend)

**Target Platform**: Linux containers via Docker Compose on a developer machine

**Project Type**: Web application — separate backend and frontend in one repository

**Performance Goals**: Not a driver for this slice. Health check answers in under 2 s including
dependency probes; sign-in completes within 30 s end to end (SC-002).

**Constraints**: Session cookie must be HttpOnly and script-unreadable; migrations apply
automatically at startup; the container must fail fast on missing configuration; no real secrets
in version control.

**Scale/Scope**: Single developer, multi-user capable. ~2 tables, ~7 endpoints, 3 frontend routes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Applies here | How this plan satisfies it |
|---|---|---|
| I. Profile is single source of truth | Yes | `professional_profiles.user_id` is UNIQUE; the profile is created in the same transaction as the user, so "user without profile" is unreachable |
| II. Human-in-the-loop | Not exercised | No AI acts in this slice; nothing to approve |
| III. Explainable and honest AI | Not exercised | No AI output |
| IV. Immutable history | Not exercised | No resumes or submissions yet |
| V. AI is a platform capability | Yes, preventively | Configuration fields only; no provider client, no LangGraph, no AI import in domain code |
| VI. Structured data first | Yes | Pydantic models at the API boundary, SQLAlchemy typed models in the domain, pgvector enabled at initialization |
| VII. Test-first quality | Yes | ≥80% backend coverage enforced in CI; Ruff and mypy must pass; the ownership-isolation and concurrent-provisioning invariants have dedicated tests |
| Tech constraints | Yes | Exactly the constitution's stack; every service containerized |
| Vertical slices | Yes | Ships demo-able end to end: clone → one command → sign in → dashboard |

**Post-design re-check**: no violations. The Complexity Tracking table is empty — nothing in this
design goes beyond the documented stack.

One design decision worth flagging as deliberate: the session is a stateless JWT rather than a
Redis-backed server session. Redis is provisioned but stays off the authentication request path.
This is a trade-off (tokens can't be revoked before expiry), accepted and recorded in
[research.md](./research.md) R-002, with the upgrade path noted.

## Project Structure

### Documentation (this feature)

```text
specs/001-platform-foundation/
├── plan.md              # This file
├── spec.md              # Requirements
├── research.md          # Phase 0 — 9 resolved decisions
├── data-model.md        # Phase 1 — users, professional_profiles, session
├── quickstart.md        # Phase 1 — run + acceptance script
├── contracts/
│   └── api.md           # Phase 1 — endpoint contracts
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 — created by /speckit-tasks, not here
```

### Source Code (repository root)

```text
backend/
├── src/careerhq/
│   ├── main.py                      # App factory, middleware, router wiring
│   ├── config.py                    # Settings (fails fast on missing values)
│   ├── api/                         # HTTP layer — no business logic
│   │   ├── deps.py                  # get_db, get_current_user
│   │   └── routes/                  # health.py, auth.py, profile.py
│   ├── application/                 # Use cases coordinating domain + infrastructure
│   │   └── provision_user.py        # Idempotent first-sign-in provisioning
│   ├── domain/                      # Business rules, no framework imports
│   │   ├── models.py                # SQLAlchemy models: User, ProfessionalProfile
│   │   └── schemas.py               # Pydantic API contracts
│   └── infrastructure/              # Technical services
│       ├── database.py              # Async engine, session factory
│       ├── redis.py                 # Client + ping
│       ├── storage.py               # S3-compatible client + bucket check
│       ├── security.py              # JWT encode/decode, cookie helpers
│       └── logging.py               # Structured logs with request correlation
├── alembic/versions/0001_foundation.py
├── tests/{unit,integration}/
├── pyproject.toml                   # deps, ruff, mypy, pytest, coverage config
└── Dockerfile

frontend/
├── src/
│   ├── app/                         # login/, dashboard/, layout.tsx, page.tsx
│   ├── components/                  # ui/ (shadcn), app-shell.tsx, user-menu.tsx
│   └── lib/api.ts                   # Typed fetch wrapper, credentials included
├── next.config.ts                   # rewrites: /api/* → backend
└── Dockerfile

docker-compose.yml                   # postgres, redis, minio, backend, frontend
.env.example
.github/workflows/ci.yml
```

**Structure Decision**: Web application layout — `backend/` and `frontend/` side by side in one
repository. The backend's four inner directories map directly to the layers in
[docs/04_System_Design.md](../../docs/04_System_Design.md) §9, with dependencies pointing inward
only: `api` → `application` → `domain`, and `infrastructure` implementing what the inner layers
declare. The `domain/` package imports no framework code, which is what keeps Principle V
enforceable later — an AI client cannot be reached from a domain module without an import that
review will catch.

## Implementation Sequence

Ordered so each step is verifiable before the next depends on it.

1. **Compose + configuration** — `docker-compose.yml`, `.env.example`, `config.py`. Verify:
   `docker compose up` starts Postgres/Redis/MinIO; a missing required value aborts startup.
2. **Backend skeleton + health** — app factory, structured logging with request IDs, both health
   endpoints. Verify: liveness and readiness respond, `/api/docs` renders, stopping Redis turns
   readiness 503 naming `cache`.
3. **Schema + migration** — models and `0001_foundation` (extensions, both tables, both UNIQUE
   constraints). Verify: `alembic upgrade head` from empty, then `downgrade base` cleanly.
4. **Auth + provisioning** — Authlib login/callback, JWT cookie issuance, idempotent
   provisioning, `/api/auth/me`, logout, `/api/profile`. Verify: the concurrency test yields one
   user and one profile; unauthenticated requests get 401.
5. **Frontend shell** — proxy rewrite, login page, app shell with user menu, empty dashboard,
   API-unreachable state. Verify: the User Story 2 walkthrough in quickstart.
6. **CI** — GitHub Actions running the same commands as local. Verify: a branch with a
   deliberate style, type, and test error fails and names each.

## Verification

Full acceptance script: [quickstart.md](./quickstart.md). The gate for calling this slice done:

- `docker compose up --build` from a clean clone reaches all-healthy (SC-001)
- Google sign-in lands on the dashboard; the database shows exactly one user and one profile after
  repeated sign-ins, including the concurrent case (SC-004)
- `/api/profile` returns 401 without a session; no endpoint accepts a client-supplied user ID
  (SC-003, SC-005)
- `pytest --cov` ≥ 80%, `ruff check`, `ruff format --check`, `mypy` all pass; frontend builds and
  tests pass (SC-006, SC-007)
- Stopping any one dependency turns readiness 503 and names it (SC-008)

## Complexity Tracking

No constitutional violations to justify.
