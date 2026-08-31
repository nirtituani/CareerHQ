# Implementation Plan: Role-Aware Company Research

**Branch**: `010-role-aware-research` | **Date**: 2026-08-31 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-role-aware-research/spec.md`

## Summary

Research becomes application-scoped and role-aware: one call through a new `ResearchProvider`
port — `research(company_name, domain, role_title, posting_text)` — returning a validated,
sections-first result with sources and an entity identification. Tavily Research
(`POST /research` with `output_schema`) is the first adapter; the 008 search→fetch→synthesise
pipeline is retained behind the same port as the configured fallback, its tiered output stored
unconverted and rendered by a legacy view. Persistence reshapes the **never-wired, provably
empty** `role_research_snapshots` table into `application_research_snapshots` (one migration —
see the correction in research.md D2: the earlier "no migration needed" claim was wrong because
of a NOT NULL lineage column). Reuse and freshness keep 008's 30/90-day windows, re-scoped to
the application. The UI replaces tier badges with the seven POC-validated sections and quiet
provenance.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7 / Next.js 16 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Pydantic v2, httpx (provider adapter —
same client family as `tavily_search.py`), LiteLLM (fallback path only), Tailwind 4 + shadcn/ui

**Storage**: PostgreSQL (existing); JSONB `sections` column carries whichever shape the
producing path emits, discriminated by `prompt_version`

**Testing**: pytest (unit + integration, ≥80% coverage gate), vitest, Playwright; tests first,
each gate watched failing (project testing philosophy rules 1–2)

**Target Platform**: existing Docker stack locally; Railway deployment (deployment itself out of
scope for this slice's definition phase)

**Project Type**: web application (backend `api/ → application/ → domain/` + `infrastructure/`,
frontend Next.js)

**Performance Goals**: research readable ≤90 s for 9/10 runs (SC-003; POC measured provider
32–53 s, fallback 59–104 s); reuse reads ≤2 s (SC-004)

**Constraints**: no CV/profile data in research input (FR-002/SC-007); provider boundary carries
no provider vocabulary (FR-004); 008-era snapshots byte-identical and renderable (FR-014/SC-005);
cost basis recorded on every run including failures (FR-015/SC-006)

**Scale/Scope**: single-user-scale course project; one provider adapter + one fallback; ~33
applications of real data today

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0 before Phase 0; re-checked
after Phase 1 design — both passes.*

| Principle | Verdict | How the design satisfies it |
|---|---|---|
| I. Profile is single source of truth | PASS (by exclusion) | Research reads no profile data at all — FR-002 forbids it and SC-007 tests it with a sentinel. Research is *about the employer*, derived from the application. |
| II. Human-in-the-loop | PASS | Research modifies no user-owned data; it is advisory reading material. Runs start only on explicit request (FR-001). |
| III. Explainable and honest AI | PASS | Entity identification with reasoning is part of the result (FR-007); every section traces to listed sources (FR-009); provider-attributed content is never dressed as verified (FR-010); empty sections explain themselves (FR-011). |
| IV. Immutable history | PASS | Snapshots are insert-only with a status transition, never edited (FR-012); old snapshots unmodified (FR-014); failure never evicts the last success (FR-016). |
| V. AI is a platform capability, not a data owner | PASS with a recorded nuance | The port lives in `application/ports.py`; `application/` imports no provider SDK (existing architecture test extends to the new adapter's import). **Nuance**: the provider does not return token usage, so the "token usage and cost" obligation is met by an explicit `cost_basis` marker — a recorded estimate at documented rates, never presented as billed (research.md D5). The fallback path keeps exact LiteLLM usage. |
| VI. Structured data first | PASS | Provider output is validated against a Pydantic schema before persistence; unvalidated output is a failed run (FR-017 edge case); citation metadata preserved per source. |
| VII. Test-first quality | PASS | Plan and tasks order tests before implementation; the reshape migration gets an emptiness guard test; gates assert the count of what they examined. |

No violations requiring Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/010-role-aware-research/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0: decisions D1–D8 (POC evidence consolidated)
├── data-model.md        # Phase 1: reshaped tables, schemas, state transitions
├── quickstart.md        # Phase 1: end-to-end validation guide
├── contracts/
│   ├── research-provider-seam.md   # The port contract and result schema
│   └── api-research.md             # Endpoint request/response contract (both shapes)
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/src/careerhq/
├── api/routes/research.py            # CHANGED: provider selection (one if), context assembly,
│                                     #   response gains shape discriminator; endpoints unchanged
├── application/
│   ├── ports.py                      # CHANGED: + ResearchProvider protocol, ResearchOutcome
│   ├── research_application.py       # NEW: the use case — assemble input, call port, verify,
│   │                                 #   persist; posting via scoreable_posting()
│   ├── research_company.py           # UNCHANGED: becomes the body of the fallback adapter
│   ├── research_persistence.py       # CHANGED: application-scoped create/complete/fail/read;
│   │                                 #   role-snapshot helpers reshaped with the table
│   ├── research_windows.py           # UNCHANGED: same windows, callers re-scope them
│   └── scoreability.py               # UNCHANGED: gains a third caller
├── domain/
│   ├── models/research.py            # CHANGED: RoleResearchSnapshot → ApplicationResearchSnapshot
│   │                                 #   (reshaped, see data-model.md); ResearchSource FK renamed
│   └── schemas/research.py           # CHANGED: + ApplicationResearch (7 sections +
│                                     #   identification); CompanyResearch kept for fallback/legacy
├── infrastructure/research/
│   ├── tavily_research.py            # NEW: the Tavily Research adapter (POST /research)
│   ├── builtin_provider.py           # NEW: fallback adapter wrapping research_company()
│   ├── tavily_search.py              # UNCHANGED (used by the fallback)
│   └── web_fetcher.py                # UNCHANGED (used by the fallback)
└── config.py                         # CHANGED: + research_provider, research_fallback_enabled,
                                      #   research_provider_timeout_seconds

backend/alembic/versions/
└── 0020_application_research.py      # NEW: reshape empty role_research_snapshots (research.md D2)

frontend/src/
├── components/applications/
│   ├── company-tab.tsx               # CHANGED: dispatches on shape discriminator
│   ├── research-sections.tsx         # NEW: sections-first view (7 sections, quiet provenance)
│   └── research-legacy.tsx           # NEW: extracted current tiered renderer (FR-014)
└── lib/api.ts                        # CHANGED: response types for both shapes
```

**Structure Decision**: existing web-application layout; every path above is real. The provider
selection stays in `api/routes/research.py` where `get_web_search`/`get_source_fetcher` already
live — the project's established pattern for "application/ must not import infrastructure"
(`build_guideline_source` precedent). No production file is touched in this phase; the tree
above is the plan for the implementation phase.

## Complexity Tracking

No constitution violations to justify. One deviation from an earlier informal claim is recorded
instead: the decision document said "no schema change required"; inspection during planning
falsified that (NOT NULL lineage column). See research.md D2 for the correction and the chosen
migration shape.
