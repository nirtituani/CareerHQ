# CareerHQ

> **Implementation Plan**

**Version:** 2.0
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
| What is CareerHQ, and what does each part do? | [07_Capabilities.md](07_Capabilities.md) — start here |
| What did the original source material actually say? | [`reference/`](reference/) — course requirements, the author's design notes, the resume-builder reference |
| What must always be true of CareerHQ? | [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) |
| What are we building, in what order? | This document |
| What exactly does slice N do? | `specs/00N-<name>/spec.md` |
| How is slice N built? | `specs/00N-<name>/plan.md` |
| What are the concrete steps? | `specs/00N-<name>/tasks.md` |

The design documents in this folder (00–04, 06) describe the *target* system. This document
describes the *path* to it.

---

# 2. Constraints

Version 2.0 of this plan is written against real constraints that Version 1.0 ignored.

- **One developer.** Every role — specification, engineering, evaluation, product — is the same
  person. Slices must be sequential and individually finishable.
- **Four to six weeks.** The original six-slice roadmap was a multi-month plan. It has been
  re-cut, not merely re-ordered.
- **An agent must exist early.** The previous ordering built three deterministic slices before any
  agent appeared. Under a fixed deadline that risks arriving with an impeccable CRUD application
  and no agent — failing the central goal while having done more work.

The response to those constraints is not to lower quality. It is to **build fewer things and
finish them**, guided by a principle taken from the original design notes:

> Better two deep agents and a working system than five shallow ones.

---

# 3. Method

Every slice follows the same loop:

```text
specify  →  plan  →  tasks  →  analyze  →  implement  →  verify
```

Each step produces a reviewable artifact and pauses for approval before the next begins. The
`analyze` step is a cross-artifact consistency check that runs before any code is written — it
catches requirements with no task coverage, drift between documents, and conflicts with the
constitution while they are still cheap to fix.

---

# 4. Slicing Principle

**Vertical slices, not horizontal layers.**

Each slice ships something demonstrable end to end — API, user interface, and tests — rather than
completing one architectural layer across the whole product. A slice is not finished when its code
is written; it is finished when it can be demonstrated against a deployed environment.

---

# 5. Roadmap

| # | Slice | Delivers | Depends on | Status |
|---|---|---|---|---|
| 001 | Platform Foundation | Containerized environment, Google sign-in, authenticated shell, CI | — | **Complete** |
| 002 | Deployment | Public URL, deployed from Docker, redeployed on every merge | 001 | **Live** |
| 003 | Data Foundation | Resume import and parsing, Professional Profile, applications, JobTracker import | 001 | **Next** |
| 004 | **Resume Tailoring Agent** | LangGraph workflow, RAG, self-critique Reviewer, item-level approval, versions, PDF | 003 | Planned |
| 005 | Evaluation & Benchmark | Test set, metrics, LLM-as-judge, results dashboard | 004 | Planned |
| 006 | Company Research | Research agent over a web search MCP, citation-preserving snapshots | 003 | Planned |
| 007 | Career Advisor | Quantified recurring skill gaps and learning priorities over history | 003, 004 | Planned |

Slices 001–005 are the **core**: together they satisfy every project requirement. Slices 006 and
007 add the most product value per unit of effort and should follow immediately, but the project
is defensible without them.

---

## 5.1 Slice 001 — Platform Foundation

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

## 5.2 Slice 002 — Deployment

**Delivers**: A public URL running the same containers as local development, redeployed
automatically on every merge to the main branch.

**Why this early**: Deployment is a graded requirement and a classic end-of-project disaster —
OAuth redirect URIs, environment variables, managed database provisioning, and HTTPS all fail in
unfamiliar ways the first time. Doing it against a nearly-empty application means debugging
deployment alone rather than deployment tangled with a half-finished agent. Every later slice then
ships continuously.

Scope is deliberately small: a managed Postgres with pgvector, the backend and frontend services,
secrets configured, and the Google OAuth client updated for the deployed domain.

---

## 5.3 Slice 003 — Data Foundation

