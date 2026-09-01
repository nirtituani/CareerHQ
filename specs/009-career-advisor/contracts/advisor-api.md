# Contract — Advisor API

All routes require the session (ownership derives from it, never from the request — the
existing 401-enumeration test picks these up automatically once registered in `main.py`).
Error rule: the type goes to the browser, the detail to the log.

## `GET /api/advisor`

The page's single read. Returns the user's memory state and latest run.

```json
{
  "memories": [
    {
      "id": "…", "claim": "…", "kind": "recurring_gap",
      "scope": {"kind": "role_family", "value": "Backend"},
      "status": "active",                     // active | tentative
      "priority": 80,                          // null = not actionable
      "evidence": { …frozen shape, data-model.md… },
      "created_at": "…", "last_confirmed_at": "…",
      "supersedes_id": null, "recreates_dismissed_id": null,
      "last_disposition": {"action": "confirmed", "run_id": "…",
                            "evidence_delta": {…} | null}
    }
  ],
  "coverage": {                                // FR-011's honest denominators, always present
    "applications": 97, "analysed": 1,
    "message": "Skill-level patterns grow as applications get match analyses."
  },
  "latest_run": { …run shape below… } | null,
  "history_counts": {"superseded": 3, "retired": 2}
}
```

- `memories` holds **active + tentative only**, ordered by `priority DESC NULLS LAST,
  last_confirmed_at DESC`. Superseded/retired come from the lineage/history routes.
- Empty history + no run → `memories: []`, `latest_run: null`; the frontend renders the
  honest empty state from `coverage` (no run is spent server-side answering this).

## `POST /api/advisor/runs` → **202** / **409**

The match-analysis trigger contract:
- **202** with the pending run body when created. The pending row commits before the
  background task starts (a background task's status change is invisible until commit).
- **409** `{"detail": "An analysis is already running."}` while a pending run is
  plausibly in flight. An abandoned pending row (over the deadline) does **not** 409 —
  it reads as failed and a new run starts (the stuck-run rule).
- **409** (distinct detail) when the user has no applications at all — the spec's
  no-history rule: no run is spent.

Run shape (also `GET /api/advisor/runs/{id}` for polling):

```json
{
  "id": "…", "status": "pending" | "ready" | "failed",
  "error": null | "The reasoning step returned nothing usable.",
  "rules_version": "v1-advisor",
  "ops": {"proposed": 7, "applied": 6, "discarded": 1} | null,
  "models": {"grouping": "…", "reason": "…"},        // per-call attribution
  "cost": "0.041000" | null,
  "created_at": "…", "completed_at": "…" | null,
  "dispositions": [ {"memory_id": "…", "action": "…", "reason": null,
                     "evidence_delta": {…} | null} ]   // ready runs only
}
```

## `GET /api/advisor/memories/{id}`

One memory with its full lineage chain (walk `supersedes_id` to the root) and its
disposition history. Any status is readable here — superseded and retired stay readable
with evidence, reasons and lineage (FR-014). 404 for another user's memory (ownership
filter, not a disclosure).

## `POST /api/advisor/memories/{id}/dismiss` → **200** / **409**

- **200**: the memory (must be `active`/`tentative`, owned) transitions to `retired`
  with `retired_reason = "user_dismissed"`. No disposition row is written — dispositions
  record what a *run* did, and a user dismissal is not a run action; both enforcement
  layers (D8, FR-021) read the memory row's `retired_reason` directly. Returns the
  updated memory.
- **409** when the memory is already superseded/retired (terminal rows refuse
  resurrection *and* re-termination; re-dismissing is a no-op conflict, not a success).

## Non-routes (deliberate)

- No `DELETE` anywhere: memories are insert-only history.
- No route mutates claim/evidence: there is nothing to PATCH by design.
- No pagination: the active set is capped at 25; lineage chains are bounded by run count.
