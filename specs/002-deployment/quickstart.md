# Quickstart: Deployment

**Feature**: [spec.md](./spec.md) | **Branch**: `002-deployment`

How to deploy CareerHQ, confirm it actually works, and get back to a working version when it does
not. Written to be followed by someone who has never deployed this system — SC-007 is exactly
that claim.

Replace `<frontend-domain>` throughout with the domain Railway generates for the frontend service.

---

## Prerequisites

| | |
|---|---|
| Railway project | Exists, with a `pgvector` service running PostgreSQL 18.4 (vector 0.8.6, verified) |
| Repository access | `main` merged and green |
| Google Cloud console | Access to the OAuth client — **required**, and the one step nobody can do for you |
| `gh` | Authenticated with the `workflow` scope, for pushing the deploy configuration |

---

## Part 1 — Deploy

### 1.1 Create the services

Two services in the existing project, both from this repository:

| Service | Root | Public? |
|---|---|---|
| `backend` | `backend/` | **No** — private only |
| `frontend` | `frontend/` | **Yes** — generate a domain |

Only the frontend gets a public domain. The backend is reached through it, over the private
network.

### 1.2 Configure the backend

Variables:

```
ENVIRONMENT=production
DATABASE_URL=${{pgvector.DATABASE_URL}}
SESSION_SECRET=<generate: openssl rand -hex 32>
PUBLIC_BASE_URL=https://<frontend-domain>
GOOGLE_CLIENT_ID=<from Google Cloud console>
GOOGLE_CLIENT_SECRET=<from Google Cloud console>
```

**Do not set `REDIS_URL` or the `S3_*` variables.** They are optional now, and leaving them unset
is what makes readiness report `not_configured` rather than failing. Setting them to placeholder
values would make the application believe it has a cache and fail at first use.

Settings:

- **Pre-deploy command**: `alembic upgrade head`
- **Healthcheck path**: `/api/health/ready`

### 1.3 Configure the frontend

```
BACKEND_URL=http://backend.railway.internal:8000
```

### 1.4 Enable the deployment gate

On both services, turn on **Wait for CI**. Without it, a merge deploys immediately and CI results
arrive too late to prevent anything (FR-020).

### 1.5 Register the OAuth redirect URI — manual, and unavoidable

In the Google Cloud console, on the OAuth 2.0 client, add to **Authorized redirect URIs**:

```
https://<frontend-domain>/api/auth/callback
```

Exactly that, with no trailing slash. Google matches redirect URIs by exact string, so a near-miss
fails at the provider with an error that describes a mismatch rather than what to fix.

---

## Part 2 — Confirm it works

Do these in order. Each is evidence for a specific success criterion; none can be satisfied by
reading code.

### 2.1 The site is reachable — SC-001

From a device with no project setup — a phone on mobile data is the strictest version:

```
https://<frontend-domain>
```

**Expect** the sign-in page over HTTPS.

### 2.2 Readiness is honest — SC-003

```bash
curl -s https://<frontend-domain>/api/health/ready | python3 -m json.tool
```

**Expect** `"database": {"status": "ok", ...}` and both `cache` and `object_storage` reporting
`"not_configured"`, with overall `"status": "ok"` and HTTP 200.

**If `cache` or `object_storage` says `ok`, stop.** Nothing is deployed to be `ok` about — the
endpoint is lying and FR-006 is violated.

### 2.3 Production security — SC-004, the first execution ever

`ENVIRONMENT=production` has never run. These checks are the point of the exercise.

**HSTS on a real response:**

```bash
curl -sI https://<frontend-domain> | grep -i strict-transport-security
```

**Expect** a `Strict-Transport-Security` header. Absent means `is_production` is not what you
think it is.

**Insecure requests are upgraded:**

```bash
curl -sI http://<frontend-domain> | grep -i '^location:'
```

**Expect** a redirect to the `https://` address.

**The session cookie, as a browser records it** — do this in the browser, not with curl, because
the browser is what enforces these flags. Sign in, then open DevTools → Application → Cookies:

**Expect** the session cookie with **`Secure` ✓** and **`HttpOnly` ✓**.

> Record what you observed, not what you expected. This configuration has never executed; the
> whole reason this step exists is that nobody knows yet whether it works.

### 2.4 Sign-in end to end — SC-002

In a private window, sign in with Google. **Expect** to arrive at the dashboard.

Then confirm exactly one account and one profile — in the `pgvector` service's Console:

```bash
psql -U postgres -c "SELECT (SELECT count(*) FROM users) || '|' || (SELECT count(*) FROM professional_profiles);"
```

**Expect** `1|1`. Sign out, sign in again, re-run: **still `1|1`**. A second profile means the
UNIQUE constraint did not deploy, which would be a Principle I violation.

### 2.5 Continuous deployment — SC-005, SC-006

**Passing gates deploy:** merge a trivial visible change to `main`. Watch with
`gh run watch`. **Expect** the change live with no manual step.

**Failing gates do not:** on a branch, break a test deliberately, merge, and confirm the public
site is **unchanged** and the failure is visible in Actions. Then revert.

> That second test is the one people skip. A gate nobody has watched fail is not a gate.

---

## Part 3 — Operate

### Read the logs

```bash
railway logs --service backend
railway logs --service frontend
```

Backend logs are one JSON object per line, each carrying a request id. To follow one request
across the system, filter on that id.

### See what is live

Railway's Deployments tab shows the active deployment, its commit, and whether the last attempt
succeeded. A failed pre-deploy command appears here with its output — that is where a failed
migration will be.

### Roll back

Deployments tab → the last known-good deployment → **Redeploy**.

### What rollback does *not* undo

Read this before an incident, not during one.

| Layer | Rolls back? |
|---|---|
| **Application code** | ✅ Yes — containers are stateless; redeploying the previous image is complete and safe |
| **Schema** | ⚠️ Only if the migration was reversible. `alembic downgrade` restores structure, **not data**. A migration that dropped a column is not undone by re-adding an empty one |
| **Business data** | ❌ **Never** — and by design |

The third row is Principle IV. Submitted resumes and status history are immutable; an application
whose history rewrote itself on deploy could not reproduce what was sent to an employer, which is
the guarantee the whole system is built to provide.

**Practical consequence:** a migration that discards data needs a database snapshot taken
immediately before deploy, because its rollback path is restore-from-backup, not `downgrade`.
Additive migrations — nearly all of them — need nothing.

---

## Troubleshooting

Two failures here do not name their own cause. Both were predicted during planning.

**The site loads but every `/api/*` request fails.**
Railway's private network is **IPv6**; Docker's local network is IPv4, so this cannot reproduce
locally. Check that the frontend resolves and connects to `backend.railway.internal` over IPv6.
See research.md R6.

**A merge never deploys, and this repository's CI is green.**
Wait for CI waits on **all** GitHub check suites on that commit, not just this repo's workflow. A
stale integration from another app can hold it indefinitely. Inspect *every* check on the commit
before suspecting Railway. See research.md R2.

**Sign-in fails at Google with a redirect-URI mismatch.**
The registered URI must match `PUBLIC_BASE_URL` exactly — scheme, host, path, no trailing slash.

**The backend never becomes healthy.**
The healthcheck points at readiness, so a readiness failure blocks the whole deployment. Fetch
`/api/health/ready` directly and read which dependency is `error`. If something reports `error`
that was never deployed, the probe is not following configuration.
