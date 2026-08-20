# Phase 1 — Data Model: Match Analysis

Two new tables, two new columns on `applications`, one migration. No vector column.

---

## `match_analyses` — one row per run, append-only

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `application_id` | uuid FK → `applications.id` | `ON DELETE CASCADE`; indexed |
| `status` | enum | `pending` \| `ready` \| `failed` |
| `error` | text NULL | Set **only** when `failed`; the reason shown to the person |
| `overall_score` | smallint NULL | 0–100. **Stored, not displayed** — sorting and calibration |
| `band` | enum NULL | `strong` \| `moderate` \| `stretch` \| `low_probability`. What is shown |
| `verdict` | text NULL | One sentence. NULL until `ready` |
| `criteria_version` | varchar(64) NOT NULL | `v1-weighted` for the first rubric — see below |
| `model` | varchar(128) NULL | |
| `input_tokens` | integer NULL | |
| `output_tokens` | integer NULL | |
| `cost` | numeric(12,6) NULL | **Decimal, never float** — an audit value accumulated over thousands of calls |
| `is_fixture` | boolean NOT NULL default false | True only from the fixture adapter |
| `created_at` | timestamptz NOT NULL | |
| `completed_at` | timestamptz NULL | Set when `ready` or `failed` |

**Append-only.** No endpoint, use case, or code path may `UPDATE` a row that has reached `ready`,
and none may `DELETE`. The one legitimate update is `pending → ready|failed`, which is the row
being completed rather than history being rewritten. Slice 003 asserts append-only on
`application_status_history` by scanning the source tree for writes; the same test extends here.

**`criteria_version` is NOT NULL from the first insert.** A nullable column would let a forgotten
value be indistinguishable from a deliberate one. The first value is `v1-weighted`, naming the
adapted weighted rubric that ships with this slice. The `v0` uncalibrated state the design
planned for is never entered, because a rubric arrived before implementation did.

**The band is derived from the score, and the banding thresholds are part of the criteria
version.** Storing the band rather than computing it at render time is deliberate: re-banding a
historical analysis under new thresholds would silently rewrite what the person was told. The
score and the band are both facts about that run, under those criteria.

**Usage columns are written in the same transaction as the result** (Principle V, FR-017), in the
manner the CV import already follows.

---

## `match_requirements` — one row per requirement

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `analysis_id` | uuid FK → `match_analyses.id` | `ON DELETE CASCADE`; indexed |
| `ordinal` | smallint NOT NULL | Presentation order as the posting stated them |
| `text` | text NOT NULL | The requirement as written |
| `kind` | enum NOT NULL | `must_have` \| `preferred` |
| `verdict` | enum NOT NULL | `confirmed` \| `partial` \| `transferable` \| `gap` \| `unverified` |
| `shortfall` | enum NULL | `wording` \| `evidence` \| `capability`. NULL when the verdict is `confirmed` |
| `evidence` | text NULL | Quoted from the profile. NULL **only** when `unverified` |

**The grounding invariant lives here as a database constraint**, not only in the schema:

```sql
CHECK ((verdict = 'unverified') = (evidence IS NULL))
```

Read that carefully, because it is stronger than it looks and stronger than the first draft's
version. **Every verdict must be grounded, including the negative ones.** A `gap` must quote the
profile text showing the shortfall — three years where five were asked. If the model cannot quote
anything, it does not get to call it a gap; the honest answer is `unverified`, and that is the one
verdict that requires no evidence precisely because it asserts nothing.

That closes a hole the first draft left open. It made `missing` evidence-free, which let the model
assert *you do not have this* from a profile that was merely silent — inventing a negative fact
about the person. AI-008 forbids inventing experience; this is the same error pointed the other
way. Pydantic rejects it earlier and more legibly; the constraint makes it true of the data
regardless of which code path wrote it.

**`transferable` requires evidence too**, and must never be rendered as `confirmed`. Adjacent
experience presented as direct experience is fabrication one step removed.

Rows rather than a JSON blob, because slice 007 counts requirement frequency across analyses —
a `GROUP BY` over rows, and a re-extraction bill over JSON (R5).

