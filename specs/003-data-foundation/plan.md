# Implementation Plan: Data Foundation

**Branch**: `003-data-foundation` | **Date**: 2026-08-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-data-foundation/spec.md`

## Summary

Populate a user's Professional Profile from a CV they already have, give them somewhere to record
a job with its description, and seed real history from JobTracker.

The technical shape follows from one decision (spec D1): extraction is a **single structured
completion call behind a Protocol seam**, implemented in `infrastructure/` by a LiteLLM adapter and
substituted in tests by a fake. That seam is the highest-value artifact this slice produces,
because slice 004 inherits it — see [research.md](./research.md) R1, which designs it so docs/08
§3.2.3's per-node model mapping becomes configuration keyed by task name rather than model
identifiers scattered through workflow code.

Everything else is deterministic: text out of PDF/DOCX, a review interface, relational writes in
one transaction, and invariants pushed into the schema.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 7 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2 — all existing.
**New**: `litellm 1.96.2` (AI gateway), `pdfplumber 0.11.10` (PDF text, MIT),
`python-docx 1.2.0` (DOCX text, MIT). Versions verified against PyPI, not recalled.

**Storage**: PostgreSQL 18 + pgvector (vector unused this slice, R9). **Railway native bucket**
for uploaded CVs, S3-compatible, filling the existing `S3_*` settings (R5).

**Testing**: pytest with async support, ≥80% coverage gate; vitest for components; Playwright for
flows. The extraction seam is replaced by a dependency override so the suite needs no API key and
no network (FR-027, R2).

**Target Platform**: Linux containers — Docker Compose locally, Railway deployed.

**Project Type**: Web application — `backend/` + `frontend/`.

**Performance Goals**: CV import completes within one interactive wait (single model call plus
text extraction). No batch or streaming requirements in this slice.

**Constraints**: No agent loop, no second model call, no embeddings (R9). Imports must not
partially commit (FR-023). The suite must pass with no provider configured.

**Scale/Scope**: Single-user-at-a-time interactive use. JobTracker import is ~20 records — well
inside a single transaction.

## Constitution Check

*GATE: evaluated before Phase 0, re-evaluated after Phase 1 design.*

| Principle | Status | How this design satisfies it |
|---|---|---|
| **I** — Profile is single source of truth | ✅ Pass | Exactly one `ProfessionalProfile` per user, already enforced by `UNIQUE (user_id)` from slice 001. The Master Resume references profile facts; it does not copy them. FR-009 forbids a second profile on re-import |
| **II** — Human-in-the-loop (non-negotiable) | ✅ Pass | The approval gate *is* User Story 1. Extracted content is staged in `ImportedResume`, never written to the profile until approved (FR-003, FR-007). FR-029 removes the loophole: no confidence score exempts an item from review |
| **III** — Explainable and honest AI | ✅ Pass | Every extracted item carries source and confidence (FR-004). Extraction that yields little says so rather than presenting an empty form (FR-008). Fixture mode is labelled as fixture data and never selected silently (R3) |
| **IV** — Immutable history | ✅ Pass | Status history is insert-only with no update or delete path (R7). No Submitted Resume exists yet, so the locking rules arrive with slice 004 |
| **V** — AI is a platform capability, not a data owner | ⚠️ **Required design work — resolved** | This is the gate this slice had to earn. Extraction is an LLM call inside a slice whose business domain must stay deterministic. Resolved structurally: the call sits behind a `Protocol` in the application layer, implemented only in `infrastructure/`. `domain/` and `application/` import no provider code, so the principle is a property of the import graph rather than a rule someone remembers. Model, tokens and cost are recorded per call (FR-026) |
| **VI** — Structured data first | ✅ Pass | The seam cannot return unvalidated text — a schema is a required argument and the return is typed (R1). Validation failure is extraction failure (FR-025). Retrieval is relational; no embedding of structured facts (R9, docs/03 §7.5) |
| **VII** — Test-first quality | ✅ Pass | Tests precede implementation per CLAUDE.md. The ≥80% gate holds. FR-027's seam keeps the suite deterministic and offline |

**Re-evaluation after Phase 1**: no new violations. The one gate needing design work (V) is
resolved by the port/adapter split, and the split is visible in the source tree below rather than
asserted here.

**No entries in Complexity Tracking** — nothing in this design requires a justified deviation.

## Project Structure

### Documentation (this feature)

```text
specs/003-data-foundation/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R9
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1
│   ├── extraction-seam.md
│   └── http-api.md
├── checklists/
│   └── requirements.md
├── spec.md
└── tasks.md             # /speckit-tasks — not created here
```

### Source Code (repository root)

```text
backend/src/careerhq/
├── domain/
│   ├── models/                 # models.py becomes a package; __init__ re-exports
│   │   ├── __init__.py         #   so every existing `from ...domain.models import User` still works
│   │   ├── identity.py         #   User, ProfessionalProfile          (moved, unchanged)
│   │   ├── profile.py          #   WorkExperience, ExperienceBullet, Skill, Education, …
│   │   ├── application.py      #   Application, Company, ApplicationStatusHistory
│   │   └── imports.py          #   ImportedResume, ExtractionItem
│   └── schemas/                # same treatment; extraction schemas live here
│       ├── __init__.py
│       ├── extraction.py       #   the Pydantic model the LLM must fill — the contract in R1
│       └── …
├── application/
│   ├── ports.py                # ★ StructuredCompletion Protocol, Completion[T], Usage
│   ├── extract_resume.py       #   upload → text → seam → staged ImportedResume
│   ├── approve_import.py       #   staged + corrections → profile + Master Resume, one transaction
│   ├── record_application.py
│   └── import_jobtracker.py    #   validate/partition, then one transaction (R6)
├── infrastructure/
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── litellm_gateway.py  # ★ the only module importing litellm
│   │   └── fixture_gateway.py  #   opt-in, labelled; never the default (R3)
│   ├── documents/
│   │   ├── pdf.py              #   pdfplumber
│   │   └── docx.py             #   python-docx
│   └── storage.py              #   unchanged — already speaks S3 (R5)
├── api/
│   ├── deps.py                 #   + get_structured_completion (the override point, R2)
│   └── routes/
│       ├── imports.py
│       ├── applications.py
│       └── health.py           #   + ai_provider in readiness (FR-028)
└── config.py                   #   + AI_PROVIDER, per-task model map, ai_provider_configured

