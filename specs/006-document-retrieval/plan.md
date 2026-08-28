# Implementation Plan: Document & Retrieval

**Branch**: `006-document-retrieval` | **Date**: 2026-08-27 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md), and the corpus research in
[corpus-research/](corpus-research/) — `source-register.md` (22 sources, triaged),
`before-after-analysis.md` (canonical example analysis), `README.md` (vocabularies).

## Summary

Replace the Tailoring agent's static rubric with retrieval over a **curated corpus of
internally-authored rules**, and turn an approved version into a sendable, permanently locked
document.

The retrieval half is deliberately small in surface area: slice 005 already defined
`GuidelineSource`, so this slice writes an implementation behind it and changes no node, no state
key, and no finalisation rule. What is *new* is the corpus itself and the machinery to author,
store, embed, retrieve and cite it.

**The corpus is authored, not ingested.** The research produced two secondary digests summarising
70+ sources; those are evidence that informs authoring, never corpus content. A chunk lifted from
a digest reads "Indeed presents a 6-part framework…" — text *about* guidance rather than guidance,
a poor retrieval unit, and a citation pointing at our own summary. Authoring in CareerHQ's own
words with a citation to the source resolves licensing, keeps rules atomic, and makes a citation
mean "this rule derives from X".

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7 / Next.js 16 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic, `pgvector`,
`sentence-transformers` (local embeddings), **WeasyPrint** (PDF rendering, BSD-3 — needs Pango/Cairo/GObject system libraries, T049), `pdfplumber`
(already present — used as the *independent verifier* for export, not the renderer)

**Storage**: PostgreSQL 18 with the `vector` extension — **already enabled** by migration
`0001_extensions`; no new database technology. Rendered documents in the existing S3-compatible
object storage.

**Testing**: pytest (≥80% coverage gate), Vitest + Playwright on the frontend

**Target Platform**: Linux containers, deployed on Railway

**Project Type**: Web application — `backend/` + `frontend/`

**Performance Goals**: retrieval adds ≤5s to end-to-end tailoring (SC-007) and ≤10% to cost per
run (SC-008), both **measured, not derived**

**Constraints**: English CV output only; Israeli high-tech market priority; retrieved context
bounded by an explicit configured token ceiling (FR-014); no embedding provider SDK importable
from `application/`

**Scale/Scope**: Corpus V1 **~95–130 authored rules, ~7,200–9,900 tokens** at the measured
76 tokens/rule (2026-08-28; the earlier ~4,000–5,500 assumed 42 tokens/rule, taken from the
bare-imperative rubric before any corpus rule existed — `research.md` R6). Rule count unchanged.
Retrieval returns **≈19 rules** under the unchanged 1,500-token ceiling: that ceiling is a budget
per run, not a target corpus size. (Revised down from
150–250 after source-quality triage removed SEO-cluster duplication). Six categories. Corpus fits
comfortably in a prompt — see *Why RAG* below.

### Why RAG, stated honestly

Corpus V1 fits in context many times over. Retrieval is **not** a scaling necessity at this size,
and the plan says so rather than inheriting slice 004's unverified "genuinely too large for
context" claim as measured fact. RAG is built here because:

1. it is an explicit **graded project requirement** (`docs/reference/01`), and the project's only
   vector retrieval;
2. **targeted retrieval beats a fixed rubric** — the Draft node should see the ~15–25 rules that
   bear on *this* posting, role family and seniority, not all 130;
3. **growth headroom** — the corpus is designed to grow, and the threshold at which retrieval
   becomes necessary (~200 rules / ~8,450 tokens) is one authoring pass away.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design.*

| Principle | Assessment |
|---|---|
| **I — Profile is the single source of truth** | ✅ The corpus holds *writing guidance*, never professional facts. No profile content is embedded (Constitution VI, ADR-008). |
| **II — Human-in-the-loop** | ✅ Unchanged. Retrieval alters what the Draft node is *advised*, never what is applied without approval. Export and submission are user-initiated. |
| **III — Explainable and honest AI** | ⚠️ **The gate this slice must actively defend.** Retrieved text enters the prompt of the component that writes claims. Research surfaced two live hazards: *"defensible estimates when hard numbers are unavailable"* and a *70–80% keyword-coverage quota*. Both are **rejected from the corpus**, and FR-013 requires retrieved content be treated as data, never instructions. See *Truth-preservation* below. |
| **IV — Immutable history** | ✅ `SubmittedResume` is insert-only with a checksum over the rendered bytes; profile changes never alter it. |
| **V — AI is a platform capability** | ✅ Embeddings sit behind an application port with an infrastructure adapter; `test_the_application_layer_imports_no_provider_sdk` continues to hold. Every embedding invocation records configuration and usage. |
| **VI — Structured data first** | ✅ This slice *is* the implementation of VI's retrieval clause: semantic knowledge via pgvector **with citation metadata preserved**. Structured facts stay relational. |
| **VII — Test-first quality** | ✅ Ports, retrieval, export and immutability all get tests before implementation; the export verification is itself a test suite (below). |

