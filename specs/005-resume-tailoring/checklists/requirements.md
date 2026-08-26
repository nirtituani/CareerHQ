# Specification Quality Checklist: Resume Tailoring

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-22
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

### Fixed during validation

Three items failed on the first pass and were corrected in `spec.md`:

1. **Implementation detail leaked into "Deliberately not here"** — the RAG boundary named
   `pgvector` directly. Replaced with "semantic retrieval over a guideline library", which
   states the same boundary without naming the store.
2. **FR-047 was written in persistence vocabulary** — "through a session other than the one that
   created the record" describes the mechanism rather than the requirement. Rewritten as "against
   a record re-read from storage, not one still held in memory from its own creation", which is
   the actual property and is testable without knowing the ORM.
3. **SC-001 was not achievable as written.** A single 90-second target ignored that the workflow
   has a bounded revision loop: the worst case is seven model calls, three of them on the slower
   reviewing model. Split into a first-pass target and a full-revision-budget ceiling, so the
   criterion is honest about the distribution rather than describing only the happy path.

### Deliberate deviations from "no implementation details"

Four requirements name mechanisms, and this is house style rather than leakage — slice 004's
spec does the same (its FR-027 and FR-020). They are governance requirements whose entire content
*is* the mechanism, and stating them abstractly would make them untestable:

- **FR-036** (model configured explicitly per step, defaults treated as a defect) — the failure it
  prevents is a silent 2.5× cost increase, which has already happened once in this project.
- **FR-037** (outputs validated against a declared schema) — Constitution Principle VI.
- **FR-038** (no step reaches a provider except through the established seam, enforced
  automatically) — Constitution Principle V, and the reason it is enforceable at all.
- **FR-045** (no test makes a live provider call).

### Carried risks, recorded rather than resolved

- **SC-006's $0.30 ceiling is a target, not a measurement.** The design records that this
  project's last token estimate was wrong by nearly 2× in the direction of underestimating, so
  this number must be measured on a real run and the spec amended if it is wrong.
- **The confidence threshold has no calibrated value.** It is an uncalibrated constant, versioned
  so it can be changed honestly once slice 007 can measure it. Listed in Out of Scope.

### Status

All items pass. Ready for `/speckit-plan`.
