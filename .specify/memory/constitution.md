<!--
Sync Impact Report
- Version change: (template) → 1.0.0
- Modified principles: all placeholders replaced (initial ratification)
- Added sections: Core Principles (7), Technology Constraints, Development Workflow, Governance
- Removed sections: none
- Follow-up TODOs: none
-->

# CareerHQ Constitution

## Core Principles

### I. Professional Profile Is the Single Source of Truth
Each user owns exactly one Professional Profile. Every Resume Profile, Resume Version,
recommendation, and career insight MUST derive from it. Resume Profiles reference profile
facts — they MUST NOT duplicate them. Resumes are generated artifacts, never primary data.
Rationale: eliminates duplication and enables structured AI reasoning (docs 00, ADR-001/002/003).

### II. Human-in-the-Loop (NON-NEGOTIABLE)
AI MUST NOT modify user-owned professional or application data without explicit user approval.
AI agents produce structured Recommendations; only Domain Services apply user-approved changes.
Every recommendation MUST be reversible until submission. User rejection MUST prevent the change.
Rationale: users retain complete ownership of their professional identity (ADR-006, doc 03 §12.3).

### III. Explainable and Honest AI
Every AI recommendation MUST include an explanation and, where applicable, supporting evidence
and a structured diff. AI MUST NOT fabricate professional experience, skills, or qualifications
(AI-008). Unsupported professional claims MUST be rejected before reaching the user.
Rationale: trust requires transparency; a resume tool that invents facts harms its user.

### IV. Immutable History
A Submitted Resume is an immutable snapshot with a stable file checksum. Applications in
`Applied` or later status MUST reference a Submitted Resume. Status history is append-only.
Company Research snapshots are immutable after generation. Profile updates MUST NOT alter
existing Resume Versions or Submitted Resumes.
Rationale: application history must always reproduce exactly what was sent (ADR-007).

### V. AI Is a Platform Capability, Not a Data Owner
Business Domains (Professional, Application, Knowledge) own all business data and stay
deterministic — they MUST NOT call AI providers. All AI execution flows through the Agent
Runtime and AI Gateway (LiteLLM); business code MUST remain provider-agnostic. Every
WorkflowExecution MUST preserve its inputs, model configuration, token usage, and cost, and
every Tool Call MUST be auditable.
Rationale: clean separation keeps the system testable and providers replaceable (ADR-004/005, doc 04).

### VI. Structured Data First
Professional information is stored as structured entities, validated with Pydantic schemas.
Structured operational facts MUST be retrieved relationally; semantic knowledge via vector
retrieval (pgvector) with citation metadata preserved; current external facts via web search.
LLM outputs MUST be validated against structured-output schemas before use.
Rationale: structure enables search, versioning, analytics, and reliable AI workflows (ADR-008/009).

### VII. Test-First Quality
Backend code targets 80%+ coverage with Pytest; domain invariants (immutability, approval
gates, ownership isolation) MUST have explicit tests. Ruff (format+lint) and mypy MUST pass
in CI before merge. Frontend critical flows get Playwright coverage.
Rationale: a platform holding career data must not regress silently (doc 06 §12).

## Technology Constraints

- Backend: Python + FastAPI + SQLAlchemy + Alembic + Pydantic (clean architecture:
  api / application / domain / infrastructure layers).
- Frontend: Next.js + TypeScript + Tailwind CSS + shadcn/ui.
- Data: PostgreSQL (with pgvector), Redis (never a source of truth), S3-compatible object
  storage (MinIO in dev).
- AI: LangGraph agent runtime, LiteLLM gateway; primary provider Anthropic Claude, providers
  swappable via configuration. Embeddings behind a configurable interface (local
  sentence-transformers by default; hosted providers optional).
- Background jobs: Celery. Auth: Google OAuth. Dev environment: Docker Compose — every
  service MUST run containerized.
- Migration source: JobTracker (github.com/nirtituani/job-tracker-web). The legacy `rejected`
  boolean MUST be converted to normalized status, never imported as-is.

## Development Workflow

- Spec-Driven Development: every feature follows specify → plan → tasks → implement using
  Spec Kit; artifacts live under `.specify/` and are version-controlled.
- Vertical slices: each feature ships demo-able end-to-end (API + UI + tests) against the
  running Docker Compose stack before it is called done.
- Design docs in `docs/` are the architectural source; conflicts between code and docs MUST
  be resolved by updating one to match the other, explicitly.
- CI (GitHub Actions): build, ruff, mypy, pytest, frontend build — all green before merge.

## Governance

This constitution supersedes ad-hoc practices. Amendments require: a documented rationale,
a semantic version bump (MAJOR: principle removal/redefinition; MINOR: new principle or
material expansion; PATCH: clarification), and an update to dependent SDD artifacts.
All PRs and reviews MUST verify compliance with Principles I–VII; violations of Principles
II–IV are release blockers. Complexity beyond the documented stack MUST be justified in an ADR.

**Version**: 1.0.0 | **Ratified**: 2026-08-05 | **Last Amended**: 2026-08-05
