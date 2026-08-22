# Implementation Plan: Resume Tailoring

**Branch**: `005-resume-tailoring` | **Date**: 2026-08-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-resume-tailoring/spec.md`, and the approved design
at [`docs/superpowers/specs/2026-08-22-resume-tailoring-design.md`](../../docs/superpowers/specs/2026-08-22-resume-tailoring-design.md)

## Summary

Adapt the owner's resume to a recorded job through a bounded agent loop that criticises its own
work, and let the owner approve or reject every change item by item.

Four workflow steps — plan, draft, review, revise — orchestrated by LangGraph, each calling the
existing completion seam. The Reviewer runs on the stronger model and can send work back twice,
escalating the reviser on the second attempt. Claims it judges unsupported are discarded **before
persistence**, so they never reach an approve button; matters of degree are shown to the owner
flagged. LangGraph owns execution flow only: persistence, business state, audit, ownership and
finalisation all stay in CareerHQ.

This is the project's **first agent loop**. Every prior AI call is one structured completion in, one
validated object out.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2, LiteLLM;
**new: `langgraph>=1.2.11,<1.3`** (verified on PyPI, requires `>=3.10`). Frontend: Next.js 16 App
Router, Tailwind 4, shadcn/ui.

**Storage**: PostgreSQL 18 with pgvector. Four new tables, two migrations. No vector use in this
slice.

**Testing**: pytest with ≥80% coverage gate, mypy strict, ruff; Vitest and Playwright on the
frontend. **No test may make a live provider call** (FR-045).

**Target Platform**: Docker Compose locally; Railway deployed (frontend public, backend and
database internal).

**Project Type**: Web application — FastAPI backend, Next.js frontend.

**Performance Goals**: A draft to approve within 90 seconds when review passes first time; within 3
minutes when the full revision budget is spent (SC-001). Both are **targets awaiting measurement**.

**Constraints**: A run costs no more than $0.30 (SC-006, unmeasured — the last estimate in this
project was 87% low). Worst case is seven model calls, three of them Opus reviews. **Draft and
Revise must return item identifiers with changed text, never the whole resume re-emitted** — output
is 57–86% of cost and the slow half of a completion.

**Scale/Scope**: Single user per profile, one job tailored at a time. Roughly 30–60 items per
version. Four HTTP routes, two migrations, one new frontend tab.

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 below.*

| Principle | How this slice satisfies it | Risk |
|---|---|---|
| **I — Profile is the single source of truth** | Versions derive from the master and record its state at creation. Excluding an item from a version does not touch the profile (FR-033, FR-021). | `original_text` is **copied**, not referenced — justified in Complexity Tracking. |
| **II — Human-in-the-loop (non-negotiable)** | No proposal enters a saved version without approval (FR-023), per item (FR-024), reversible (FR-026), and approval starts nothing further (FR-028). | The default-accept rule (FR-025) must mirror import review, or it becomes a second pattern. |
| **III — Explainable and honest AI** | Unsupported claims are discarded before persistence (FR-018) and never shown as a choice. Findings are displayed against the items they concern (FR-042). Every version is presented as AI-generated (FR-022). | **The release blocker of this slice.** FR-046 requires the test be watched failing. |
| **IV — Immutable history** | A version does not change when the profile or its master changes (FR-031). Runs are append-only audit records. | `submitted` and its lock are slice 006; this slice adds no state that claims immutability it does not enforce. |
| **V — AI is a platform capability, not a data owner** | Nodes hold no session and write nothing (contract O2); the use case owns every transaction (O3). Usage returned, not logged internally (O5). Enforced by the import-graph test. | **The guard is currently weaker than assumed** — research R2. Widening it is a task, landing with the dependency. |
| **VI — Structured data first** | Every model output validated against a declared schema (FR-037). Findings carry a closed `kind` set so finalisation can route on it. No vector retrieval in this slice. | — |
| **VII — Test-first quality** | ≥80% coverage, ruff, mypy. Absence tests watched failing. Status paths exercised against re-read records (FR-047). | The two-revision path is untestable until the fixture gateway returns sequences (R10). |

**No unjustified violations.** One justified departure is recorded in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/005-resume-tailoring/
├── plan.md              # This file
├── spec.md              # 48 functional requirements, three user stories
├── research.md          # Phase 0 — R1–R10
├── data-model.md        # Phase 1 — four tables, two absences
├── quickstart.md        # Phase 1 — how to prove it works
├── contracts/
│   ├── tailoring-workflow.md   # O1–O8: the LangGraph/CareerHQ boundary
│   └── http-api.md             # Four routes, ownership from the session
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks — not created here
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/
│   ├── 0010_resume_versions.py
│   └── 0011_version_items_and_findings.py
├── src/careerhq/
│   ├── api/routes/tailoring.py            NEW  four routes
│   ├── application/
│   │   ├── tailor_resume.py               NEW  the use case: transactions, finalisation, audit
│   │   ├── finalisation_rules.py          NEW  named + versioned, beside match_criteria.py
│   │   ├── guidelines.py                  NEW  GuidelineSource port + static rubric
│   │   ├── agents/tailoring/              NEW  ← LangGraph lives here and nowhere else
│   │   │   ├── graph.py                        nodes, edges, the conditional edge
│   │   │   ├── state.py                        frozen dataclass + append reducers
│   │   │   └── prompts.py                      one builder per node
│   │   └── ports.py                       UNCHANGED
│   ├── domain/
│   │   ├── models/tailoring.py            NEW  four tables
│   │   └── schemas/tailoring.py           NEW  plan, draft, review schemas
│   └── config.py                          MOD  five llm_model_<task> entries
└── tests/
    ├── unit/test_architecture.py          MOD  widen the forbidden provider list
    ├── unit/test_finalisation_rules.py    NEW
    ├── integration/test_tailoring_workflow.py  NEW  the five paths
    └── conftest.py                        MOD  fixture gateway returns sequences

frontend/src/
├── components/applications/
│   ├── tailor-tab.tsx                     NEW  the diff and approval surface
│   ├── tailor-diff-item.tsx               NEW  original / proposed / finding / decision
│   └── detail-tabs.tsx                    MOD  add the tab
└── lib/api.ts                             MOD  four calls
```

