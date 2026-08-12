# Implementation Plan: Deployment

**Branch**: `002-deployment` | **Date**: 2026-08-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-deployment/spec.md`

## Summary

Put CareerHQ on a public HTTPS address, built from the same images that run locally, and redeploy
it whenever work merges — with the existing quality gates deciding whether that happens.

The planning phase changed the shape of this slice once. The specification anticipated a
readiness-probe change; reading the configuration showed the real blocker sits one layer earlier.
**`REDIS_URL` and the four S3 settings are required fields with no defaults, so the backend cannot
start at all without a cache and object storage it does not use.** The readiness endpoint is
downstream of that. Making both dependencies optional — following the pattern already written into
the same file for Google OAuth — is the actual code change, and honest readiness follows from it.

Three decisions carry the rest. Deploys are gated by **Railway's own Wait-for-CI setting** rather
than a GitHub Actions workflow holding a deploy token, because the host already provides the
behaviour and the alternative moves a production credential into a second system. Migrations run
as a **pre-deploy command**, which the platform will not proceed past if it fails. And the
backend's **health check points at readiness**, which makes honest readiness load-bearing: report
an undeployed dependency as failed and the deployment never goes live.

One requirement resists ordinary implementation. FR-015 demands that HSTS, `Secure`, and
`https_only` be confirmed by **observing real responses and real cookies from the deployed site**.
`is_production` has never been true anywhere, so reading the code proves nothing about it.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7.0 (frontend) — unchanged

**Primary Dependencies**: No new runtime dependencies. This slice adds configuration and
infrastructure, not libraries.

**Storage**: PostgreSQL 18.4 with pgvector 0.8.6 — already provisioned and verified on the
deployed host, and matched locally. Cache and object storage are **deliberately absent**.

**Testing**: pytest for the configuration and readiness changes; observation against the deployed
site for FR-015, which no test suite can satisfy.

**Target Platform**: Railway — two services (frontend public, backend private) plus the existing
`pgvector` service, in one project.

**Project Type**: Web application — existing backend and frontend, no structural change.

**Performance Goals**: Not a driver. The health check must answer inside Railway's healthcheck
timeout; the existing 2-second probe budget already satisfies that.

**Constraints**: No user-visible behaviour change (FR-025). No new secrets in the repository. The
database must remain unreachable from the public internet. One public origin, so no CORS surface.

**Scale/Scope**: One region, one replica per service, single-digit users. Roughly 40 lines of
backend change, two configuration files, one documentation section.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Applies here | How this plan satisfies it |
|---|---|---|
| I. Profile is single source of truth | Preserved, not exercised | No schema change. The UNIQUE constraint that enforces it deploys unchanged, and SC-002 re-proves it on the deployed system |
| II. Human-in-the-loop | Not exercised | No AI acts in this slice |
| III. Explainable and honest AI | Not exercised | No AI output. *Note the adjacent principle this slice does exercise: the readiness endpoint must not claim a result it did not produce (FR-006). Same honesty, different subject* |
| IV. Immutable history | **Constrains the rollback design** | Application rollback is cheap and schema rollback is conditional, but business data is immutable and is **not** rolled back. FR-024 requires this stated plainly in the documentation rather than discovered during an incident |
| V. AI is a platform capability | Preserved | No provider client ships. The AI configuration fields deploy as unset values |
| VI. Structured data first | Not exercised | No new data |
| VII. Test-first quality | **Yes** | The configuration and readiness changes get failing tests first. Coverage stays ≥80%; ruff and mypy stay clean. FR-015 is the documented exception — it is satisfied by observation, and the plan says so rather than pretending a test covers it |

**Result: PASS.** No violations, so Complexity Tracking is omitted.

The one thing worth flagging to a reviewer: making required configuration optional slightly
weakens the fail-fast property slice 001 built deliberately. That is examined in Phase 1 rather
than waved through — the mitigation is that the accessors fail loudly on use, so the failure moves
from startup to first use rather than disappearing.

## Project Structure

### Documentation (this feature)

```text
specs/002-deployment/
├── spec.md              # What and why
├── plan.md              # This file
├── research.md          # Phase 0 — six decisions, R1 reshaped the slice
├── data-model.md        # Phase 1 — no new entities; the observable contract that does change
├── quickstart.md        # Phase 1 — deploy, observe, roll back
├── contracts/
│   └── readiness.md     # The readiness response contract, including `not_configured`
└── tasks.md             # Phase 2 — created by /speckit-tasks, not here
```

### Source code (repository root)

Only these paths change:

```text
backend/
├── src/careerhq/
│   ├── config.py                      # cache + object storage become optional
│   ├── api/routes/health.py           # probe what is configured; report honestly
│   └── infrastructure/
│       ├── redis.py                   # fail loudly when unconfigured
│       └── storage.py                 # fail loudly when unconfigured
└── tests/
    ├── unit/test_config.py            # optional-configuration cases
    └── integration/test_health.py     # not_configured reporting