---

## `applications` — two new columns

| column | type | notes |
|---|---|---|
| `requirements` | text[] NULL | What the posting asks of the candidate, one per element |
| `current_match_analysis_id` | uuid NULL FK → `match_analyses.id` | The analysis to display |

`current_match_analysis_id` gives the applications table one join rather than one query per row,
preserves history, and makes the displayed score have a single unambiguous source.

**It advances only when an analysis reaches `ready`** (FR-015). On a first analysis it is NULL and
the interface shows the pending state. On a re-run it keeps pointing at the previous `ready` row
until the new one succeeds — so the score does not blank out while re-running, and a failed re-run
leaves the last good score standing.

The FK is deliberately nullable and deliberately *not* `ON DELETE CASCADE` in the direction that
would delete an application when an analysis goes; it is `ON DELETE SET NULL`.

### `job_description` and the legacy-row problem

Per R1, `job_description` has been storing a newline-joined requirements list, not the posting.
From this slice onward it holds the full posting and `requirements` holds the list.

**Existing rows are not backfilled and not guessed at.** A row written before this slice never had
its posting captured, so there is nothing to recover. Such rows are identified by
`requirements IS NULL`, and they are **not scored** — they present as *nothing to score against
yet*, with an offer to re-add the job to repopulate both fields.

`requirements IS NULL` (never captured) and `requirements = '{}'` (captured, none found) are
different facts and must stay distinguishable. An empty array is a real extraction result; NULL is
the absence of one. Any code treating them alike reintroduces exactly the ambiguity this column
was added to remove.

---

## State machine

```
                    ┌─────────────────────────────────────────┐
   job saved        │                                         │
   with posting ───▶│  pending  ──▶  ready                    │
                    │      │                                  │
                    │      └────▶  failed                     │
                    └─────────────────────────────────────────┘

   job saved with no posting  ──▶  (no analysis row at all)
```

Four states reach the interface, and the fourth is not a row:

| state | condition | treatment (docs/09 §5) |
|---|---|---|
| running | latest analysis is `pending` | spinner |
| scored | `current_match_analysis_id` is set | the score |
| failed | latest is `failed` and no current | solid failure rule and the reason |
| nothing to score | no requirements captured, or none found | muted line — **not** an error |

The fourth is deliberately not a `failed` row. A job added by hand with no description is ordinary,
and an analysis against an empty requirement list would return a number with nothing behind it.

**At most one analysis may be `pending` per application** (FR-007), enforced with a partial unique
index rather than an application-level check, which can be raced:

```sql
CREATE UNIQUE INDEX ... ON match_analyses (application_id) WHERE status = 'pending';
```

---

## Invariants to assert, not assume

Each of these must be watched failing before it is trusted — `create_all` does not reconcile an
existing table, and slice 003 lost a release-blocker assertion to exactly that.

| # | Invariant | Where |
|---|---|---|
| **I1** | Every verdict except `unverified` has evidence; `unverified` never does | Schema + DB constraint |
| **I1a** | A `gap` is never recorded for a requirement the profile is merely silent about | Integration test with a profile silent on a named requirement |
| **I2** | No analysis row is updated once `ready`; none is ever deleted | Source-tree scan, as slice 003 does for status history |
| **I3** | `current_match_analysis_id` never points at a non-`ready` analysis | Integration test across the re-run path |
| **I4** | An analysis is never visible to a user who does not own the application | Route enumeration test, as slice 001 established |
| **I5** | `criteria_version` is non-null on every row | NOT NULL, plus a test that the value is the configured one |
| **I5a** | A stored `band` is never recomputed from a later criteria version | Test that re-banding thresholds does not alter historical rows |
| **I6** | The analysis writes nothing to the profile | Integration test comparing profile state either side of a run |
| **I7** | Legacy rows (`requirements IS NULL`) are never scored | Integration test with a legacy-shaped row |
| **I8** | At most one `pending` analysis per application | Partial unique index; test attempts a concurrent second |
