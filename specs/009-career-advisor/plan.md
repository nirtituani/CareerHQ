# Implementation Plan: Career Advisor Agent with Career Memory

**Branch**: `009-career-advisor` | **Date**: 2026-09-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/009-career-advisor/spec.md`

## Summary

An advisor run assembles a deterministic **evidence pack** (every quantitative fact, with
denominators and record ids, computed by SQL/Python — the model is never the source of a
number), feeds it to the reasoning step **together with every active memory and every
dismissed memory**, and receives back a set of **memory operations** (create / confirm /
supersede / retire, plus a disposition for every prior active memory). Deterministic
application code then validates each operation against the grounding rules — numerals in a
claim must exist in its cited evidence, every active memory must be dispositioned, the cap
and dismissal gates hold — discards what fails (observably), and persists what survives.
Memories are insert-only with supersession lineage; a dispositions log makes the lifecycle
auditable per run. The surface is the existing `/advisor` navigation entry, activated.

Two completions per run at most: an optional cheap **grouping** step (titles → role
families, requirement texts → skills, over enumerated ids only; skipped when there is no
Tier 2 data) whose output feeds *deterministic counting*, then one **reasoning** step. No
LangGraph, no new dependencies, no vector infrastructure.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7 / Next.js 16 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2; existing
`StructuredCompletion` seam over LiteLLM. **No new dependencies.**

**Storage**: PostgreSQL — three new tables (`advisor_runs`, `career_memories`,
`memory_dispositions`), one migration (`0021`). No pgvector use.

**Testing**: pytest (host, ≥80% coverage gate), Vitest, Playwright available; the drills
in CLAUDE.md §Testing philosophy apply (watched-failing gates, count-what-you-examined).

**Target Platform**: existing Docker Compose stack locally; Railway deployment unchanged.

**Project Type**: web application (existing `backend/` + `frontend/`).

**Performance Goals**: SC-006 — a typical run completes within two minutes wall clock
(match-analysis-like: one or two completions, no fetching, no polling of external services).

**Constraints**: SC-007 — per-run LLM spend of the same order as a match analysis (cents to
low tens of cents): grouping on Haiku, reasoning on Sonnet, both configured **by task name**
(`llm_model_advisor_grouping`, `llm_model_advisor_reason`) — the Opus-fallback pricing trap
is known and each new task gets an explicit entry.

**Scale/Scope**: one user accumulates tens of memories (hard cap 25 active); evidence packs
over ~100 applications; full relational retrieval everywhere.

## Constitution Check

*GATE: evaluated before Phase 0; re-evaluated after Phase 1 design — both pass.*

| Principle | Verdict | How the design satisfies it |
|---|---|---|
| I — Profile is the single source of truth | ✅ | Memories are derived interpretation, never primary data: raw counts recomputable from history at any time (FR-005/006), frozen evidence is a record of past justification, and FR-017 forbids any capability reading memories as profile facts. Nothing is duplicated out of the profile or applications into memory. |
| II — Human-in-the-loop | ✅ | Memories are the agent's own derived understanding, not user-owned professional data — no profile, application or resume row is written by an advisor run, so the approval gate is not in play. The user's control is curation: dismissal retires a memory and is enforced against recreation in two layers (FR-021). |
| III — Explainable and honest AI | ✅ | The grounding gate is the severity-split pattern a third time: a proposed insight whose numbers are not in its cited evidence is **discarded before persistence** and the discard is observable (FR-009). Denominators are mandatory; the small-sample floor and no-causal-claims rule (FR-010) are named, versioned constants in `advisor_rules.py`. |
| IV — Immutable history | ✅ | Memories are insert-only; supersession is a new row with a link; claim and frozen evidence are never edited (FR-012). Status moves forward only (`active → superseded/retired`) — the "lock is about content, not the row" rule. The dispositions log is append-only. |
| V — AI is a capability, not a data owner | ✅ | Both completions go through `complete()` by task name; `UsageRecorder` wraps them so a failed run records what it spent (`ExtractionFailedError.usage`); model config, tokens and cost land on `advisor_runs` in the same transaction as the work. `application/` imports no provider SDK (the existing import-graph test covers the new modules automatically). |
| VI — Structured data first | ✅ | Facts retrieved relationally; LLM output validated against Pydantic schemas whose conditional rules live in `Field(description=...)` (the serialisation rule); memory rows are structured entities with typed lifecycle. No semantic retrieval — deliberately (FR-015). |
| VII — Test-first quality | ✅ | Every gate below is specified with a watched-failing drill; SC-001/002/003 tests assert the count of what they examined; the reasoning double reads its input out of the prompt (testing rule 4). |

**No violations to justify.** Complexity added: two tables + one log table, two config
entries, one page — all within the documented stack.

## Project Structure

### Documentation (this feature)

```text
specs/009-career-advisor/
├── spec.md              # /speckit-specify + /speckit-clarify output
├── plan.md              # This file
├── research.md          # Phase 0 — decisions D1–D15
├── data-model.md        # Phase 1 — tables, constraints, transitions
├── quickstart.md        # Phase 1 — end-to-end validation walkthrough
├── contracts/
│   ├── advisor-api.md   # Route contract
│   └── reasoning-contract.md  # Evidence pack in, memory operations out
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
backend/src/careerhq/
├── domain/models/advisor.py          # AdvisorRun, CareerMemory, MemoryDisposition
├── domain/schemas/advisor.py         # GroupingProposal, AdvisorReasoning (+ ops), evidence types
├── application/
│   ├── advisor_rules.py              # ADVISOR_RULES_VERSION, SMALL_SAMPLE_FLOOR=5,
│   │                                 # ACTIVE_MEMORY_CAP=25, abandonment deadline
│   ├── advisor_evidence.py           # deterministic evidence pack (facts, ids, denominators)
│   ├── advisor_grounding.py          # the gate: numeral check, disposition completeness,
│   │                                 # cap, contradiction, dismissal-recreation
│   └── advise_career.py              # create_pending_run / run_advisor (the use case)
├── api/routes/advisor.py             # routes; registered in main.py's create_app
└── config.py                         # + llm_model_advisor_grouping / _reason
backend/alembic/versions/0021_career_advisor.py
backend/tests/{unit,integration}/...  # per tasks.md

