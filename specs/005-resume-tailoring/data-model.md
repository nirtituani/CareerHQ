# Data Model — Slice 005, Resume Tailoring

Four new tables, one amended enum, and two absences that are load-bearing.

Everything here follows the project's rule that **business invariants belong in the schema**: a
constraint cannot be raced or forgotten, an application-level check can be both.

---

## Overview

```
resume_profiles ──────┐ (lineage: recorded, never inherited — ADR-012)
                      ▼
applications ──► resume_versions ──► tailoring_runs
                      │                    │
                      ├──► resume_version_items
                      │              ▲
                      └──► reviewer_findings ──┘ (item-level findings reference an item;
                                                  draft-level findings reference none)
match_analyses ──────────► read only, never written (FR-011)
```

---

## `resume_versions`

One tailored resume for one job. The business document.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `profile_id` | uuid fk → `professional_profiles` | Ownership. Every query filters on it. |
| `application_id` | uuid fk → `applications` | Which job this was tailored for (FR-032) |
| `source_resume_profile_id` | uuid fk → `resume_profiles` | Lineage (FR-030) |
| `source_profile_updated_at` | timestamptz | The master's state at creation (FR-030) |
| `name` | varchar(255) | |
| `professional_title` | varchar(255) nullable | The version's own title |
| `status` | varchar(24) | See the lifecycle below |
| `confidence_score` | integer nullable | 0–100, from the Reviewer. Null until reviewed. |
| `tailoring_run_id` | uuid fk → `tailoring_runs`, **`use_alter`, named** | The workflow reference (`docs/03` line 273) |
| `failure_reason` | text nullable | Set when a run fails (FR-006) |
| `created_at` / `updated_at` | timestamptz | |

**The `use_alter` foreign key must be named**, or it cannot be dropped — slice 004 hit this exactly
once and the failure was total: `drop_all` emits statements from the metadata rather than from the
database, and an unnamed `use_alter` constraint broke it outright against an existing test
database. `conftest.py` drops the schema for this reason; that behaviour is a prerequisite here,
not an optimisation.

The circularity is real and not accidental: a version points at the run that produced it
(`docs/03` line 273), and a run points back at the version it is producing so an abandoned run can
be reaped without a scan. One of the two must be `use_alter`.

### Lifecycle (FR-039, FR-040)

```
Draft → Tailoring → Reviewing → Awaiting approval → Ready
          ▲            │
          └────────────┘   confidence below threshold — internal, no user involvement
```

| Status | Means | Who acts next |
|---|---|---|
| `draft` | Created; holds the master's content unchanged | The system, on request |
| `tailoring` | The workflow is planning or drafting | The system |
| `reviewing` | **The agent is criticising its own draft** | The system |
| `awaiting_approval` | **Finished. The owner's turn.** | The owner |
| `ready` | Owner-approved. Still editable (FR-029). | The owner |

**`awaiting_approval` is the amendment.** `docs/03` §10.1 folds it into `reviewing`, which conflates
a machine working for tens of seconds with a human queue that may last days. `docs/03` §10.1 is
updated in this slice (R8).

**A failed run returns the version to `draft`** and sets `failure_reason`. There is deliberately no
`failed` status: what remains is an untailored resume plus a run record explaining the attempt, and
the owner can retry into the same `draft` rather than accumulating abandoned versions.

`exported` and `submitted` are **not** added here. Slice 006 adds them when something can reach
them.

### Constraints

- **`uq_resume_versions_one_in_flight_per_application`** — partial unique index on
  `application_id` where `status IN ('tailoring','reviewing')`. This is FR-004, and it is in the
  schema because a double-click can race an application-level check. Same reasoning as
  `uq_resume_profiles_one_master_per_profile`.
- `status` is checked against the five values.
- `confidence_score` between 0 and 100 when not null.

---

## `tailoring_runs`

One execution of the workflow. The audit record.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `resume_version_id` | uuid fk → `resume_versions` | |
| `match_analysis_id` | uuid fk → `match_analyses` | Which analysis fed the plan (FR-010). Read-only. |
| `plan` | jsonb | The Tailoring Plan (FR-009) |
| `guidelines_used` | jsonb | Each guideline and its source (FR-016) |
| `attempts` | integer | Revisions performed, 0–2 (FR-013) |
| `finalisation_rules_version` | varchar(32) | e.g. `v1-severity` (FR-020) |
| `model_config` | jsonb | Task name → model, as resolved at run time (FR-036) |
| `status` | varchar(16) | `running`, `succeeded`, `failed`, `abandoned` |
| `failure_reason` | text nullable | |
| `started_at` / `finished_at` | timestamptz | `finished_at` null while running — this is what the reaper reads |
| `input_tokens` / `output_tokens` | integer | Summed across steps (FR-035) |
| `cost` | numeric(12,6) | **Decimal, never float.** An audit value, not a display value. |
| `is_fixture` | boolean | True only from the fixture gateway |

