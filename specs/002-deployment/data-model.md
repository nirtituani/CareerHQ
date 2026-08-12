# Data Model: Deployment

**Feature**: [spec.md](./spec.md) | **Branch**: `002-deployment`

## No new entities, and no schema change

This slice adds no tables, columns, indexes, or migrations. The schema that deploys is exactly the
schema slice 001 created:

| Table | Owner | Change in this slice |
|---|---|---|
| `users` | Professional context | None |
| `professional_profiles` | Professional context | None |
| `alembic_version` | Migration tooling | None |

`alembic upgrade head` runs during deployment (research.md R3) and will find nothing to apply on
the first deploy, because the deployed database is fresh and the local one is already current.
That is the expected outcome, not a sign the step was skipped — and it is worth knowing before the
first deploy, so an empty migration run is not mistaken for a misconfiguration.

**Constitutional invariants deploy unchanged.** The UNIQUE constraint on
`professional_profiles.user_id` — which is what makes Principle I unraceable rather than merely
intended — travels with the schema. SC-002 re-proves it against the deployed system by signing in
twice and confirming the counts do not move.

---

## What does change shape: configuration

The only structural change is which settings are required. This is not persisted data, but it
determines what the system can start without, so it belongs here.

| Setting | Before | After | Why |
|---|---|---|---|
| `DATABASE_URL` | Required | **Required** | No environment can run without it |
| `SESSION_SECRET` | Required, min length 32 | **Required, min length 32** | Relaxing it would undo a T068 protection — an empty secret means forgeable sessions |
| `REDIS_URL` | Required | **Optional** | Nothing uses the cache yet; arrives with slices 003/004 |
| `S3_ENDPOINT_URL` | Required | **Optional** | Same |
| `S3_ACCESS_KEY` | Required | **Optional** | Same |
| `S3_SECRET_KEY` | Required | **Optional** | Same |
| `S3_BUCKET` | Required | **Optional** | Same |
| `PUBLIC_BASE_URL` | Default `localhost:3000` | Unchanged; **set explicitly** in deployment | Drives every browser-facing URL, the OAuth redirect above all |
| `ENVIRONMENT` | Default `local` | Unchanged; **set to `production`** | First time this value has ever been used |

Two derived properties join the existing `google_oauth_configured`:

```
cache_configured            → REDIS_URL is set
object_storage_configured   → the S3 settings are set
```

These are the sole input to which dependencies get probed. A dependency whose property is `False`
is reported as **`not_configured`** rather than probed — never as `ok`, which would make the
endpoint claim a result it never produced. See
[contracts/readiness.md](./contracts/readiness.md) for the full status contract.

### The trade this makes, stated plainly

Slice 001 made these settings required on purpose, so a misconfigured container fails at startup
naming the field rather than at the first request that needs it. Making them optional gives that
up for these two dependencies.

**The mitigation is that absence must still fail loudly, just later.** `redis.py` and `storage.py`
raise a specific named error when asked for a client that is not configured — the failure moves
from startup to first use rather than disappearing into a `None`. A future slice that adds a cache
call and forgets the configuration gets an immediate, self-explaining error.

This is the same trade already made for `GOOGLE_CLIENT_ID`, and for the same reason: a dependency
a *later* slice needs should not stop the platform starting and reporting honestly today.

---

## Entity relationships

Unchanged from slice 001, and reproduced only so this document stands alone:

```text
User (1) ──────── (1) ProfessionalProfile
     UNIQUE(user_id) — enforced in the schema, not in application code
```

---

## Data lifecycle across deployment

Relevant because it is what makes rollback asymmetric (FR-024):

| Layer | On redeploy | On rollback |
|---|---|---|
| Container image | Replaced | Replaced — cheap and safe |
| Schema | Migrated forward | `alembic downgrade` **only if the migration was reversible**. A dropped column is not restored by re-adding it |
| Business data | Untouched | **Never rolled back.** Principle IV makes submitted resumes and status history immutable; an application whose history rewrites itself on deploy cannot reproduce what was sent to an employer |

The third row is a design decision, not a gap, and `quickstart.md` states it where an operator
will actually be looking during an incident.
