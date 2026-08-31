# Contract: research API (both shapes)

Endpoints keep their 008 paths and verbs — the interface reaches research from an application,
and ownership comes from the session, never the request. What changes is scope (application, not
company) and the response body, which now declares its shape.

## `POST /api/applications/{application_id}/research` → 202

Starts a run for **this application**, or reuses.

| Case | Response |
|---|---|
| Fresh snapshot exists (≤ reuse window, per application) | `202 {"reused": true, "snapshot_id": ...}` — no spend |
| Started | `202 {"reused": false, "snapshot_id": ...}` — background run begins |
| A run is already in flight for this application | `409` conflict (FR-016) |
| Application not owned / not found | `404` (never 403 — existence is not disclosed) |

Request body: **none**. Company, domain, role title and posting are assembled server-side from
the owned application (`scoreable_posting()` supplies posting text or None — FR-003). Nothing
client-supplied selects the research subject.

## `GET /api/applications/{application_id}/research` → 200

Returns the current research for this application: in-flight while plausibly in flight → newest
succeeded application snapshot → **legacy company snapshot only if no application snapshot
exists** → `{"status": "none"}`.

```jsonc
{
  "status": "running" | "succeeded" | "failed" | "none",
  "shape": "sections" | "tiered",          // from prompt_version; "tiered" covers legacy rows
  "produced_by": "provider:tavily-research" | "builtin" | "legacy-company",
  "retrieved_at": "...",
  "freshness": "fresh" | "aging" | "stale",   // 008 windows, application-scoped (D6)
  "cost": "0.038000",
  "cost_basis": "recorded" | "estimate",
  "failure_reason": "ResearchProviderUnavailable",   // failed only; class name, no detail
  "research": { ... },                     // ApplicationResearch when shape=sections;
                                           // CompanyResearch when shape=tiered
  "sources": [ {"source_id": "s1", "url": "...", "title": "...",
                "excerpt": "... or null", "fetch_status": "retrieved" | "failed"} ]
}
```

Contract rules:

- **`shape` is the renderer dispatch** — the frontend must not sniff the payload. Adding a third
  shape later is additive.
- **`produced_by` is always present and truthful** (FR-005, FR-017): a fallback-produced result
  says `builtin`; the UI's Sources area surfaces it quietly (provenance, not a warning banner).
- **No tier vocabulary in the `sections` shape** (FR-009/SC-008). Tiers still appear inside the
  `tiered` shape's payload — that is the legacy/fallback contract, rendered by the legacy view.
- **`excerpt` non-null means verified** (FR-010): only fallback/legacy sources carry excerpts;
  provider sources are attribution-only and render as such.
- **Errors disclose kind, not detail** (project security rule): `failure_reason` is an exception
  class name; driver/provider text goes to the operator log only.
- **The response is cache-safe to poll**: the frontend polls every 2 s only while
  `status == "running"` (unchanged 008 behaviour), keyed on the application id (the route-change
  state gotcha).

## Compatibility

- 008-era company snapshots keep rendering through the same GET, as `shape: "tiered"`,
  `produced_by: "legacy-company"` — stored bytes untouched (SC-005).
- The 008 POST semantics ("reused" per **company**) are retired with decision 1A; two
  applications at the same employer each pay for and own their research.
- OpenAPI enumeration tests must re-assert route count after the change (the "gate with nothing
  to examine" rule — enumerate from `app.openapi()["paths"]` and assert how many were examined).
