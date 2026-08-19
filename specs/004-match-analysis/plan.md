# Implementation Plan: Match Analysis

**Branch**: `004-match-analysis` | **Date**: 2026-08-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-match-analysis/spec.md`, implementing the approved
design at [docs/superpowers/specs/2026-08-17-match-analysis-design.md](../../docs/superpowers/specs/2026-08-17-match-analysis-design.md).

## Summary

Score a recorded job against the owner's approved Professional Profile and show the reasoning.

One structured completion through the seam slice 003 built: profile + full posting in,
`MatchAnalysis` out. The result is persisted as an append-only analysis row plus one row per
requirement, each carrying one of five verdicts and — for **every verdict except `unverified`** —
evidence quoted from the profile. Scoring runs in a background task after the job is saved, so
saving stays fast and the band arrives a few seconds later.

The rubric ships as `v1-weighted`, adapted from two supplied sources (R9). The model rates four
dimensions; the application computes the score and derives the band. **The band is what the person
sees**; the score is retained for sorting and for the calibration docs/07 §3.2 requires.

**No agent loop, no embeddings, no vector retrieval.** This is the third `complete()` call site and
it does not react to its own output.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7 / Next.js 16 App Router (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2; LiteLLM strictly
behind `infrastructure/ai/`; React 19, Tailwind 4, shadcn/ui

**Storage**: PostgreSQL 18 (the `pgvector` image, but **no vector column is added or used**)

**Testing**: pytest at ≥80% coverage with the completion seam overridden by the fixture adapter;
Vitest component tests; Playwright for the critical flow

**Target Platform**: Linux containers — Docker Compose locally, Railway when deployed

**Project Type**: Web application — existing `backend/` + `frontend/`

**Performance Goals**: score visible within 20 s of saving a job (SC-001); the completion itself
is expected around 12 s

**Constraints**: ≤ $0.03 per job and ≤ $3 per hundred (SC-004); no live provider call in any test
(FR-027); at most one analysis in flight per job (FR-007)

**Scale/Scope**: single-user, hundreds of applications; one new endpoint group, two new tables,
one migration, one new tab

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1.*

| Principle | Verdict | How this design satisfies it |
|---|---|---|
| **I. Profile is the single source of truth** | **PASS** | The analysis reads the profile and derives from it. Evidence is quoted from profile facts rather than duplicated as new professional data. |
| **II. Human-in-the-loop (non-negotiable)** | **PASS** | Nothing user-owned is modified. FR-012 makes this explicit and it is asserted by test, not assumed. The analysis is an observation, not a recommendation awaiting application — so no approval gate is needed, and adding one would be noise. |
| **III. Explainable and honest AI** | **PASS — the central gate** | Every met/partial verdict must carry evidence or the completion is rejected (FR-008). AI-008 becomes a schema property rather than a hope. Model and cost are shown (FR-010). |
| **IV. Immutable history** | **PASS** | Analyses are append-only (FR-014). The displayed-analysis pointer advances only on success (FR-015), so a failed re-run destroys nothing. |
| **V. AI is a platform capability, not a data owner** | **PASS** | The completion goes through the existing `StructuredCompletion` port. `domain/` imports no provider code; the application layer writes usage in the same transaction as the result (FR-017). |
| **VI. Structured data first** | **PASS — and it forbids the alternative** | Output is schema-validated before use. Requirements are stored **relationally** (FR-016). This principle is why retrieval is wrong here: the profile is structured operational fact, and §VI reserves vector retrieval for semantic knowledge. |
| **VII. Test-first quality** | **PASS** | ≥80% coverage; the grounding invariant (FR-008), the append-only invariant (FR-014) and the ownership rule get explicit tests. |

**No violations. Complexity Tracking is therefore empty and omitted.**

Two notes recorded rather than left implicit:

- **Principle V names an "Agent Runtime"** that does not exist as a component. Slice 003 settled
  this: a single structured call through the seam satisfies V because the constraint is that
  business domains do not call providers and that usage is auditable. Both hold. A runtime is
  what the *tailoring agent* will need.
- **Principle II's approval gate does not apply** because nothing is applied. Worth stating,
  because "AI output the user did not approve" pattern-matches to a II violation until you notice
  the analysis writes only to its own tables.

## Project Structure

### Documentation (this feature)

```text
specs/004-match-analysis/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions and their evidence
├── data-model.md        # Phase 1 — tables, states, invariants
├── contracts/
│   ├── match-analysis.md   # The completion contract: schema, prompt, grounding rule
│   └── http-api.md         # Endpoints, payloads, status semantics
├── quickstart.md        # Phase 1 — how to prove it works end to end
├── checklists/
│   └── requirements.md  # Spec quality checklist (complete)
└── tasks.md             # Phase 2 — created by /speckit-tasks, not here
```

### Source Code (repository root)

```text
backend/
├── src/careerhq/
│   ├── api/routes/
│   │   └── applications.py        # MODIFIED — match sub-resource, re-run endpoint
│   ├── application/
│   │   ├── analyze_match.py       # NEW — the use case; the third complete() call site
│   │   └── match_criteria.py      # NEW — v1-weighted: weights, bands, the must-have cap
│   │   └── extract_job.py         # MODIFIED — stop discarding the posting body
│   ├── domain/
│   │   ├── models/
│   │   │   ├── match.py           # NEW — MatchAnalysis, MatchRequirement
│   │   │   └── application.py     # MODIFIED — requirements, current_match_analysis_id
│   │   └── schemas/
│   │       └── match.py           # NEW — the validated completion schema
│   └── config.py                  # MODIFIED — llm_model_match_analysis
├── alembic/versions/
│   └── <rev>_match_analysis.py    # NEW — two tables, two columns
└── tests/
    ├── unit/test_match_schema.py          # NEW — grounding rule, schema invariants
    ├── integration/test_match_analysis.py # NEW — states, append-only, ownership
    └── integration/test_match_content.py  # NEW — every stored value reaches the API

