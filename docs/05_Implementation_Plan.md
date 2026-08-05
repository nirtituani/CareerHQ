# CareerHQ

> **Implementation Plan**

**Version:** 1.0
**Status:** Active
**Author:** Nir Tituani
**Last Updated:** August 2026

---

# 1. Purpose

This document is the roadmap: what gets built, in what order, and why that order.

It is intentionally the shortest of the design documents, because the detailed plans are
**executable artifacts** rather than prose. CareerHQ is built with Spec-Driven Development using
[GitHub Spec-Kit](https://github.com/github/spec-kit), so each slice carries its own specification,
technical plan, and task list under `specs/`.

| Question | Where it is answered |
|---|---|
| What must always be true of CareerHQ? | [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) |
| What are we building, in what order? | This document |
| What exactly does slice N do? | `specs/00N-<name>/spec.md` |
| How is slice N built? | `specs/00N-<name>/plan.md` |
| What are the concrete steps? | `specs/00N-<name>/tasks.md` |

The design documents in this folder (00–04, 06) describe the *target* system. This document
describes the *path* to it.

---

# 2. Method

Every slice follows the same loop:

```text
specify  →  plan  →  tasks  →  analyze  →  implement  →  verify
```

Each step produces a reviewable artifact and pauses for approval before the next begins. The
`analyze` step is a cross-artifact consistency check that runs before any code is written — it
catches requirements with no task coverage, drift between documents, and conflicts with the
constitution while they are still cheap to fix.

---

# 3. Slicing Principle

**Vertical slices, not horizontal layers.**

Each slice ships something demonstrable end to end — API, user interface, and tests — rather than
completing one architectural layer across the whole product. A slice is not finished when its code
is written; it is finished when it can be demonstrated against the running Docker Compose stack.

The alternative — building the entire data layer, then the entire API, then the entire frontend —
defers all learning to the end and produces months of work that has never been run together. This
matters more here than usual, because several architectural decisions (ADR-005 LangGraph, ADR-008
RAG) are still marked *Proposed* and only survive contact with a working system.

---

# 4. Roadmap

| # | Slice | Delivers | Depends on | Status |
|---|---|---|---|---|
| 001 | Platform Foundation | Containerized environment, Google sign-in, authenticated shell, CI | — | **In progress** |
| 002 | Application Tracking | Applications, companies, status lifecycle, JobTracker import, dashboard | 001 | Planned |
| 003 | Professional Profile | Profile aggregate and value objects, Resume Profiles, profile editor | 001 | Planned |
| 004 | Resume Tailoring | LangGraph workflow, RAG retrieval, match analysis, approval, PDF export | 002, 003 | Planned |
| 005 | Company Research | Research agent, web search, citation-preserving snapshots | 002 | Planned |
| 006 | Career Advisor | Recurring skill-gap detection, learning priorities | 002, 004 | Planned |

---

## 4.1 Slice 001 — Platform Foundation

**Delivers**: A developer clones the repository, runs one command, signs in with Google, and lands
on an authenticated dashboard, with every quality gate green.

Docker Compose (PostgreSQL with pgvector, Redis, MinIO), a layered FastAPI backend with versioned
migrations and a dependency-aware health check, Google OAuth that provisions the user and their
single empty Professional Profile, a Next.js shell, and GitHub Actions running lint, type checks,
and tests.

**Why first**: Nothing else can be built, demonstrated, or tested until the environment starts
reliably and requests carry an identity.

**Artifacts**: [`specs/001-platform-foundation/`](../specs/001-platform-foundation/)

---

## 4.2 Slice 002 — Application Tracking

**Delivers**: The Application and Company aggregates, the status lifecycle with append-only
history and normalized analytics categories, notes, contacts, salary, and links — plus an import
that brings existing JobTracker data across.

**Why second**: It is the domain already proven in production in
[JobTracker](https://github.com/nirtituani/job-tracker-web), so the requirements are known rather
than guessed, and there is real data to import. That makes it the fastest route to a system that
is genuinely useful rather than merely running.

**Migration note**: JobTracker's `rejected` boolean must not survive as an independent source of
truth. Rejection is derived from the normalized status, per
[03_Domain_Model.md](03_Domain_Model.md) §14. This is a constitutional constraint, not a
preference.

---

## 4.3 Slice 003 — Professional Profile

**Delivers**: The ProfessionalProfile aggregate populated with its value objects — work
experience and bullets, skills, projects, education, certifications, languages — plus Resume
Profiles and the editor to maintain them.

**Why third**: It is the largest purely deterministic slice, and slice 004 cannot tailor a resume
that does not exist. Building it before any AI touches it also proves the profile stands on its
own, which is what Principle I claims.

---

## 4.4 Slice 004 — Resume Tailoring

**Delivers**: The flagship capability. A LangGraph workflow that analyzes a job description,
retrieves relevant knowledge, proposes tailored content, **pauses for explicit human approval**,
and only then creates a Resume Version — exported to PDF and frozen as an immutable Submitted
Resume when linked to an application.

Also introduces the Knowledge Context: document ingestion, chunking, embeddings, and pgvector
retrieval with citations preserved.

**Why fourth**: It depends on both a profile to tailor and applications to learn from. It is also
where the two *Proposed* ADRs become real, so it deliberately follows slices that de-risk
everything else first.

**The constraint that matters**: structured facts are retrieved relationally; only semantic
knowledge goes through vector search ([03_Domain_Model.md](03_Domain_Model.md) §7.5). Embedding
structured profile data and asking a model to retrieve it yields approximate answers to questions
the database answers exactly.

---

## 4.5 Slice 005 — Company Research

**Delivers**: On-demand company research with web search, summarized into immutable snapshots that
preserve their sources and retrieval timestamps.

---

## 4.6 Slice 006 — Career Advisor

**Delivers**: Analysis across accumulated application history and interview feedback to surface
recurring skill gaps and recommend learning priorities, each with supporting evidence.

**Why last**: It is the one capability that is worthless without history. It needs applications,
match analyses, and feedback to have accumulated first — which is exactly the "intelligence over
time" premise from [00_Product_Vision.md](00_Product_Vision.md).

---

# 5. Deferred from the MVP

Kept in the architecture, not built yet:

| Capability | Why deferred |
|---|---|
| Evaluation framework (LLM-as-judge, regression suites, RAG retrieval metrics) | There is nothing to evaluate until slice 004 produces output. The `EvaluationResult` entity stays in the domain model so adding it later is not a schema migration. |
| Multi-provider routing (OpenAI, Gemini) | LiteLLM makes providers swappable by configuration. Building routing before a second provider is needed is speculative complexity. |
| Interview coach, learning planner, cover letters, LinkedIn and calendar integration | Out of scope for Version 1 per [01_Functional_Product_Requirements.md](01_Functional_Product_Requirements.md) §11. |

---

# 6. Corrections to the Original Design

Recorded here so the design documents and the implementation do not silently diverge.

| # | Original | Correction | Reason |
|---|---|---|---|
| 1 | OpenAI embeddings ([06](06_Technology_Stack.md) §7) | Configurable embeddings interface, local sentence-transformers by default | The chosen primary provider is Anthropic, which has no embeddings endpoint. A local default also keeps the stack runnable with no API key. |
| 2 | Single `0001_foundation` migration | `0001_extensions` and `0002_users_profiles` | Keeps the environment slice shippable independently of the identity slice. |
| 3 | JobTracker `rejected` boolean | Derived from normalized status | Two sources of truth for the same fact drift apart. Already required by [03](03_Domain_Model.md) §14; restated because import code is where it would be violated. |

---

# 7. Definition of Done

A slice is complete when **all** of the following hold:

- Every functional requirement in its specification has passing test coverage
- Backend test coverage is at or above 80%; Ruff and mypy pass
- The quickstart script runs clean from a fresh clone against the Docker Compose stack
- The capability can be demonstrated end to end to a person, not just to a test runner
- Design documents and code agree — where they disagree, one of them was updated deliberately

---

# 8. Current Status

**Active slice**: 001 — Platform Foundation
**Stage**: Tasked and analyzed; implementation not started
**Artifacts**: specification, plan, research, data model, API contracts, quickstart, 69 tasks
**Next checkpoint**: User Story 1 (`T001`–`T030`) — one command brings the platform up healthy

Progress is tracked in `specs/001-platform-foundation/tasks.md`. This section is updated as slices
complete.