backend/alembic/versions/0003_*.py   # profile children, applications, companies, imports

frontend/src/
├── app/
│   ├── import/page.tsx         #   upload + review + approve
│   └── applications/
│       ├── page.tsx
│       └── new/page.tsx
├── components/
│   └── import-review/          #   per-item accept / correct / discard, source+confidence shown
└── lib/api.ts                  #   extended
```

**Structure Decision**: the existing `backend/` + `frontend/` split is kept unchanged. Two
deliberate refactors: `domain/models.py` and `domain/schemas.py` become **packages** whose
`__init__.py` re-exports every existing name, so no import in slice 001 code changes while this
slice adds roughly a dozen entities. The alternative — one file growing to a thousand lines — makes
review harder for no benefit.

The starred files are the seam. `litellm_gateway.py` is intended to be **the only module in the
codebase that imports `litellm`**, and that is worth asserting in a test: an import-graph check is
how Principle V stops depending on reviewer vigilance.

## Phase 1 outputs

- **[data-model.md](./data-model.md)** — entities, relationships, and the six schema constraints
  from R7 with the reason each is a constraint rather than a check
- **[contracts/extraction-seam.md](./contracts/extraction-seam.md)** — the `StructuredCompletion`
  contract and its obligations, written so slice 004 can implement against it without re-reading
  this plan
- **[contracts/http-api.md](./contracts/http-api.md)** — endpoints, ownership rules, status codes
- **[quickstart.md](./quickstart.md)** — how to run and validate the slice end to end, including
  the provider-key question

## Risks carried into tasks

| Risk | Handling |
|---|---|
| **JobTracker export shape is unknown** (R8) | A real export is a required input to User Story 3. US3 is P3, so the critical path is unaffected — but the mapping is not written until the file exists, because FR-016 is a release blocker and cannot be mapped against a guess |
| **Extraction quality is the slice's main uncertainty** | SC-002 (80% of bullets attributed to the right role) is measured against a real CV early, not at the end. If it misses, the honest responses are a better prompt or a stronger model — both configuration under R1 — not a lowered criterion |
| **Two new deployment prerequisites** | Bucket and provider credentials. Both surface through readiness as `not_configured` before they are set (FR-021, FR-028), so the failure is named rather than mysterious. Slice 002's lesson: an unstated deployment assumption appears as a five-minute health-check timeout with no application error |
| **Railway bucket endpoint form unverified** | `storage.py` already passes `endpoint_url`; path-style addressing is a configuration flag if needed. Verified during implementation, not assumed |
