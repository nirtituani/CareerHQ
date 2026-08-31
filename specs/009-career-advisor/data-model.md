# Data Model — Slice 009: Career Advisor

Three tables, one migration (`0021_career_advisor`). House rules apply: String columns for
enums (with the `is`-vs-`==` gotcha noted), `Numeric(12,6)` for cost, timezone-aware
timestamps, `gen_random_uuid()` PKs, ownership FKs with `ondelete="CASCADE"`.

## `advisor_runs`

One analysis execution. The audit anchor (Constitution V) and the lifecycle mirror of
`match_analyses`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users, NOT NULL, indexed | ownership from session, never the request |
| `status` | String(16) NOT NULL | `pending` / `ready` / `failed` |
| `error` | Text NULL | user-safe kind of failure only; detail goes to the log |
| `rules_version` | String(32) NOT NULL | `ADVISOR_RULES_VERSION` at run time — scores under different unnamed rules compare nothing |
| `evidence_pack` | JSONB NULL | the full pack this run computed (facts with ids); NULL while pending. Kept for SC-001 audits and the UI's "computed from" rendering |
| `ops_proposed` | SmallInteger NULL | counts written at completion… |
| `ops_applied` | SmallInteger NULL | …so *found-nothing* (`proposed=0`) and… |
| `ops_discarded` | SmallInteger NULL | …*discarded-everything* (`proposed>0, applied=0`) are different queryable outcomes (FR-009) |
| `grouping_model` / `reason_model` | String(128) NULL | per-call attribution — the one-model-for-a-two-model-run display bug is a recorded lesson |
| `input_tokens` / `output_tokens` | Integer NULL | summed across calls |
| `cost` | Numeric(12,6) NULL | Decimal, never float; includes spend of a failed run |
| `is_fixture` | Boolean NOT NULL default false | same rule as match analysis |
| `created_at` | timestamptz NOT NULL server default | |
| `completed_at` | timestamptz NULL | |

**Indexes/constraints**:
- `uq_advisor_run_one_pending_per_user`: UNIQUE partial index on `(user_id)` WHERE
  `status = 'pending'` — the race closed where it cannot be raced.

## `career_memories`

Insert-only. One falsifiable claim + frozen evidence + lifecycle position.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users, NOT NULL, indexed | |
| `advisor_run_id` | UUID FK → advisor_runs, NOT NULL | the run that created it |
| `claim` | Text NOT NULL | immutable after insert |
| `kind` | String(64) NOT NULL | open vocabulary (spec: grounding rules, not topic whitelists) |
| `scope_kind` | String(32) NOT NULL | `global` / `role_family` / `skill` / `status` / `source` (String, deliberately not DB-constrained — open like `kind`) |
| `scope_value` | Text NULL | NULL iff `scope_kind = 'global'` (CHECK below) |
| `evidence` | JSONB NOT NULL | frozen: cited facts with numerator/denominator/record ids/date range, plus any grouping relied on (FR-007). Never updated |
| `priority` | SmallInteger NULL | agent-assigned, 0–100, NULL = not actionable (FR-022); CHECK range |
| `status` | String(16) NOT NULL | `active` / `tentative` / `superseded` / `retired` — forward-only (see transitions) |
| `supersedes_id` | UUID FK → career_memories NULL | set at insert, never after |
| `recreates_dismissed_id` | UUID FK → career_memories NULL | D8: visible dismissal history on legitimate recreation |
| `retired_reason` | Text NULL | required when retired (CHECK); `user_dismissed` is the distinguished value the dismissal gate keys on |
| `created_at` | timestamptz NOT NULL server default | |
| `last_confirmed_at` | timestamptz NOT NULL, defaults to `created_at` | advanced by a `confirmed` disposition; the only mutable timestamp |

**Check constraints** (the Pydantic validators reject earlier and more legibly; these make
it true of the table whatever writes to it):
- `ck_career_memory_scope`: `(scope_kind = 'global') = (scope_value IS NULL)`
- `ck_career_memory_retired_reason`: `(status = 'retired') = (retired_reason IS NOT NULL)`
- `ck_career_memory_priority`: `priority IS NULL OR priority BETWEEN 0 AND 100`
- `ck_career_memory_supersedes_not_self`: `supersedes_id IS NULL OR supersedes_id <> id`