railway.toml                           # new — pre-deploy, healthcheck, as config-as-code
.env.example                           # cache and object storage documented as optional
README.md / quickstart                 # deployment, logs, rollback
```

**Structure Decision**: Unchanged. This slice deploys the existing two-part application; it
introduces no new module, layer, or service. If the diff grows a third component, the slice has
drifted from FR-025.

## Design outline

Detail lives in the Phase 1 artifacts; this is the shape.

### The code change

1. **Configuration** — `redis_url` and the four `s3_*` fields become `| None = None`, joined by
   `cache_configured` and `object_storage_configured` properties beside the existing
   `google_oauth_configured`. `DATABASE_URL` and `SESSION_SECRET` stay required: those are not
   optional in any environment, and losing the startup crash on a missing session secret would
   undo a T068 protection.
2. **Accessors** — `redis.py` and `storage.py` raise a specific, named error when asked for a
   client that is not configured, mirroring how the auth routes already behave for absent Google
   credentials.
3. **Readiness** — the probe set is derived from configuration rather than hardcoded. Configured
   dependencies are probed and report `ok` or `error`; unconfigured ones report `not_configured`.
   Overall status considers checked dependencies only. Failure disclosure is unchanged: exception
   class to the caller, driver detail to the log.

### The infrastructure

4. **Two Railway services** from the existing Dockerfiles. Frontend public, backend private,
   `BACKEND_URL` pointing at the backend's internal address.
5. **`railway.toml`** carrying the pre-deploy command and healthcheck path, so the deployment
   configuration is reviewable in the repository rather than living only in a web console.
6. **Wait for CI** enabled, so gates decide whether a merge deploys.
7. **Secrets** set in Railway: `SESSION_SECRET`, the Google OAuth pair, `PUBLIC_BASE_URL`,
   `ENVIRONMENT=production`, and `DATABASE_URL` referencing the existing database service.

### The manual step

8. **The Google OAuth redirect URI.** Once Railway generates the frontend domain, the exact value
   `https://<frontend-domain>/api/auth/callback` must be added to the OAuth client's authorized
   redirect URIs. This cannot be automated and must not be guessed — the tasks state the value and
   where it goes.

### The observation

9. **FR-015** — confirm against the deployed site, not the source: the `Strict-Transport-Security`
   header present on a real response, the session cookie carrying `Secure` and `HttpOnly` as the
   browser records it, and a plain-HTTP request arriving at HTTPS. This is the first execution of
   that configuration in the project's life.

## Risks carried into implementation

| Risk | Symptom | Where it is recorded |
|---|---|---|
| Railway's private network is IPv6-only | Frontend loads; every `/api/*` request fails. Invisible locally, where Docker is IPv4 | research.md R6 |
| Wait for CI waits on *all* check suites | A merge silently never deploys, with this repository's CI green | research.md R2 |
| Optional configuration weakens fail-fast | A missing cache URL surfaces at first use rather than at startup | Constitution Check, mitigated by loud accessors |
| Health check points at readiness | A readiness bug blocks *all* deployments, not just reporting | research.md R4 — deliberate, and the reason honesty matters |

## Post-design constitution re-check

Re-evaluated after Phase 1. **Still PASS.** No new entities, no AI execution, no data-ownership
change, no endpoint accepting a client-supplied identity. The rollback asymmetry required by
Principle IV is carried into `quickstart.md` as documentation rather than left implicit, which was
the one place this slice could have violated a principle by omission.