frontend/
├── src/
│   ├── components/applications/
│   │   ├── detail-tabs.tsx        # MODIFIED — Match becomes the second tab
│   │   ├── match-tab.tsx          # NEW — verdict, fits, missing, coverage
│   │   ├── match-score.tsx        # NEW — the four states, in the table and the tab
│   │   └── applications-view.tsx  # MODIFIED — Match column
│   └── lib/api.ts                 # MODIFIED — match types and fetchers
└── src/components/__tests__/
    └── match.test.tsx             # NEW — the four states render distinctly
```

**Structure Decision**: the existing two-project web layout, unchanged. This feature adds no new
top-level directory and no new service. It extends `applications` because a match analysis has no
meaning apart from the job it scores — a separate top-level resource would invite orphans and buy
nothing.

## What research found that the design did not know

Recorded here because it changes the work, not merely the wording. Full detail in
[research.md](research.md) R1.

**`job_description` does not currently hold the posting.** `extract_job.py` extracts a
`requirements` list, joins it with newlines, stores *that* as `job_description`, and **discards
the posting body** — falling back to the body only when no requirements were found. The design
assumed both were already stored and that only a column needed adding.

Two consequences:

1. The migration is not purely additive. Adding a `requirements` column is easy; making
   `job_description` mean "the full posting" changes the meaning of **existing rows**, which hold
   a joined requirements list under that name. A row saved before this slice and one saved after
   are indistinguishable by shape.
2. Scoring an old row would compare the profile against a requirements list while the prompt says
   it is reading a whole posting — quietly producing the requirements-only scoring the design
   explicitly reversed.

Handled by R1's decision rather than left to be discovered during implementation.

## Constitution re-check, after Phase 1 design

Re-evaluated against the artifacts rather than the intention. **Still no violations**, and the
design strengthened two principles rather than merely preserving them:

- **III got stronger.** The grounding rule is enforced in three places, not one: a Pydantic
  validator, a database `CHECK ((verdict = 'unverified') = (evidence IS NULL))`, and an
  integration test against a known profile. The schema protects one code path; the constraint
  protects the table whatever writes to it.
- **III got stronger a third time, from R9.** The five-verdict taxonomy closed a hole the first
  draft shipped: a single evidence-free `missing` verdict let a silent profile become a confident
  *you do not have this*. **Every verdict except `unverified` is now grounded, including negative
  ones** — a `gap` must quote the shortfall. AI-008 forbids inventing experience; the first draft
  left the model free to invent absences.
- **III got stronger again, from R1.** Refusing to score legacy rows means the system declines to
  produce a number it cannot stand behind. Scoring them would have been honest-looking and wrong.
- **IV is enforced structurally.** Append-only is asserted by a source-tree scan, the same
  mechanism slice 003 used for status history — not by reviewer vigilance.
- **VI actively forbade the alternative.** Vector retrieval is reserved for semantic knowledge;
  the profile is structured operational fact. R4's rejection of RAG is a constitutional
  requirement, not only a judgement about token budgets.

One thing the design added that the pre-check did not anticipate: **FR-007 is enforced by a partial
unique index**, not an application-level check. That follows the project convention that business
invariants belong in the schema — an index cannot be raced or forgotten.

## Phase 0 output

[research.md](research.md) — eight decisions, each with what was rejected and why.

## Phase 1 outputs

- [data-model.md](data-model.md) — two new tables, two new columns, the state machine, and the
  invariants that must be asserted rather than assumed.
- [contracts/match-analysis.md](contracts/match-analysis.md) — the completion contract: the schema,
  the prompt's obligations, and the grounding rule that makes AI-008 structural.
- [contracts/http-api.md](contracts/http-api.md) — endpoints, payload shapes, and how the four
  states appear over the wire.
- [quickstart.md](quickstart.md) — the end-to-end proof, including the deployed check.

## Risks carried into tasks

| Risk | Why it matters | Carried as |
|---|---|---|
| **Legacy `job_description` rows** hold requirements, not postings | Scores computed against them are the reversed design, silently | R1; a task must make old rows distinguishable and must not score them as postings |
| **`llm_model_match_analysis` unset** falls back to Opus | 2.5× cost, no quality gain, silent. Already caught CV extraction once | Config line ships in the same commit as the use case; a test asserts the task resolves to a configured model |
| **A background task is fire-and-forget** | An exception with nowhere to go leaves a row `pending` forever | The row is written `pending` first precisely so failure has somewhere to land; a task must prove the failure path writes `failed` |
| **Evidence quoting is 57–86% of cost** | The obvious optimisation (return references) would weaken the grounding check | Explicitly out of scope; recorded so it is a decision, not an oversight |
| **Five verdicts cost more than three** | `gap` now requires evidence, so output grows. The estimates in R8 assumed three verdicts and no `shortfall` field | A task must re-measure cost against a real analysis before the estimate is quoted as fact |
| **The model collapsing to a met/missing binary** | Silently inflates the score and manufactures gaps. Nothing in the schema catches it — every row would be individually valid | Quickstart step 4 checks the verdict spread; a task must assert `unverified` on a profile silent about a named requirement |
| **Test DB schema drift** | `create_all` does not reconcile an existing table; slice 003 lost a release-blocker assertion to this | Any test asserting an absence must be watched failing first |
