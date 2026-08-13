# Deployment Observations

**Feature**: [spec.md](./spec.md) | **Satisfies**: FR-015, SC-004 | **Date**: 2026-08-12

FR-015 requires that HSTS, `Secure`, and `https_only` be confirmed **by observing the deployed
system**, not by reading the code. `ENVIRONMENT=production` had never executed anywhere in this
project's life, so the source could only ever have shown intent.

This file records what was actually observed. Where an expectation was wrong, the observation is
recorded rather than the expectation.

**Deployed at**: `https://frontend-production-02ac.up.railway.app`

---

## FR-014 — browsers instructed to use secure connections only

Observed on a real response from `/login`:

```
strict-transport-security: max-age=31536000; includeSubDomains
x-content-type-options:    nosniff
x-frame-options:           DENY
referrer-policy:           no-referrer
```

**This did not pass on the first attempt, and the failure is the most valuable finding in the
slice.** The headers were present on `/api/*` and absent from every page a browser navigates to.
`SecurityHeadersMiddleware` was correct throughout — it simply never sees those responses, because
the frontend serves the HTML. Reading the middleware would have confirmed it handles the half of
the origin it is given and said nothing about the other half.

Fixed by giving the frontend a matching `headers()` policy, copied from the backend's values so
the two halves of one origin cannot drift.

## FR-013 — session credential restricted and script-unreadable

Observed on a live `set-cookie` from the deployed system:

```
session=…; path=/; Max-Age=600; httponly; samesite=lax; secure
```

Confirmed a second time in the browser after a real sign-in: DevTools → Application → Cookies
shows the authenticated `session` cookie with **Secure** and **HttpOnly** both set. The browser is
what enforces these, so the browser is where it was checked.

## FR-002 — insecure requests upgraded

```
$ curl -sI http://frontend-production-02ac.up.railway.app
HTTP/1.1 301 Moved Permanently
location: https://frontend-production-02ac.up.railway.app/
```

## FR-004 to FR-007 — readiness reports only what it checked

```json
{
  "status": "ok",
  "version": "0.1.0",
  "dependencies": {
    "database":       { "status": "ok", "latency_ms": 5.05 },
    "cache":          { "status": "not_configured" },
    "object_storage": { "status": "not_configured" }
  }
}
```

HTTP 200. Two dependencies absent by design are reported as such rather than as healthy, and the
deployment is not blocked by their absence. Database latency of 3–11 ms across repeated checks is
consistent with the private network rather than the public proxy.

## FR-016 / SC-008 — database not reachable from the public internet

**First measured as a failure, and the measurement was wrong.** `nc -z` reported the old proxy
port open, but it only completes a TCP handshake, and Railway's proxy edge is shared across
customers — it accepts connections on a port whether or not anything sits behind it.

Speaking the PostgreSQL protocol instead gives the honest answer:

```
SSLRequest to yamabiko.proxy.rlwy.net:58953 -> ConnectionResetError
control (github.com:443)                    -> accepted then closed
```

Nothing answers as a database. A test that cannot distinguish "port open" from "database exposed"
is not evidence for a security criterion, and it nearly went into the record as one.

## FR-009 / FR-010 / SC-002 — sign-in and provisioning

A real Google sign-in on the public address reached the dashboard. Counts afterwards:

| | users\|profiles |
|---|---|
| After first sign-in | `1\|1` |
| After signing out and in again | `1\|1` |

The second row is the one that matters: it exercises the UNIQUE constraint that makes
Principle I unraceable, on the deployed database, for the first time.

## FR-011 — browser-facing URLs derive from configuration

Confirmed by inspecting what the backend actually sends Google:

```
redirect_uri=https://frontend-production-02ac.up.railway.app/api/auth/google/callback
```

Derived from `PUBLIC_BASE_URL`, not from the incoming request — which would have been the
internal service hostname. Three separate misspellings of the domain (`fronted`, `frontned`) were
caught here **before** reaching Google, because the value is inspectable in the redirect rather
than only discoverable as a provider-side error.

