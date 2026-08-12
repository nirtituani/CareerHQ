# Phase 0 Research: Deployment

**Feature**: [spec.md](./spec.md) | **Branch**: `002-deployment` | **Date**: 2026-08-12

Six decisions. The first is the one that changes the shape of the slice.

---

## R1 — The backend cannot start without Redis and object storage

**This was found while planning, not while implementing, and it is the most important finding
here.** The spec anticipated a readiness-probe change. The actual blocker is one layer earlier.

`backend/src/careerhq/config.py` declares these fields with **no default**, which in
pydantic-settings means required:

```python
redis_url: str
s3_endpoint_url: str
s3_access_key: SecretStr
s3_secret_key: SecretStr
s3_bucket: str
```

A missing required field raises `ValidationError`, which `get_settings()` deliberately turns into
a startup crash naming the field. That behaviour is correct and was built on purpose in slice 001.
Its consequence here is that **a deployment without Redis and object storage cannot boot at all** —
it never reaches the readiness endpoint the spec was worried about.

### Decision

Make cache and object-storage configuration **optional**, following the pattern already
established in the same file for Google OAuth:

```python
# Optional by design. Sign-in cannot work without them, but the platform
# starts and reports healthy so the environment can be verified before a
# Google Cloud OAuth client exists.
google_client_id: str | None = None
```

That comment describes exactly this situation with a different dependency. Cache and object
storage become `| None = None`, with `cache_configured` and `object_storage_configured`
properties alongside the existing `google_oauth_configured`.

### Rationale

The precedent exists, is documented in place, and was written for the same reason: a dependency
that a *future* slice needs should not prevent the platform from starting and reporting honestly
today. Following it keeps one pattern rather than inventing a second.

### Alternatives considered

| Alternative | Rejected because |
|---|---|
| Deploy Redis and object storage after all | Directly contradicts the slice's scope. Two more services to pay for and configure, to satisfy code that nothing yet calls |
| Set dummy values (`redis://unused`) in Railway | The application would believe it has a cache, construct a client, and fail at first use. It also makes readiness lie, which FR-006 forbids |
| Separate production settings class | Two configuration schemas that must be kept in step; the difference between environments becomes structural rather than a value |

### Consequence for the accessors

`infrastructure/redis.py` and `infrastructure/storage.py` construct clients from these settings.
They must fail loudly and specifically when asked for a client that is not configured — the same
way the auth routes already do for absent Google credentials — rather than returning `None` and
pushing the problem to the caller.

---

## R2 — Gating deployment on CI

**Problem**: Railway's GitHub integration deploys on push by default. Left alone, a merge deploys
immediately and CI results arrive afterwards, which inverts FR-020.

### Decision

Enable Railway's **"Wait for CI"** setting on the services — *"trigger deployments after all
GitHub actions have completed successfully."*

### Rationale

No new code, no deployment workflow to maintain, and — importantly — **no Railway API token
stored in GitHub secrets**. The alternative moves a credential that can deploy the production
system into a second system, to reproduce behaviour the host already provides.

### Alternatives considered

| Alternative | Rejected because |
|---|---|
| GitHub Actions job that runs gates then deploys via Railway CLI | Requires a long-lived `RAILWAY_TOKEN` in GitHub secrets; more moving parts to maintain; duplicates the host's own feature |
| Deploy only from tags | Adds a manual release step, defeating FR-019's "without further human action" |
| Accept deploy-then-test | Violates FR-020 outright. A broken build reaches users and is rolled back afterwards |

### Known caveat, to be recorded rather than discovered

Wait for CI waits on **all** GitHub check suites on the commit, not only this repository's CI
workflow. A check suite from an unrelated installed app — a stale integration, a coverage
service — can silently hold deployments. If a merge does not deploy, inspect *every* check on
the commit before suspecting Railway.

---

## R3 — Running migrations before traffic

### Decision

Use Railway's **pre-deploy command** on the backend service: `alembic upgrade head`.

### Rationale

Pre-deploy runs between build and deploy, inside the private network, with the service's
environment variables available — and **if it fails, the deployment does not proceed**. That last
property is precisely FR-021 and the "must not begin serving traffic on a database it cannot use"
edge case, obtained from the platform rather than built.

### Alternatives considered

