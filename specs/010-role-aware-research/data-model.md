# Data Model: Role-Aware Company Research

Phase 1 output. Tables/columns here describe the **target** state; nothing is migrated in this
phase. The one migration (`0020_application_research`) reshapes a provably empty table — see
research.md D2 for the argument and its emptiness guard.

## Entities

### ApplicationResearchSnapshot (reshaped from `role_research_snapshots`)

One immutable record per research run, scoped to an application.

| Column | Type | Rules |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK → users, NOT NULL, CASCADE | ownership from session, never request |
| `application_id` | uuid FK → applications, NOT NULL, CASCADE | the scope (decision 1A) |
| `retrieved_at` | timestamptz NOT NULL default now() | freshness clock |
| `sections` | JSONB NOT NULL | whatever the producing path emitted, unconverted (D3) |
| `produced_by` | varchar(32) NOT NULL | `provider:tavily-research` \| `builtin` — **new**. The API's third value, `legacy-company`, is **derived at read time** for 008-era company snapshots and is never stored here — do not add it to the check constraint |
| `prompt_version` | varchar(32) | shape discriminator: `app-v1` \| `v2-dense` |
| `model_config_used` | JSONB | provider tier / model list; raw cost-basis facts |
| `input_tokens`, `output_tokens` | int NOT NULL ≥0 | exact on fallback, 0 on provider runs |
| `cost` | numeric(12,6) NOT NULL ≥0 | recorded or estimated spend |
| `cost_basis` | varchar(16) NOT NULL | `recorded` \| `estimate` — **new** (D5) |
| `status` | varchar(16) NOT NULL | `running` \| `succeeded` \| `failed` |
| `failure_reason` | text | exception class name, no secrets/values |

Constraints carried over under new names: status check, tokens ≥ 0, cost ≥ 0, and the partial
unique index **one `running` row per application** (the FR-016 concurrency guard, exactly 008's
pattern re-scoped). New check: `cost_basis IN ('recorded','estimate')`.

**Dropped**: `company_research_snapshot_id` (mandatory Layer 1 lineage — no Layer 1 exists in
this design; D2). **Renamed**: `findings` → `sections`.

**State transitions**: `running → succeeded` (sections + sources + usage written, in one
transaction) or `running → failed` (reason + whatever cost basis existed). No other transitions;
no updates to a terminal row (Principle IV). A `running` row older than
`research_max_duration_seconds` is *treated as* abandoned by readers and by the guard — the row
itself is never rewritten by the reader.

**Read path** (per application): prefer an in-flight row while plausibly in flight → newest
`succeeded` row. No pointer column: unlike 008's company pointer (which arbitrated *reuse across
applications*), a per-application scope has exactly one candidate ordering, and `retrieved_at`
plus the partial unique index answer it. Failure never evicts the last success because failure
writes nothing the read path prefers.

### ResearchSource (existing table, FK renamed)

| Change | Detail |
|---|---|
| Rename | `role_snapshot_id` → `application_snapshot_id` (FK → application_research_snapshots, CASCADE) |
| Constraint | `ck_research_sources_exactly_one_snapshot` rewritten by hand: exactly one of `company_snapshot_id` / `application_snapshot_id` (Alembic does not diff check constraints) |
| Unique | partial unique `(application_snapshot_id, source_id)` carried over under the new name |
| Semantics | provider runs: one row per provider-returned source, `source_id` minted `s1..sN`, `excerpt` NULL (no verbatim verification possible — FR-010); fallback runs: unchanged 008 behaviour, `excerpt` holds the surviving verified excerpt |

### CompanyResearchSnapshot (legacy, read-only from this slice)

Untouched. No new rows are written to it; existing rows keep rendering (FR-014, SC-005). Its
pointer `companies.current_research_snapshot_id` is no longer advanced; the read path treats a
legacy company snapshot as the thing to show **only when the application has no
ApplicationResearchSnapshot at all** (US4 acceptance 2).

## Validated schemas (Pydantic, `domain/schemas/research.py`)

### ApplicationResearch (`app-v1`) — the provider output schema, also the stored shape

```
ApplicationResearch
├── company_identification: { official_name: str, website: str,
│                             headquarters: str | None, how_identified: str }
├── company_overview: str
├── products_and_services: str
├── business_and_market: str
├── relevant_to_your_role: str            # explains itself when no posting existed (FR-011)
├── what_to_know_before_the_interview: list[str]  (1..12)
└── questions_worth_asking: list[str]              (1..12)
```

Validation rules: every field required; `how_identified` non-empty (the wrong-entity tripwire,
FR-007); list bounds enforced; a provider response that fails validation is a **failed run**,
never partially persisted (D8). When posting text was absent, `relevant_to_your_role` and the
two lists must still be present — content may be thin but must say why (validator mirrors 008's
"empty must explain itself"). Reminder from the tailoring slice: conditional requirements must
live in `Field(description=...)` — `model_validator(mode="after")` does not serialise into the
JSON Schema the provider receives, and with Tavily the schema is the entire contract (every
property additionally needs a `description`, D1).

### CompanyResearch (`v2-dense`) — unchanged

Kept as-is for the fallback path and legacy rendering. Not deprecated in code; deprecated as the
*primary* stored shape.

## Configuration (new fields, `config.py`)

| Field | Default | Meaning |
|---|---|---|
| `research_provider` | `tavily-research` | which adapter is primary (`builtin` selects the 008 pipeline directly) |
| `research_fallback_enabled` | `true` | provider failure → builtin run vs honest failure (D8) |
| `research_provider_timeout_seconds` | `300` | provider HTTP timeout; distinct from the 900 s abandonment ceiling |
| `research_posting_max_chars` | `20000` | posting text beyond this is truncated **from the end** before being sent (requirements concentrate early); the truncation is recorded in the snapshot's `model_config_used` as `{"posting_truncated": true, "posting_chars_sent": N}` |

Existing fields reused: `tavily_api_key` (same key covers `/research`),
`research_max_duration_seconds`, window constants in `research_windows.py`. The fallback path's
`llm_model_research_synthesise_company` entry already exists; no new `llm_model_<task>` entries
are needed unless a new completion task is added (none is).
