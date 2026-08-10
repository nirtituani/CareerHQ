# Phase 0 Research: Platform Foundation

**Date**: 2026-08-05 | **Feature**: [spec.md](./spec.md)

All open questions from the Technical Context are resolved below. Versions were verified against
PyPI and npm on 2026-08-05 rather than recalled.

---

## R-001: Dependency versions

**Decision**: Pin major/minor, allow patch updates. Backend: FastAPI 0.141, SQLAlchemy 2.0,
Alembic 1.19, Pydantic 2.13, pydantic-settings 2.14, Authlib 1.7, psycopg 3.3, pytest 9.1,
Ruff 0.16, mypy 2.3. Frontend: Next.js 16.3, React 19.2, TypeScript 7.0, Tailwind CSS 4.3.

**Rationale**: Queried the registries directly; training-recalled versions would be months stale.
Two of these carry real migration cost if assumed wrong — TypeScript 7 is the Go-based compiler
rewrite, and Tailwind 4 moved configuration from `tailwind.config.js` into CSS `@theme` blocks.
Scaffolding written against the older conventions would need rework.

**Alternatives considered**: Unpinned latest (breaks reproducibility, violates the constitution's
reproducible-environment goal); exact pins including patch (creates constant dependency churn).

---

## R-002: Authentication mechanism

**Decision**: Google OAuth 2.0 via Authlib on the backend. On successful callback the backend
issues a signed JWT stored in an **HttpOnly, SameSite=Lax, Secure-in-production cookie**. No
server-side session table.

**Rationale**: The user has already shipped this exact flow in JobTracker with Authlib, so the
GCP client setup and redirect-URI handling are familiar. HttpOnly satisfies FR-016 (not readable
by browser scripts). A stateless JWT keeps the API horizontally scalable per the system design's
"stateless APIs" quality attribute, and avoids a session table we would have to expire and clean.

**Trade-off accepted**: A stateless JWT cannot be revoked before it expires. Acceptable for a
7-day personal-productivity session; if instant revocation is needed later, a Redis deny-list can
be added without changing the cookie contract (Redis is already provisioned).

**Alternatives considered**: Server-side sessions in Redis (revocable, but adds a request-path
dependency on Redis for every call in a slice that otherwise doesn't need it); `Authorization`
header + localStorage token (rejected — readable by scripts, violates FR-016).

---

## R-003: Frontend ↔ backend origin

**Decision**: Next.js `rewrites()` proxies `/api/*` to the backend container. The browser only
ever talks to `localhost:3000`.

**Rationale**: Makes every request same-origin, so there is no CORS configuration and no
cross-origin cookie edge cases in dev or production. The OAuth redirect URI points at the proxied
path, so one URI works in both environments.

**Alternatives considered**: Direct cross-origin calls with `CORSMiddleware` + `credentials:
"include"` — works (cookies ignore port, so `localhost:3000` → `localhost:8000` is same-site),
but adds an origin allowlist to maintain and a class of bugs that only appear once deployed.

---

## R-004: Preventing the duplicate-profile race (SC-004)

**Decision**: Enforce at the database, not in application code. `users.google_sub` gets a UNIQUE
constraint; `professional_profiles.user_id` gets a UNIQUE constraint. First sign-in performs an
idempotent upsert (`INSERT ... ON CONFLICT DO NOTHING` then `SELECT`) inside one transaction.

**Rationale**: A check-then-insert in Python is a textbook race — two concurrent first sign-ins
both read "no user exists" and both insert. Only the database can serialize this. This directly
protects Constitution Principle I (exactly one profile per user), so it is an invariant, not an
optimization.

**Test**: An integration test fires two concurrent provisioning calls for the same Google subject
and asserts exactly one user row and one profile row afterward.

---

## R-005: Applying migrations at startup

**Decision**: The backend container's entrypoint runs `alembic upgrade head` before starting
Uvicorn. The `vector` extension is created in the first migration via `CREATE EXTENSION IF NOT
EXISTS vector`, using the `pgvector/pgvector:pg17` image.

**Rationale**: FR-003 requires schema to be current with no manual step. Enabling the extension in
a migration (rather than a database init script) means it is versioned and reproducible on any
Postgres that has the extension available.

**Alternatives considered**: `Base.metadata.create_all()` (no version history, no downgrade path,
diverges from Alembic immediately); a `docker-entrypoint-initdb.d` SQL script (runs only on first
volume creation, so a developer with an existing volume silently lacks the extension).

---

## R-006: Health check semantics

**Decision**: Two endpoints. `GET /api/health` is a liveness probe returning `{"status": "ok"}`
without touching dependencies. `GET /api/health/ready` checks Postgres (`SELECT 1`), Redis
(`PING`), and object storage (bucket head) concurrently and returns per-dependency status,
responding 503 when any is unreachable.

**Rationale**: FR-002 and SC-008 require naming the failing dependency. Splitting liveness from
readiness prevents a container restart loop when a dependency is merely slow, and gives Docker
Compose a cheap healthcheck target.

---

## R-007: Configuration and fail-fast

**Decision**: A single `Settings(BaseSettings)` model from pydantic-settings, instantiated once at
import. Required secrets are typed without defaults so a missing value raises `ValidationError`
during startup. Ship `.env.example`; `.env` is gitignored.

**Rationale**: FR-005 and FR-006. Pydantic's validation error already names the missing field, so
"fail fast with a message naming the missing value" comes for free rather than needing custom
checks.

---

## R-008: LLM and embeddings configuration seam (no AI code this slice)

**Decision**: Add settings fields only — `llm_provider_model` defaulting to
`anthropic/claude-opus-5` (LiteLLM's `provider/model` naming), `anthropic_api_key` as optional,
and `embedding_model` defaulting to a local sentence-transformers model. No client, no
LangGraph, no LiteLLM import in this slice.

**Rationale**: Confirmed against the current Claude model reference: `claude-opus-5` is the
current default Opus model ID (1M context), with `claude-sonnet-5` as the cheaper alternative.
Model IDs carry **no date suffix** — appending one produces a 404. Recording the correct default
now avoids a stale ID being copied forward into the resume-tailoring slice.

Embeddings default to local sentence-transformers because Anthropic has no embeddings endpoint —
this is the design-doc correction noted in the constitution. It keeps the foundation runnable with
zero API keys.

**Deferred to the resume-tailoring slice**: adaptive thinking configuration, effort levels, and
structured-output schemas. Noted here only so the settings names don't have to change later.

---

## R-009: Testing strategy for 80% coverage (SC-007)

**Decision**: `pytest` + `pytest-asyncio` + `httpx.ASGITransport` for API tests against the real
app object. Integration tests run against the Compose Postgres via a per-test transaction that is
rolled back. The Google OAuth exchange is faked by overriding the FastAPI dependency that returns
verified claims — the callback route, provisioning logic, and cookie issuance are all exercised
for real; only Google's network call is substituted.

**Rationale**: 80% on a scaffolding slice is only reachable if provisioning and auth are testable
without a browser. Injecting claims at the dependency boundary keeps the code under test real
while removing the external dependency.

**Alternatives considered**: Testcontainers (cleaner isolation, but a second way to start
Postgres alongside Compose, and slower on every run); mocking the SQLAlchemy session (would not
catch the constraint violations R-004 depends on, so the race test would be meaningless).
