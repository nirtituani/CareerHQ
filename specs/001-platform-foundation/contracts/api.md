# API Contracts: Platform Foundation

**Date**: 2026-08-05 | **Feature**: [spec.md](../spec.md)

All paths are under `/api`. The browser reaches them through the Next.js proxy, so they are
same-origin from the frontend's perspective. FastAPI generates the live OpenAPI document at
`/api/docs`; this file is the reviewable contract the implementation must satisfy.

---

## Health

### `GET /api/health` — liveness

Never touches dependencies. Used by Docker Compose's healthcheck.

**200**
```json
{ "status": "ok", "version": "0.1.0" }
```

### `GET /api/health/ready` — readiness

Checks every dependency concurrently and reports each by name (FR-002, SC-008).

**200** — all reachable
```json
{
  "status": "ok",
  "dependencies": {
    "database": { "status": "ok", "latency_ms": 3 },
    "cache": { "status": "ok", "latency_ms": 1 },
    "object_storage": { "status": "ok", "latency_ms": 8 }
  }
}
```

**503** — one or more unreachable. The response still lists every dependency, so the failing one
is named rather than inferred.
```json
{
  "status": "degraded",
  "dependencies": {
    "database": { "status": "ok", "latency_ms": 3 },
    "cache": { "status": "error", "error": "Connection refused" },
    "object_storage": { "status": "ok", "latency_ms": 8 }
  }
}
```

A dependency that does not answer within 2 seconds is reported as an error rather than hanging
the probe.

---

## Authentication

### `GET /api/auth/google/login`

Starts the OAuth flow. Generates `state`, stores it in a short-lived HttpOnly cookie, and
redirects to Google.

**302** → Google's consent screen.

Optional query parameter `next` (a relative path) is preserved and used as the post-login
destination. Absolute URLs are rejected — an open redirect would let an attacker send a
freshly-authenticated user to a site they control.

### `GET /api/auth/google/callback`

Google's redirect target. Validates `state`, exchanges the code, verifies the ID token, provisions
the user and profile on first sign-in (idempotent — FR-010, FR-011), issues the session cookie.

**302** → `/dashboard` (or the validated `next` path), with `Set-Cookie: careerhq_session=...;
HttpOnly; SameSite=Lax; Path=/; Max-Age=604800`.

**302** → `/login?error=access_denied` when the user cancels at Google's prompt. No account is
created (edge case: "Sign-in declined").

**400** when `state` is missing or does not match — a possible CSRF attempt.

### `GET /api/auth/me`

Returns the signed-in identity. This is how the frontend decides whether to show the app shell.

**200**
```json
{
  "id": "0198f2c1-...",
  "email": "nir@example.com",
  "display_name": "Nir Tituani",
  "avatar_url": "https://lh3.googleusercontent.com/...",
  "created_at": "2026-08-05T09:12:44Z"
}
```

**401** when the cookie is absent, expired, tampered with, or its `sub` no longer exists.
```json
{ "detail": "Not authenticated" }
```

### `POST /api/auth/logout`

**204**, with a `Set-Cookie` that expires `careerhq_session` immediately. Safe to call while
already signed out — returns 204 either way, so the UI needs no special case.

---

## Profile

### `GET /api/profile`

Returns the signed-in user's Professional Profile. Empty in this slice; later slices add content.

**200**
```json
{
  "id": "0198f2c4-...",
  "user_id": "0198f2c1-...",
  "created_at": "2026-08-05T09:12:44Z",
  "updated_at": "2026-08-05T09:12:44Z"
}
```

**401** when unauthenticated.

The profile is resolved from the session's `sub`. There is no `GET /api/profile/{id}` — no route
accepts a client-supplied user or profile ID, which is what makes cross-user access impossible by
construction rather than by a permission check that could be forgotten (FR-015, SC-005).

---

## Cross-cutting

**Errors** use FastAPI's standard shape, `{"detail": "..."}`. Validation failures return 422 with
Pydantic's field-level errors.

**Correlation**: every request gets an `X-Request-ID` (echoed if the client supplies one) which
appears in the response header and in every structured log line for that request (FR-008).

**Authentication**: any route outside `/api/health*` and `/api/auth/google/*` requires a valid
session cookie and returns 401 without one (FR-014).