**`plan` and `guidelines_used` are `jsonb` rather than tables**, and this is a deliberate departure
from slice 004's "requirements as rows, not a JSON blob" (its R5). The difference is what gets
queried: slice 004 queries requirements individually to render and to measure. Nothing queries an
individual plan line. When slice 007 needs to measure retrieval quality it will query
`guidelines_used`, and `jsonb` containment is adequate for that. **If a query arrives that wants a
row per guideline, that is the signal to normalise** — recorded here so the departure is a decision
rather than an inconsistency.

**Per-step usage is summed, not stored per step.** The three totals plus `model_config` answer
Principle V's requirement (inputs, model configuration, token usage, cost). A per-step breakdown is
what slice 007 might want; it is not needed to satisfy the audit obligation, and a `tailoring_steps`
table nothing reads is cost without benefit. Named here so 007 knows what it would have to add.

**`is_fixture` propagates to the interface**, as it does for imports and analyses. Canned content
mistaken for real output would mean approving invented history.

---

## `resume_version_items`

One row per item in the version. This is what the diff renders and what approval writes to.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `resume_version_id` | uuid fk → `resume_versions` | |
| `source_kind` | varchar(32) | `experience_bullet`, `skill`, `project`, `summary`, `title`, … |
| `source_item_id` | uuid nullable | The profile fact this derives from |
| `position` | integer | Order within its section (FR-033) |
| `original_text` | text | What the master said |
| `proposed_text` | text nullable | What the agent proposed. Null when unchanged. |
| `final_text` | text | What the version holds |
| `decision` | varchar(16) | `pending`, `accepted`, `rejected`, `edited` |
| `included` | boolean | Selection (FR-033) |

**`original_text` is copied, not referenced.** Principle I says resumes reference profile facts
rather than duplicating them — but Principle IV and FR-031 say a version must not change when the
profile does. A reference would make the diff mutate underneath an approved version. The copy *is*
the lineage snapshot, and it is the same reasoning that puts `source_profile_updated_at` on the
version.

**`final_text` is materialised rather than derived** from `decision` plus the other two columns.
Deriving it means every reader re-implements the rule, and the reader that gets it wrong is the PDF
export in slice 006 — which is exactly where a wrong answer becomes a document sent to an employer.

**`decision = 'edited'` is how FR-027 stays distinguishable** from both the agent's proposal and the
master's original. This mirrors `user_corrected` in the profile, and for the same reason.

### Constraints

- Unique on `(resume_version_id, source_kind, source_item_id)` where `source_item_id` is not null.
- `final_text` not null — an item that reached persistence has resolved text.

---

## `reviewer_findings`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `tailoring_run_id` | uuid fk → `tailoring_runs` | |
| `resume_version_item_id` | uuid fk nullable | Null for draft-level findings |
| `kind` | varchar(16) | `ungrounded`, `overstated`, `uncovered` |
| `detail` | text | The Reviewer's own words |
| `quoted_text` | text nullable | The words objected to. **Required for `ungrounded`.** |
| `attempt` | integer | Which pass raised it |

**`kind` is a closed set because finalisation routes on it** (R9). A free-text concern cannot be
routed, and FR-018's discard rule is a release blocker.

**`ungrounded` must quote what it objects to** — a check constraint, not a convention. Slice 004
established why: a verdict carrying no evidence lets the model invent the absence, which is the
same fabrication pointed the other way. A finding that cannot say *which words* are unsupported
cannot be tested, shown, or checked by a person.

**`uncovered` findings carry no item**, deliberately. There is no item for an unaddressed
requirement to attach to, and manufacturing one would repeat slice 004's `unverified`-shortfall
mistake exactly: demanding a structured field the model has no honest basis to fill.

**Findings persist even when their item's proposal was discarded** under FR-018. The record of what
the Reviewer caught is the evidence that the guardrail ran, and slice 007 measures against it.

---

## Two absences that are load-bearing

**There is no `is_stale` column on anything.** Staleness is a comparison between
`professional_profiles.updated_at` and the analysis's `created_at`, computed at read time — the
rule `match.py` already established, and FR-001 reuses the existing check rather than adding a
flag. A stored flag is a second source of truth that goes wrong the moment a profile is edited
without every dependent row being visited.

**There is no `failed` version status.** A failed run leaves `draft` plus a `failure_reason`. Its
absence is what keeps retry simple and stops abandoned versions accumulating.

Both absences need tests that have been **watched failing**. `create_all` does not reconcile an
existing table, so a schema-shaped assertion silently checks a stale snapshot — slice 003's T067
passed against a deliberately added column until `conftest.py` dropped before creating.

---

## Migrations

| # | Adds |
|---|---|
| `0010_resume_versions` | `resume_versions`, `tailoring_runs`, the named `use_alter` FK between them, both partial indexes |
| `0011_version_items_and_findings` | `resume_version_items`, `reviewer_findings`, the `ungrounded`-quotes-text check |

Two rather than one, because the second depends on the first's tables existing and splitting makes
a partial failure diagnosable.