**Delivers**: The user uploads their existing CV; it is parsed into structured Professional Profile
content; the user reviews and corrects it; an initial Master Resume is created. Alongside it, a
minimal Application entity holds jobs and their descriptions, seeded by importing real data from
[JobTracker](https://github.com/nirtituani/job-tracker-web).

**Why third**: The tailoring agent needs a structured profile to tailor and a job description to
tailor against. This slice produces both, and nothing in it requires an agent loop.

It is **not**, however, purely deterministic — an earlier version of this line said it was.
Slice 003's spec (D1) resolved CV extraction to a single structured-output LLM call behind an AI
Gateway seam, because deterministic parsing of a PDF would have forced the extraction-quality
target down rather than met it, and would likely have been rebuilt in 004 regardless. One typed,
schema-validated call is not an agent loop: no planning, no tool use, no self-critique, no
iteration. The seam it introduces is the one slice 004 extends rather than invents.

**Why import rather than a builder**: A guided from-scratch resume builder is roughly forty
settings and several weeks of interface work that demonstrates none of the project requirements.
Importing reaches the same structured data in a fraction of the time. The builder is documented as
future work in [01_Functional_Product_Requirements.md](01_Functional_Product_Requirements.md) §12,
and because the data model is identical it will be a pure interface addition (ADR-013).

**Why the JobTracker import matters**: It puts roughly twenty real applications in the database on
day one. That makes the tailoring demo realistic and, more importantly, gives the Career Advisor
genuine history to analyze rather than waiting for data to accumulate.

**Migration note**: JobTracker's `rejected` boolean must not survive as an independent source of
truth. Rejection is derived from the normalized status, per
[03_Domain_Model.md](03_Domain_Model.md) §14.

---

## 5.4 Slice 004 — Resume Tailoring Agent

**The flagship.** Everything before it exists to make this possible; everything after builds on it.

**Delivers** a LangGraph workflow implementing the loop:

```text
Analyze Job Description
  → Retrieve resume guidelines (RAG over pgvector)
  → Draft tailored content
  → Reviewer: self-critique, grounding check, confidence score
  → Revise if below threshold
  → Present diff for item-level human approval
  → Frozen Resume Version with recorded lineage
  → PDF export → Submitted and locked
```

The **Reviewer** is not optional decoration. It verifies that every claim is grounded in existing
profile content, detects overstated phrasing, checks coverage against the job requirements, and
returns a confidence score that can send the draft back for revision. It is what makes the system
trustworthy rather than merely generative, and it is the component the original design notes
identified as most important.

**Also introduces** the Knowledge Context: document ingestion, chunking, embeddings, and pgvector
retrieval with citations preserved.

**The constraint that matters**: structured facts are retrieved relationally; only semantic
knowledge goes through vector search ([03_Domain_Model.md](03_Domain_Model.md) §7.5). Embedding
structured profile data and asking a model to retrieve it produces approximate answers to
questions the database answers exactly.

**Version model**: lineage is recorded, never inherited (ADR-012). A submitted resume is locked
permanently, which is what allows the Career Advisor to later analyze which versions led to
interviews.

**Presentation scope**: one well-designed, ATS-safe template. The `ResumeLayout` value object
carries the fields a designer surface would need, so that remains an interface addition rather
than a schema change.

---

## 5.5 Slice 005 — Evaluation & Benchmark

**Delivers** a real evaluation harness, not a spreadsheet of impressions:

- A fixed benchmark set of job descriptions paired with profile states
- **Grounding accuracy** — the proportion of generated claims traceable to existing profile content
- **Requirement coverage** — how much of a job description's must-have list the tailored resume addresses
- **Match Score calibration** — do higher scores correspond to better human-rated resumes?
- **Retrieval quality** — are the guidelines the RAG step returns actually relevant?
- **LLM-as-judge** scoring of tailored output against a rubric, with a human-rated sample to check the judge
- **Regression runs** — the same benchmark re-run after prompt or model changes, so improvement is measured rather than assumed
- A results view showing metrics over time

**Why it is a slice and not a task**: evaluation was deferred in the previous version of this plan,
which was a mistake on two counts. It is an explicit project requirement, and it is the difference
between "I built an agent" and "I know how well my agent works" — which is the more interesting
claim.

**Why here**: there is nothing to evaluate before slice 004 produces output, and everything built
afterwards can be measured against a harness that already exists.

---

## 5.6 Slice 006 — Company Research

**Delivers** on-demand company research — what the company does, its product and customers, its
market and competitors, publicly visible technologies, and interview-preparation notes — summarized
into immutable snapshots that preserve their sources and retrieval timestamps.

**Implemented over a web search MCP** rather than a hand-rolled search client. This satisfies the
Tools/MCP project requirement and is the better design regardless: the tool boundary stays clean
and the provider is replaceable.

---

## 5.7 Slice 007 — Career Advisor

**Delivers** quantified analysis across accumulated application history:

- Skill frequency across job descriptions applied to — *"Python appeared in 14 of 20 roles,
  Kubernetes in 9, Java in 4"*
- Separation of critical gaps from nice-to-have
- Role families where match scores run consistently higher
- A prioritized learning roadmap ordered by frequency and impact
- Whether identified gaps are narrowing over time

**Why last**: it is the one capability worthless without history. It needs applications, match
analyses, and submitted versions to have accumulated — which the JobTracker import in slice 003
provides immediately rather than after months of use.

**Why it matters most for the project**: it is the clearest demonstration that the system reasons
over accumulated memory instead of answering a single prompt.

---

# 6. Project Requirements Coverage

Where each stated project requirement is satisfied.

| Requirement | Satisfied by |
|---|---|
| Project idea with specifications | `docs/00`–`docs/06` plus `specs/` artifacts |
| Plan with milestones | This document |
| Agent with backend and frontend | Slice 004 (FastAPI + Next.js) |
| Agent manages memory | Professional Profile, application history, submitted versions, and interview feedback persisted across sessions; slice 007 reasons over all of it |
| Tools / MCPs | Knowledge retrieval, resume diff, and PDF export tools in slice 004; web search **MCP** in slice 006 |
| Agentic workflow matched to the problem | Multi-agent with RAG and self-critique, plus human-in-the-loop approval (ADR-004, ADR-008) |
| Evaluation, benchmark, metrics | Slice 005 |
| Team roles | Solo project; all roles held by one person. Spec-Driven Development keeps the specification, evaluation, and engineering responsibilities separated as artifacts even when the person is the same. |
| Deployed using Docker | Slice 002, then continuously |

---

# 7. Deferred

Kept in the architecture, not built in this version.

| Capability | Why deferred |
|---|---|
| Resume Builder from scratch, and the Designer surface | Roughly forty presentation settings and a guided editor, demonstrating none of the project requirements. Import reaches the same structured data far faster, and the data model is identical so the builder is a later interface addition (ADR-013). |
| Application Workflow Agent | Proactive follow-up prompts, stale-application detection, deadline awareness. Genuinely agentic and cheap on top of the lineage model — the first stretch goal if slices 001–005 land early. |
| Interview Preparation Agent | Reuses Company Research output; second stretch goal. |
| Multi-provider routing | LiteLLM makes providers swappable by configuration. Building routing before a second provider is needed is speculative complexity. |
| Cover letters, LinkedIn, calendar, email integration | Out of scope for Version 1 per [01_Functional_Product_Requirements.md](01_Functional_Product_Requirements.md) §11. |

---

# 8. Corrections to the Original Design

Recorded so the design documents and the implementation do not silently diverge.

| # | Original | Correction | Reason |
|---|---|---|---|
| 1 | OpenAI embeddings ([06](06_Technology_Stack.md) §7) | Configurable embeddings interface, local sentence-transformers by default | The primary provider is Anthropic, which has no embeddings endpoint. A local default keeps the stack runnable with no API key. |
| 2 | Single `0001_foundation` migration | `0001_extensions` and `0002_users_profiles` | Keeps the environment slice shippable independently of the identity slice. |
| 3 | JobTracker `rejected` boolean | Derived from normalized status | Two sources of truth for one fact drift apart. Already required by [03](03_Domain_Model.md) §14; restated because import code is where it would be violated. |
| 4 | Evaluation framework deferred out of the MVP | Promoted to slice 005 | It is an explicit project requirement, and the original design notes identified the Reviewer layer as the most important missing component. Deferring it was the most serious error in version 1.0 of this plan. |
| 5 | Agents scheduled after three deterministic slices | Agent-first ordering | Under a fixed deadline the previous order risked shipping no agent at all. |
| 6 | Resume version inheritance left unspecified | Template lineage with immutable snapshots (**ADR-012**) | Live inheritance would silently alter already-submitted resumes and make historical analysis impossible. |
| 7 | Imported CV as a document | Parsed into structured content (**ADR-013**) | Match scoring, gap analysis, and item-level approval all require structure. |

---

# 9. Definition of Done

A slice is complete when **all** of the following hold:

- Every functional requirement in its specification has passing test coverage
- Backend test coverage is at or above 80%; Ruff and mypy pass
- The quickstart runs clean from a fresh clone
- The slice works on the **deployed** environment, not only locally
- The capability can be demonstrated end to end to a person, not just to a test runner
- Design documents and code agree — where they disagree, one was updated deliberately

---

# 10. Current Status

**Last completed slice**: 001 — Platform Foundation

All 69 tasks done and all three user stories verified, including a real Google sign-in taking the
database from `0|0` to `1|1` and a second sign-in leaving it at `1|1` while advancing only
`last_login_at`. Merged to `main`; CI green on the merge commit. 55 backend tests at 89% coverage,
3 component tests, 6 Playwright smoke tests.

**Active slice**: 002 — Deployment
**Stage**: Live, finishing — 37 of 52 tasks. User Stories 1 and 2 verified against the running
system; User Story 3 (continuous deployment) and documentation remain.

**Deployed at https://frontend-production-02ac.up.railway.app** — public HTTPS, real Google
sign-in working end to end, readiness reporting deployed dependencies truthfully.

The production security path is no longer unproven. HSTS, `Secure` and `https_only` have now run
with `ENVIRONMENT=production` and were confirmed by observing real responses and the real session
cookie, not by reading the code. The evidence is in
[`specs/002-deployment/observations.md`](../specs/002-deployment/observations.md).

That distinction earned its keep. Three of this slice's failures were invisible to the source: a
hardcoded listening port that was correct locally by coincidence; a production container stage
nobody had ever built; and a proxy destination baked in at build time, so a runtime variable
arrived too late. A fourth was subtler still — the security headers were correct and complete on
`/api/*` while absent from every page a browser actually navigates to, because the middleware that
sets them never sees those responses.

This is the argument for deploying before the agent, made concrete: each of those would otherwise
have surfaced later, tangled with a half-finished agent, instead of against an application small
enough to debug in isolation.

Progress for each slice is tracked in its own `specs/00N-<slice>/tasks.md`. This section is updated
as slices complete.