---

## FR-021 / T043 — the pre-deploy migration ran

Read from the deployed backend's logs. Both alembic runs appear, which is what
`backend/railway.toml` describes and what a single run would have left ambiguous:

```
20:45:20  INFO [alembic.runtime.migration] Context impl PostgresqlImpl.   <- preDeployCommand
20:45:27  Applying database migrations...                                 <- entrypoint.sh
20:45:28  INFO [alembic.runtime.migration] Will assume transactional DDL.
20:45:28  Starting API on :8000
```

No `Running upgrade` line, because the deployed database was already current — the expected
result, not a skipped step. `Starting API on :8000` is also the first direct confirmation that
the `${PORT:-8000}` change resolves to the pinned port in the deployed environment.

One detail worth knowing before it is mistaken for a fault: alembic writes to stderr, so Railway
tags every migration line `"level":"error"`. A successful migration therefore looks like an error
in a log search filtered by level.

## FR-017 / T039 — secrets in deployed logs: startup covered, sign-in not

Every retained log corpus was searched for the **literal values** of `SESSION_SECRET`,
`GOOGLE_CLIENT_SECRET`, `GOOGLE_CLIENT_ID` and the database password, read from the deployed
configuration so the comparison is against what is actually set:

| Corpus | Lines | Result |
|---|---|---|
| backend deploy | 20 | clean |
| backend build | 49 | clean |
| backend http | 0 | clean |
| frontend deploy | 6 | clean |
| frontend build | 55 | clean |

Zero occurrences. **But this is not yet the evidence FR-017 asks for.** The task requires startup
*and at least one completed sign-in*, and Railway retains logs only for the current deployment —
the deployment the sign-in verification ran against is now `REMOVED` and its logs are gone. What
is proven is that startup and both image builds leak nothing. The sign-in path is unproven, and
that is the half where a secret is most likely to be logged, because it is the half that handles
one.

## An anomaly worth recording: the service domain the CLI reports is not the one that serves

`railway domain list` reports exactly one domain for the `frontend` service:

```
fronted-production-02ac.up.railway.app   service   Sync: UPDATING
```

That hostname returns **404**. The hostname that actually serves CareerHQ is
`frontend-production-02ac.up.railway.app`, which returns 200 — and it is the value in
`PUBLIC_BASE_URL`, in the README, and registered with Google.

The reading that fits: Railway generates a service domain from the service *name*, the service
was first created misspelled, and renaming it to `frontend` started a domain sync that has sat in
`UPDATING` since 2026-08-12T14:12Z. The new hostname routes; the record still displays the old
one.

Nothing is broken, and the documented URL is the correct one. It is recorded because the failure
mode is nasty: an operator who trusts `railway domain list` over the running system would
"correct" `PUBLIC_BASE_URL` to a 404 and break sign-in at the same time, since the OAuth redirect
URI must match it byte for byte.

## FR-023 / SC-007 / T044 — the rollback drill, performed

Run against the live `frontend` service before any incident required it. The target was chosen so
the mechanism could be proven without risking a regression: `beeadaf` (live) and `cfc7369` (one
step back) differ only in documentation, and the security-headers fix is in both.

| Time (UTC) | Step | Live deployment | Commit | Site |
|---|---|---|---|---|
| 08:03:25 | baseline | `04f1da7f` | `beeadaf` | 200, 4/4 headers |
| 08:03:41 | `deploymentRollback` → previous | — | — | — |
| 08:04:14 | rolled back | `eda5c647` | `cfc7369` | 200, 4/4 headers |
| 08:06:44 | `deploymentRollback` → original | — | — | — |
| 08:07:16 | restored | `28cab4db` | `beeadaf` | 200, 4/4 headers |

**The site returned 200 at every poll across both transitions** — the rollback is genuinely
zero-downtime, which is what the readiness healthcheck in `backend/railway.toml` buys. Final
headers and readiness are byte-identical to baseline.