**Deliberate absences** (in the manner of `match.py`'s docstring):
- **No cap constraint.** `count(active) ≤ 25` is COUNT-shaped and cannot be a CHECK; it is
  a use-case invariant asserted before commit, closed against races by the one-pending-run
  index, and drilled by a watched-failing test (research D9).
- **No `is_stale` column, no aging column.** Freshness is `last_confirmed_at` versus now,
  derived at read time — a stored flag goes wrong the moment anything moves without every
  memory being visited (the `match.py` argument verbatim).
- **No uniqueness on `(kind, scope)`.** Supersession chains legitimately hold many rows
  with the same subject; only the *active* set must be contradiction-free, and that is the
  reconciliation gate's job (FR-016), not a schema shape.

**Immutability rule**: `claim`, `kind`, `scope_kind`, `scope_value`, `evidence`,
`supersedes_id`, `recreates_dismissed_id`, `advisor_run_id`, `created_at` are frozen at
insert. Mutable: `status` (forward only), `retired_reason` (set once, with the transition),
`last_confirmed_at`, `priority` (a confirming run may re-rank). Enforced by a gate test in
the `immutability.py` drill style — watched failing.

### Status transitions

```text
              (evidence reaches floor, a later run)
   tentative ────────────────────────────────────▶ active
       │                                             │
       │        superseded (new row links back)      │
       ├──────────────────────▶ superseded ◀─────────┤
       │                                             │
       └──────────────────────▶ retired    ◀─────────┘
                    (reason required; user_dismissed is one reason)
```

No transition leaves `superseded` or `retired`. A dismissed claim returning on materially
different evidence is a **new row** carrying `recreates_dismissed_id` — never a
resurrection (the terminal-rows-refuse-resurrection lesson from 010).

## `memory_dispositions`

Append-only log: what each run did with each memory (research D6). This table is FR-013's
completeness check made queryable — `set(active before run) == set(memory_id where run)`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `run_id` | UUID FK → advisor_runs, NOT NULL, indexed | |
| `memory_id` | UUID FK → career_memories, NOT NULL, indexed | |
| `action` | String(16) NOT NULL | `created` / `confirmed` / `superseded` / `retired` / `left_open` |
| `reason` | Text NULL | required for `retired` and `left_open` (CHECK) |
| `evidence_delta` | JSONB NULL | fresh figures accompanying a confirmation ("still 14 of 20 → now 24 of 30") without touching frozen evidence |
| `created_at` | timestamptz NOT NULL server default | |

**Constraints**:
- `uq_memory_disposition_once_per_run`: UNIQUE `(run_id, memory_id)` — a run dispositions
  a memory exactly once.
- `ck_memory_disposition_reason`: `(action IN ('retired','left_open')) = (reason IS NOT NULL)`

## Relationships

```text
users 1──* advisor_runs 1──* memory_dispositions *──1 career_memories *──1 users
career_memories.supersedes_id ──▶ career_memories (lineage chain)
career_memories.recreates_dismissed_id ──▶ career_memories (dismissal history)
```

Lineage is walked by following `supersedes_id` from any memory; the active set is
`status IN ('active','tentative')`; "since the last analysis" is the dispositions of the
latest `ready` run.

## Evidence JSONB shape (frozen into `career_memories.evidence`)

```json
{
  "as_of": "2026-09-01T10:00:00Z",
  "rules_version": "v1-advisor",
  "facts": [
    {
      "fact_id": "tier2.requirement_gap.aws.backend",
      "numerator": 16, "denominator": 20,
      "value": "16/20 analysed Backend postings require AWS",
      "date_range": ["2026-05-01", "2026-08-31"],
      "record_ids": ["…uuid…"],
      "basis": "match_requirements rows with verdict in (gap, partial), grouped per grouping g1"
    }
  ],
  "groupings": [
    { "group_id": "g1", "label": "AWS",
      "member_ids": ["…requirement row uuids…"] }
  ]
}
```

The same fact objects live in `advisor_runs.evidence_pack`; a memory freezes the subset it
cites (plus groupings it relies on). SC-001's audit recomputes each frozen fact from the
named `record_ids`' tables and compares.
