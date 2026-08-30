# Contract: HTTP API

All routes are under `/api`, reached through the frontend proxy — there is one public origin and
no CORS surface (slice 002).

## Universal rules

**Ownership comes from the session, never the request.** No route accepts a user id or profile id
from the client (FR-019, Constitution I). The existing test that enumerates every route and
asserts non-public ones return 401 must be extended to cover everything added here — it is the
mechanism, not the intention, that keeps this true.

**Errors name the field, never the value.** The T068 convention from slice 001: configuration and
validation errors identify what is wrong without echoing rejected input, because that is how a
secret ends up in a log.

**Diagnostics go in structured fields.** Anything needed to debug an import failure in production
belongs in `extra={...}`, not the log message — Railway discards message text (FR-022, slice 002
observation).

---

## Import

### `POST /api/imports/resume`

Upload a CV. Multipart. Returns the staged import with its extracted items.

| | |
|---|---|
| **202** | Accepted and extracted. Body is the `ImportedResume` with `ExtractionItem`s |
| **400** | Not PDF or DOCX, or content does not match the declared type. Names accepted formats (FR-001) |
| **413** | Too large |
| **422** | Extraction produced nothing usable — `extraction_error` set (FR-008). **Not** an empty item list |
| **503** | No AI provider configured. Names the missing setting (FR-028) |

Nothing is written to the profile by this endpoint. That is the whole point of it being separate
from approval.

### `GET /api/imports/{id}`

The staged import and its items, for review. 404 if not owned by the session user — **404, not
403**, so the endpoint does not confirm the existence of another user's data.

### `PATCH /api/imports/{id}/items/{item_id}`

Correct, accept, or discard one item. Sets `source = user_corrected` on a change (FR-004).

### `POST /api/imports/{id}/approve`

The gate. Writes accepted items to the Professional Profile and creates the Master Resume, in
**one transaction** (FR-023, R6).

| | |
|---|---|
| **200** | Profile populated, Master Resume created |
| **409** | Already approved. Idempotent by C4 — a double-click cannot produce two Master Resumes (SC-004) |
| **422** | Nothing accepted to approve |

### `DELETE /api/imports/{id}`

Discard. The profile is untouched (FR-007).

---

## Applications

### `POST /api/applications`

Create with company, title, and job description (FR-010). The company is resolved or created by
normalized name (C2). Valid with no submitted resume (FR-011).

### `GET /api/applications` / `GET /api/applications/{id}`

The session user's only. 404 for anything else.

### `PATCH /api/applications/{id}`

Any status change writes a history row (FR-012). Requests cannot set `normalized_status`
directly — it is derived from the label (FR-013), because a client-settable normalized status is
a second source of truth for the same fact.

### `POST /api/applications/import/jobtracker`

Upload a JobTracker export (FR-015, D2). Rows are validated and partitioned **before** the
transaction opens, so unmappable rows are reported while mappable ones still import (FR-018,
FR-023).

| | |
|---|---|
| **200** | Report: imported, skipped-as-duplicate, rejected rows with per-row reasons, and notices |
| **400** | File unreadable or not a recognised export |
| **413** | File larger than the upload limit, checked before the file is parsed |
| **409** | Another import of the same rows is already in progress |

Re-running is safe: duplicates are refused by C3 and reported as skipped, not as errors.

**200 carries four fields, not three.** `notices` holds rows that *did* import but need a
person's eye — an unfamiliar status label, a date nobody could read. Deliberately separate from
`rejected`: those rows are in the database, and a report that merged the two would send someone
looking for history that is already there.

**409 is for two imports racing, and it is the only outcome that asks the caller to wait.**
Duplicate detection reads which rows were already imported and then writes; between those two
steps a second upload of the same file can import the same row, so the read can be stale by the
time the write happens. The guarantee is the uniqueness rule itself rather than the check, so the
second writer is refused rather than allowed to duplicate someone's history.

**The response says what to do, not what went wrong underneath.** The body is
*"An import of this file is already running. Try again in a moment."* — the refusal names no
table, column, constraint or value, because a conflict message is a description of the schema if
it is allowed to be. The detail goes to the log in structured fields, which is the same split
`/api/health/ready` applies to a failed dependency: **the operator gets the cause, the browser
gets the kind.** Retrying once the other import finishes reports every row as skipped, so the
resolution is to wait rather than to change anything.

**No request or response anywhere in this API carries a `rejected` boolean** (FR-016). Rejection
travels as a normalized status value. Worth stating in the contract because an API field is
exactly how a removed column grows back.

---

## Health

`GET /api/health/ready` gains `ai_provider`, reported on the same three-state basis slice 002
established for cache and object storage:

```
"ai_provider": { "status": "ok" | "error" | "not_configured" }
```

`not_configured` neither fails the check nor masks a real failure — the property slice 002's
most important test was written to prove. `object_storage` moves from `not_configured` to probed
once the bucket exists (FR-021, R5), through a code path that already has tests.