Two things the drill established that the documentation had wrong or silent:

1. **`railway deployment redeploy` is not a rollback.** It redeploys the *latest* deployment —
   effectively a restart. Rolling back to an earlier version is a different operation:
   `deploymentRollback(id)` in the API, or Redeploy on an older deployment in the dashboard.
   Reaching for the obvious command during an incident would restart the broken version.
2. **A rollback creates a *new* deployment id carrying the *old* commit**, and the previous live
   id flips to `REMOVED`. Restoring `04f1da7f` produced `28cab4db`, not `04f1da7f`. So "which
   version is live" must be read from the deployment's **commit**, never its id — and a rolled-back
   deployment id never becomes live again under its own name.

## FR-020 / SC-005 / T040 + T041 — the gate holds, then releases

Watched on a real push of `39b6e76` to `main`, polling CI and Railway together:

```
08:32:47  CI=in_progress        554d6ead:WAITING:39b6e76   <- held by Wait for CI
08:33:31  CI=completed/success  554d6ead:SUCCESS:39b6e76   <- released on green
08:33:53                        28cab4db:REMOVED:beeadaf   <- previous retired
```

The `WAITING` state is the evidence. A deployment that merely arrives after CI proves nothing
about ordering — that could be coincidence of timing. Seeing Railway *hold* a created deployment
and release it when CI reported success is what shows the gate is armed. It also settles the
caveat printed under the toggle ("make sure you have accepted our updated GitHub permissions"),
which is otherwise a silent failure mode.

Both services moved `beeadaf` → `39b6e76` with no manual step; the site kept 4/4 security headers
and a healthy readiness response throughout.

Neither service sets `watchPatterns`, so every push to `main` deploys both regardless of which
paths changed — a documentation-only commit still exercises the full pipeline.

## FR-020 / SC-006 / T042 — the gate watched failing

The case T041 could not prove. A deliberately failing test was merged to `main` and the pipeline
watched, then reverted:

```
08:37:06  CI=in_progress        69e62334:WAITING:02a5bcf   554d6ead:SUCCESS:39b6e76
08:37:51  CI=completed/failure  69e62334:SKIPPED:02a5bcf   554d6ead:SUCCESS:39b6e76
```

**`SKIPPED`, not `SUCCESS`.** Railway created a deployment for the broken commit, held it while CI
ran, and abandoned it when CI failed — and it stayed `SKIPPED` rather than retrying. The public
site answered 200 with all four security headers at every poll, still served by the previous
deployment on the last good commit.

The revert then completed the cycle, which matters as much as the failure: a gate that blocks bad
commits but also jams good ones is not usable.

```
08:40:21  CI=in_progress        686b8e23:WAITING:94cd529
08:41:06  CI=completed/success  686b8e23:DEPLOYING:94cd529
08:41:28  CI=completed/success  686b8e23:SUCCESS:94cd529
```

Two things worth keeping:

- **Two independent gates caught the break** — ruff `B011` (`assert False` is stripped under
  `python -O`) and pytest — and both appeared in the same run rather than the lint failure
  masking the test failure. That is what CI's `if: !cancelled()` buys, observed rather than
  assumed.
- **Deployment status is the honest signal, not CI status.** `WAITING` → `SKIPPED` is visible only
  from the deployment record. Reading Actions alone shows a red run and leaves open whether
  anything reached production.

## Not yet observed

- **T034** — declined consent creating nothing. Needs a browser.
- **T039** — the sign-in half, per above. Needs a sign-in on the *current* deployment.

## What observation caught that review could not

Three of the failures in this slice were invisible to the source:

1. Security headers missing from every page a browser visits, while the middleware was correct
2. A hardcoded listening port, correct locally by coincidence
3. A proxy destination baked in at build time, so a runtime variable arrived too late

None would have been found by reading the code, and all three produced symptoms that named
something other than their cause. That is the argument FR-015 was making.
