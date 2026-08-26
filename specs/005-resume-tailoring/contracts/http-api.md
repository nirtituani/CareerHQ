# Contract — HTTP API

**Ownership comes from the session, never from the request.** No endpoint accepts a client-supplied
user, profile, or version owner. The existing test that enumerates every route and asserts
non-public ones return 401 covers these automatically.

---

## `POST /api/applications/{application_id}/tailor`

Start a tailoring run.

**202 Accepted**

```json
{
  "version_id": "uuid",
  "status": "tailoring",
  "run_id": "uuid"
}
```

The **version id** is the polling target and the resource the interface is about; `run_id` is
included for the audit view. Both the version and the run are created before the response is sent
(FR-003), so the id is immediately usable.

| Status | When |
|---|---|
| **202** | Started |
| **409** | A run is already in flight for this job (FR-004) |
| **422** | No completed match analysis, or the analysis predates the current profile (FR-001) |
| **404** | Not this owner's application |

**422 must distinguish the two causes** — "run a match analysis first" and "your profile changed;
re-run the match" are different actions. A single message covering both makes the interface
guess.

## `GET /api/versions/{version_id}`

The version, its items, and the Reviewer's findings.

```json
{
  "id": "uuid",
  "application_id": "uuid",
  "status": "awaiting_approval",
  "confidence_score": 78,
  "is_fixture": false,
  "model": "claude-sonnet-5",
  "source_profile_updated_at": "…",
  "items": [
    {
      "id": "uuid",
      "source_kind": "experience_bullet",
      "position": 0,
      "included": true,
      "original_text": "…",
      "proposed_text": "…",
      "final_text": "…",
      "decision": "pending",
      "findings": [
        { "kind": "overstated", "detail": "…", "quoted_text": "…" }
      ]
    }
  ],
  "draft_findings": [
    { "kind": "uncovered", "detail": "…" }
  ]
}
```

**`findings` are nested under the item they concern** (FR-042). `draft_findings` carries only those
with no item — `uncovered` (research R9).

**No `ungrounded` finding ever appears with a surviving `proposed_text`.** The claim was discarded
before persistence (FR-018); the finding remains as evidence the guardrail ran.

While `status` is `tailoring` or `reviewing`, `items` is empty and `confidence_score` is null. The
interface renders progress, not an empty diff (FR-039).

## `PATCH /api/versions/{version_id}/items/{item_id}`

Record a decision on one proposal.

```json
{ "decision": "rejected" }
{ "decision": "edited", "text": "…" }
```

| Rule | |
|---|---|
| `accepted` | `final_text` becomes `proposed_text` |
| `rejected` | `final_text` becomes `original_text` (FR-026). **No AI work is triggered.** |
| `edited` | `final_text` becomes the supplied text, distinguishable from both (FR-027) |

**409** once the version is `ready` and has been exported — not applicable in this slice, but the
status check belongs here rather than being added in 006 alongside the state that needs it.

**422** if `decision` is `edited` and `text` is absent or empty.

## `POST /api/versions/{version_id}/approve`

Confirm the draft.

**Every item still `pending` is treated as accepted** (FR-025) — the import-review precedent, where
an untouched review adds everything not discarded.

Transitions `awaiting_approval → ready`. **Starts nothing** (FR-028). Returns the version.

**409** unless the version is `awaiting_approval`.

## `GET /api/versions/{version_id}/run`

The audit record: plan, attempts, guidelines used with sources, per-task models, tokens, cost,
finalisation rules version, and timings.

Its own endpoint rather than a field on the version, because it is inspection rather than the
document, and slice 007 reads it programmatically.

## `GET /api/applications/{application_id}/versions`

Versions for one job, newest first. Enough to render a list: id, name, status, confidence score,
created-at.

---

## Two things the API deliberately does not do

**No endpoint returns a version belonging to another owner**, and none accepts an owner id. This
is the existing rule, restated because four new routes is the largest surface this project has
added at once since slice 003.

**No endpoint exposes the raw model output.** What the provider returned is reachable only as
validated, finalised rows. An endpoint serving the unfinalised draft would route around FR-018 —
the discard rule is enforced at persistence, so anything reading upstream of persistence bypasses
it.