**No violations requiring justification.** Complexity Tracking is therefore omitted.

### Truth-preservation safeguards (Principle III)

Four, in order of strength:

1. **Corpus-level.** Fabrication-inviting advice is rejected at authoring time and recorded as
   rejected in `source-register.md`, so it cannot re-enter. Integrity rules are **internally
   authored only** — never sourced externally.
2. **Prompt-level.** Retrieved guidance is rendered in a labelled block as *advice*, positioned so
   it cannot read as instruction, and never overrides the grounding rules.
3. **Workflow-level.** Unchanged and untouched: the Reviewer still judges the composed resume
   against the profile, and `finalise()` still discards `ungrounded` proposals before persistence.
   **Retrieval cannot weaken a guardrail it sits upstream of.**
4. **Test-level.** A test asserts no corpus rule instructs estimation, quota-filling, or adding
   unsupported claims.

## Project Structure

### Documentation (this feature)

```text
specs/006-document-retrieval/
├── spec.md                  # Requirements (FR-001…FR-029)
├── plan.md                  # This file
├── research.md              # Phase 0 — decisions D1–D8 and corpus findings
├── data-model.md            # Phase 1 — entities and schema deltas
├── quickstart.md            # Phase 1 — how to validate the slice end to end
├── contracts/               # Phase 1 — port and export contracts
├── checklists/requirements.md
├── corpus-research/         # Research inputs (not shipped corpus)
└── tasks.md                 # NOT created by /speckit-plan
```

### Source code

```text
backend/
├── corpus/                              # NEW — the authored corpus, version-controlled
│   ├── universal/*.md                   #   one file per category, front-matter + rules
│   ├── israel/*.md
│   ├── ats/*.md
│   ├── integrity/*.md
│   ├── tailoring/*.md
│   └── role-seniority/*.md
├── src/careerhq/
│   ├── application/
│   │   ├── guidelines.py                # EXISTS — port + static fallback, unchanged in shape
│   │   ├── embeddings.py                # NEW — EmbeddingSource port (no SDK import)
│   │   └── export.py                    # NEW — export/submit use cases
│   ├── domain/models/
│   │   ├── knowledge.py                 # NEW — KnowledgeDocument, KnowledgeChunk
│   │   └── tailoring.py                 # AMEND — VersionStatus += EXPORTED, SUBMITTED
│   ├── infrastructure/
│   │   ├── knowledge/                   # NEW — corpus loader, chunker, retrieval
│   │   ├── embeddings/                  # NEW — local sentence-transformers adapter
│   │   └── documents/render.py          # NEW — WeasyPrint behind a boundary (readers exist)
│   └── api/routes/                      # AMEND — export + submit endpoints
├── alembic/versions/                    # NEW — knowledge tables, SubmittedResume, status values
└── tests/
    ├── unit/                            # port contracts, corpus lint, chunk integrity
    └── integration/                     # retrieval, export round-trip, immutability

frontend/src/                            # AMEND — export/submit affordances, cited guidance display
```

**Alembic coordination.** The head is `0014_displaced_position`. **Slice 008 is being designed in
parallel and will also want the next revision** — whoever writes second **rebases rather than
branching** the migration history. Slice 008's plan carries the same note; both must stay in step.

**Structure Decision**: Web application layout, matching the existing repository. The corpus lives
under `backend/corpus/` as version-controlled Markdown — decision D1 requires it be curated and
reviewable in pull requests, which a database-only corpus would not be.

### Retrieval latency instrumentation (D6, FR-039)

SC-007 is a **measured** ≤500ms threshold, so this slice records the duration of each retrieval
operation — start through final selected guideline set — excluding embedding-model initialisation.
Deliberately narrow: one timing around one operation, no new observability infrastructure.

**Not in scope**: per-call LLM timestamps on `tailoring_run_calls`. That is the other half of
M-001 and belongs to slice 007; adding it here would widen this slice to solve a problem SC-007
does not have.

## Phase status

- **Phase 0** — [research.md](research.md) ✅
- **Phase 1** — [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md) ✅
- **Phase 2** — `tasks.md`, produced by `/speckit-tasks`. **Not created by this command.**

## Post-design Constitution re-check

Re-evaluated after Phase 1. No gate moved. The design adds one port (embeddings), two entities and
one status pair; it removes no guardrail and changes no node. Principle III's defence is stronger
after design than before it, because the severity split and the Reviewer both sit *downstream* of
retrieval and are untouched by it.