| Alternative | Rejected because |
|---|---|
| Keep migrations in the container entrypoint (what local Compose does) | Runs once per replica rather than once per deploy. Correct today at one replica, quietly wrong at two, and the failure mode is a race rather than an error |
| Manual migration step before deploying | Reintroduces the human action FR-019 removes, and makes the ordering a matter of discipline |

The Compose entrypoint keeps its current behaviour. Local and deployed differ here deliberately,
and the difference is recorded rather than incidental.

---

## R4 — Health checks and what they gate

### Decision

Set the backend service's **healthcheck path to `/api/health/ready`**. Railway queries it after
deploying and only makes the new deployment active once it answers 200; the previous deployment
keeps serving until then.

### Rationale

This makes R1 and the readiness redesign load-bearing rather than cosmetic. If readiness fails
because a dependency that was never deployed is reported as failed, **the deployment never goes
live** — the health check simply never turns green. Honest readiness is not a nicety here; it is
what allows the deploy to complete.

It also gives zero-downtime deploys and automatic protection against a release that starts but
cannot reach its database.

### Alternatives considered

| Alternative | Rejected because |
|---|---|
| Point the check at `/api/health` (liveness) | It touches no dependency. A backend that cannot reach Postgres would be declared healthy and take traffic |
| No health check | Railway would cut over to a new deployment that may not work |

---

## R5 — Representing "not configured" honestly

FR-006 requires that the readiness response distinguish *checked and healthy* from *not
configured*, and never report success for something unchecked.

### Decision

Keep the existing response shape and add a third status value:

```json
{
  "status": "ok",
  "dependencies": {
    "database":       { "status": "ok", "latency_ms": 12.4 },
    "cache":          { "status": "not_configured" },
    "object_storage": { "status": "not_configured" }
  }
}
```

Overall status is derived from **checked** dependencies only. A `not_configured` entry never
fails the overall result, and never claims success.

### Rationale

The distinction survives into the response, so an operator reading it learns what was checked and
what was deliberately absent. It also degrades gracefully: when slices 003 and 004 configure these
dependencies, the entries become `ok` or `error` with no further code change.

### Alternatives considered

| Alternative | Rejected because |
|---|---|
| Omit unconfigured dependencies from the response | Silent. A reader cannot distinguish "not deployed" from "we forgot to check", which is the ambiguity FR-006 exists to remove |
| Report them as `ok` | Makes the endpoint lie. Explicitly forbidden by FR-006, and it is the tempting shortcut precisely because it turns the health check green |
| Separate `checked` and `skipped` objects | A shape change for every existing consumer and test, to express what one extra status value expresses |

The existing disclosure rule is unchanged: a failing probe still reports the exception class only,
with the driver's message going to the log (established by T068).

---

## R6 — Reaching the backend from the frontend

### Decision

The frontend remains the only publicly reachable service and proxies `/api/*` to the backend over
Railway's private network. `BACKEND_URL` becomes the backend's internal address rather than the
Compose service name.

### Rationale

Mirrors the local arrangement exactly, so local behaviour remains evidence about deployed
behaviour. One public origin means every request is same-origin: no CORS configuration, no
cross-origin cookie handling, and one `PUBLIC_BASE_URL` for the OAuth redirect to derive from.

### Risk to verify early, not assume

**Railway's private network is IPv6.** The frontend's proxy must resolve and connect over IPv6 to
reach `*.railway.internal`. This is a known source of first-deploy failures and it is invisible
locally, where Docker's network is IPv4. The symptom would be the frontend loading while every
`/api/*` request fails.

The project has already been bitten by the mirror image of this — Playwright resolving `localhost`
to `::1` against an IPv4-only Docker publish. Treat this as something to confirm on the first
deploy with a real request, not to reason about.

---

## Resolved: no NEEDS CLARIFICATION items remain

Every unknown in the technical context is decided above. The two carrying residual risk —
Wait for CI's breadth (R2) and private-network IPv6 (R6) — are recorded with the symptom to look
for, because both fail in ways that do not name their cause.

## Sources

- [Railway — Controlling GitHub autodeploys](https://docs.railway.com/deployments/github-autodeploys)
- [Railway — Pre-deploy command](https://docs.railway.com/deployments/pre-deploy-command)
- [Railway — Healthchecks](https://docs.railway.com/deployments/healthchecks)
- [Railway — Config as code reference](https://docs.railway.com/config-as-code/reference)
- [Railway — Production readiness checklist](https://docs.railway.com/overview/production-readiness-checklist)