**Structure Decision**: the existing layered backend (`api/ → application/ → domain/`, with
`infrastructure/` implementing declared ports) and the Next.js App Router frontend. The one new
concept is `application/agents/tailoring/`, sited under `application/` **so the import-graph guard
covers it** — that placement is what makes contract O2 enforceable rather than advisory.

## What research found that the design did not know

Three things, each of which would have been discovered during implementation at higher cost.

**The checkpointer is not avoidable, only unused** (R1). `langgraph-checkpoint` is a hard transitive
dependency carrying the in-memory saver. What is actually declined is
`langgraph-checkpoint-postgres`, a separate package. The design's §3.2 reads as though the
dependency is avoided; it is not, and the lockfile will say so.

**The import guard forbids exactly one package** (R2). Adding LangGraph makes this worse rather
than merely incomplete: `langchain-core` arrives transitively, so `langchain_anthropic` becomes one
install away, and the idiomatic LangGraph example binds a model inside the node. Widening the guard
must land in the same commit as the dependency.

**`usage` will silently keep only its last entry** unless the state key carries an append reducer
(R3). LangGraph overwrites keys without one. The audit trail would be incomplete and the cost figure
wrong by up to 7×, and *nothing raises*. It looks like a cheap run.

## Constitution re-check, after Phase 1 design

Re-evaluated against the artifacts rather than the intent.

- **Principle V holds structurally**, but only after R2's task lands. Until then it holds by
  convention, which is what Principle V exists to avoid. This is the highest-priority task in the
  slice and is sequenced first.
- **Principle III holds** provided finalisation runs in the use case (O3) and `reviewer_findings.kind`
  stays a closed set (R9). A free-text concern cannot be routed, and FR-018 is a release blocker.
- **Principle I's departure is justified and recorded** below.
- **Principle VII is at risk from one gap**: the fixture gateway cannot yet return different results
  for successive calls to the same task, so the two-revision and exhausted-budget paths — where
  FR-013 and FR-018 live — are untestable. Sequenced before the graph.

No new violations.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `resume_version_items.original_text` **copies** profile text rather than referencing it (Principle I says reference, not duplicate) | FR-031 and Principle IV require a version not to change when the profile does. A reference would make an approved diff mutate underneath it. | Referencing the profile fact and rendering current text was rejected: it makes "what you approved" unreproducible, which is the exact failure ADR-012 records lineage to prevent. The copy *is* the lineage snapshot. |
| `plan` and `guidelines_used` stored as `jsonb`, where slice 004 stores requirements as rows | Nothing queries an individual plan line. `jsonb` containment is adequate for slice 007's retrieval-quality measurement. | Normalising both to tables was rejected as cost without a reader. Recorded in `data-model.md`: the arrival of a query wanting a row per guideline is the signal to normalise. |

## Risks carried into tasks

| Risk | Handling |
|---|---|
| **SC-006 ($0.30) and SC-001 (90s/3min) are unmeasured.** The last estimate in this project was 87% low. | Measure both paths on a real run; record in `research.md`. If missed, mark missed in `spec.md` rather than adjusting the target. |
| **The confidence threshold has no calibrated value.** | An uncalibrated constant inside a *named* rules version, so slice 007 can change it honestly. |
| **The reaper's abandonment threshold cannot be copied from match analysis.** A run legitimately in its second revision must not be released. | Named constant with reasoning beside it; test both sides. |
| **A second render path costs an affordance every time** (slice 003: Edit, Add, Remove each went missing from grouped skills). | One item component for every source kind. If a second appears, that is the signal to stop. |
| **Display bugs are invisible to the suite.** Four in slice 003 were extracted correctly and dropped by the renderer. | `quickstart.md` §4 is a required step, on real data, in a browser, on `localhost`. |

## Phase 0 output

[`research.md`](research.md) — R1 through R10. No `NEEDS CLARIFICATION` remained: the approved
design resolved what would otherwise have been unknowns, and research addressed the three things it
had got wrong or left open.

## Phase 1 outputs

- [`data-model.md`](data-model.md) — four tables, the amended lifecycle, and two load-bearing
  absences
- [`contracts/tailoring-workflow.md`](contracts/tailoring-workflow.md) — O1–O8, the
  LangGraph/CareerHQ boundary
- [`contracts/http-api.md`](contracts/http-api.md) — four routes
- [`quickstart.md`](quickstart.md) — including the browser pass that finds what the suite cannot
