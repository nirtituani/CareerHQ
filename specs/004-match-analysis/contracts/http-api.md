# Contract: HTTP API

Extends `api/routes/applications.py`. A match analysis has no meaning apart from the job it
scores, so it is a sub-resource rather than a top-level one.

**Ownership comes from the session, never from the request.** No endpoint here accepts a
client-supplied user or application owner. The route-enumeration test that asserts every
non-public route returns 401 covers these automatically.

---

## `GET /api/applications/{id}/match`

The current analysis for one job.

**200** — an analysis exists (any state):

```jsonc
{
  "state": "ready",              // running | ready | failed | nothing_to_score
  "analysis": {
    "id": "…",
    "band": "strong",              // what the interface shows
    "overall_score": 84,           // retained for sorting and calibration, not displayed bare
    "dimensions": { "direct": 88, "transferable": 82, "adjacent": 75, "impact": 80 },
    "verdict": "Strong backend fit; Kubernetes ownership is unproven rather than absent.",
    "criteria_version": "v1-weighted",
    "coverage": {
      "confirmed": 11, "partial": 4, "transferable": 6,
      "gap": 3, "unverified": 14, "total": 38
    },
    "requirements": [
      {
        "ordinal": 0,
        "text": "5+ years building production backend services",
        "kind": "must_have",
        "verdict": "confirmed",
        "shortfall": null,
        "evidence": "Led the payments platform team for six years…"
      },
      {
        "ordinal": 1,
        "text": "10+ years in a regulated domain",
        "kind": "preferred",
        "verdict": "gap",
        "shortfall": "capability",
        "evidence": "Six years at the payments platform — the only regulated work listed."
      },
      {
        "ordinal": 2,
        "text": "Kubernetes in production",
        "kind": "must_have",
        "verdict": "unverified",     // the profile is silent — NOT a gap
        "shortfall": "evidence",
        "evidence": null
      }
    ],
    "model": "anthropic/claude-sonnet-5",
    "input_tokens": 3420,
    "output_tokens": 1487,
    "cost": "0.022110",           // string — Decimal is never serialised as a float
    "is_fixture": false,
    "created_at": "…",
    "completed_at": "…"
  },
  "stale": false                  // profile edited since this analysis
}
```

**The four states are explicit in `state`, not inferred by the client.** A client deciding
"no score means it failed" is precisely the conflation FR-022 forbids, and putting the decision on
the server means one implementation rather than one per surface.

| `state` | `analysis` | meaning |
|---|---|---|
| `running` | the pending row, scores null | spinner |
| `ready` | the current analysis, fully populated | the score |
| `failed` | the failed row, `error` populated | the failure and its reason |
| `nothing_to_score` | `null` | no posting captured, or none found — **not** an error |

**`stale`** is true when the profile's `updated_at` is newer than the analysis's `created_at`.
The server computes it; the client only renders the offer to re-run (FR-025). It is never acted on
automatically.

**404** — the application does not exist *or* is not the caller's. The two are not
distinguished, so the endpoint cannot be used to discover which application ids exist.

---

## `POST /api/applications/{id}/match`

Trigger an analysis by hand (FR-024). Idempotent under concurrency.

**202 Accepted** — an analysis was queued:

```jsonc
{ "state": "running", "analysis": { "id": "…", "status": "pending", … } }
```

**409 Conflict** — one is already in flight (FR-007). The partial unique index is the enforcement;
this is its surface. Returning 202 here would let a person queue five runs with five clicks.

**422** — nothing to score against. The job has no captured posting, or none yielded requirements.
Not a 500 and not an empty 202: the request was well-formed and the answer is that this job cannot
be scored yet.

**No request body.** There is nothing for the caller to choose. A model, a criteria version, or a
prompt accepted from the client would put cost and behaviour under the browser's control.

---

## Existing endpoints that change

### `POST /api/applications` and the URL/text import path

Now store **both** `job_description` (the full posting) and `requirements` (the list). Per R1 this
is the behaviour change that ends the discard; the response gains `requirements`.

On success, an analysis row is created `pending` **in the same transaction as the application**,
and the scoring runs in a background task. The response returns immediately (FR-004) and carries
the pending analysis so the interface has something to show a spinner against.

If no requirements were captured, **no analysis row is created** and the job simply has none —
the `nothing_to_score` state (FR-006).

### `GET /api/applications`

Each row gains a compact match summary — enough for the Match column, not the whole analysis:

```jsonc
{ "state": "ready", "band": "strong", "overall_score": 84 }
```

`band` drives the column. `overall_score` is included so the column can be **sorted** meaningfully
— four bands make a poor sort key — but a client must not render it as a bare percentage.

One join via `current_match_analysis_id`, not one query per row.

### `GET /api/applications/{id}`

Gains `requirements` as a distinct field. `job_description` continues to be returned and now means
the full posting for rows written from this slice onward. Rows written earlier have
`requirements: null`, which is how the interface tells them apart from a job whose posting yielded
no requirements (`requirements: []`). Those two must not be collapsed.