frontend/src/
├── app/advisor/page.tsx              # the activated /advisor page
├── components/advisor/               # memory card, lineage, run status, empty states
├── components/sidebar-nav.tsx        # /advisor entry: ready: false → true
└── lib/api.ts                        # advisor client functions + types
```

**Structure decision**: mirrors match analysis end to end — same layering, same
pending-row/background/poll lifecycle, same route registration point (`main.py`), same
frontend client pattern. No new architectural shapes are introduced; the novel parts
(evidence pack, grounding gate, dispositions log) are plain application modules.

## Phase 0 — research.md

Fifteen decisions (D1–D15), each with rationale and alternatives: run lifecycle reuse, the
evidence-pack shape, one-vs-two completions, grouping mechanics, the numeral-grounding
algorithm, dispositions as a log table, lifecycle column semantics, the dismissal
"materially differs" test, cap enforcement, Tier 1 fact families, scope representation,
model/task configuration, why no LangGraph, why no port, and failure/abandonment handling.
All Technical Context items are resolved; no NEEDS CLARIFICATION remains.

## Phase 1 — design artifacts

- **data-model.md** — three tables with columns, check constraints (status vocabularies,
  supersession shape, grounded-evidence invariants where schema-enforceable), the partial
  unique index for one-pending-run-per-user, state transitions, and what is deliberately
  absent (no `is_stale`, no cap constraint in schema — argued inline).
- **contracts/advisor-api.md** — five routes (`GET /api/advisor`, `POST /api/advisor/runs`,
  `GET /api/advisor/runs/{id}`, `GET /api/advisor/memories/{id}`,
  `POST /api/advisor/memories/{id}/dismiss`), auth, status codes (202/409 per the match
  pattern), and response shapes including lineage and the honest empty/insufficient states.
- **contracts/reasoning-contract.md** — the evidence-pack rendering the prompts receive,
  the `GroupingProposal` and `AdvisorReasoning` schemas (every conditional rule in
  `Field(description=...)`), and the deterministic validation each operation must survive.
- **quickstart.md** — Docker-stack walkthrough of the full lifecycle demo (first run,
  evidence change, second run with confirm/supersede/retire, dismissal, cap), with the
  commands and expected observations.

## Post-design constitution re-check

Re-evaluated after writing the data model and contracts: verdicts unchanged. The one point
worth flagging to review: `last_confirmed_at` and forward-only `status` **do** move on a
persisted memory row — this is the established "lock is about content, not the row" reading
of Principle IV (claim, evidence, kind, scope are immutable; lifecycle position is not), and
the dispositions log preserves the full history of those moves.
