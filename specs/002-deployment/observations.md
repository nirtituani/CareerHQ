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

## Not yet observed

- **T034** — declined consent creating nothing. Not exercised.
- **T039** — deployed logs searched for secret values. Not yet run.
- **T042/T043** — deliberate gate failure and rollback drill (User Story 3).

## What observation caught that review could not

Three of the failures in this slice were invisible to the source:

1. Security headers missing from every page a browser visits, while the middleware was correct
2. A hardcoded listening port, correct locally by coincidence
3. A proxy destination baked in at build time, so a runtime variable arrived too late

None would have been found by reading the code, and all three produced symptoms that named
something other than their cause. That is the argument FR-015 was making.
