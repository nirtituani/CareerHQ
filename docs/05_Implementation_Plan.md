# CareerHQ

> **Implementation Plan**

**Version:** 2.1
**Status:** Active
**Author:** Nir Tituani
**Last Updated:** September 2026

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
| 003 | Data Foundation | Resume import and parsing, Professional Profile, applications, JobTracker import | 001 | **Complete** — 109/109, import run against production |
| 004 | Match Analysis | Score a recorded job against the approved profile, with per-requirement evidence | 003 | **Complete**, verified in production |
| 005 | **Resume Tailoring** | LangGraph workflow, self-critique Reviewer, versions with lineage, item-level approval | 004 | **Complete** — 101/101, deployed, exercised by a real paid run |
| 006 | Document & Retrieval | RAG over resume guidelines, PDF export, submit-and-lock | 005 | **Complete** — 57/57, deployed |
| 007 | Evaluation & Benchmark | Benchmark set, metrics, LLM-as-judge, regression runs, results view | 006 | **Complete** — 50/50, paid benchmark pass run. **Graded** |
| 008 | Company Research | Search → fetch → synthesise over web search (plain HTTPS, not MCP), citation-preserving snapshots | 003 | **Complete** and merged; **primary path superseded by 010**, retained as its fallback. Its unwired Layer 2 table was reshaped by 010's migration `0020` |
| 009 | Career Advisor | Agent-managed career memory: evidence-backed claims created, confirmed, superseded, retired across runs; deterministic evidence pack, grounding gate, `/advisor` surface | 003, 004 | **Complete** — merged and deployed; Advisor V2 (evidence-grounded guidance, grounded technology signals) followed on `main` |
| 010 | Role-Aware Research | Application-scoped research via a ResearchProvider seam (Tavily Research first), sections-first UI | 008 | **Complete** — merged as PR #22 and deployed |

Slices 001–007 are the **core**: together they satisfy every project requirement. Slices 008 and
009 added the most product value per unit of effort and followed immediately, but the project
was defensible without them.

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

> **Status: complete — 109/109, all three user stories.** A CV becomes a reviewed profile, and a
> job becomes a record carrying the description slice 004 tailors against — both verified on the
> deployed system. The JobTracker import, blocked for a time on a CSV export only the author could
> produce, was **run against production**: 96 rows imported, rejection arriving as a status value
> rather than a column, and the pre-existing records preserved rather than duplicated.
>
> Two things this slice added that the plan below does not describe, both requested during
> implementation and recorded in `specs/003-data-foundation/tasks.md` Phase 4b: **reading a job
> posting from its URL** (a second `complete()` call site, decided rather than drifted into — see
> T096) and the **match-analysis design** in
> [`docs/superpowers/specs/2026-08-17-match-analysis-design.md`](superpowers/specs/2026-08-17-match-analysis-design.md),
> which is slice 004 work started early because both of its inputs now exist.

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
day one, giving the Career Advisor genuine history — statuses, dates and outcomes — rather than
waiting for data to accumulate.

It does **not** make the tailoring demo realistic, which an earlier version of this line claimed.
Reading the source (slice 003 research R8) established that JobTracker has no job description
field at all — only `job_link` and `job_desc_link`, both URLs. Imported applications therefore
carry nothing to tailor against, and the manual job-entry story is the only source of tailorable
input for slice 004.

**Migration note**: JobTracker's `rejected` boolean must not survive as an independent source of
truth. Rejection is derived from the normalized status, per
[03_Domain_Model.md](03_Domain_Model.md) §14.

The source system shows why this is not theoretical: its own dashboard counts rejections as
`rejected IS TRUE OR status='Rejected'`, reconciling two fields that encode one fact at every read
site. The import's rule loses nothing — a row flagged rejected while sitting at "Interview Round 2"
keeps that label and takes a normalized status of `rejected`, recording both how far the
application got and how it ended. That is more information than the source could express, obtained
by removing a field rather than adding one.

---

## 5.4 Slice 004 — Match Analysis, then the Resume Tailoring Agent

> **Split during implementation.** Match analysis — scoring a recorded job against the profile —
> was pulled out ahead of the tailoring agent and **built as slice 004**, because it is
> independently valuable, independently shippable, and needs none of the tailoring machinery: no
> workflow engine, no retrieval, no Reviewer, no version lineage. It answers *is this worth
> applying to, and where am I weak*, which is the question a person asks **before** any resume
> work, so building it first also puts the tailoring agent's inputs on screen.
>
> Specified in [`specs/004-match-analysis/`](../specs/004-match-analysis/). The tailoring agent
> described below is **slice 005** (§5.5), and its scope was cut there: the workflow, the Reviewer,
> versions and approval ship in 005; retrieval and PDF export in 006. **The numbering was shifted on
> 2026-08-22** — it had deliberately not been after the split, because renumbering to record one split cost more
> than the sentence you are reading.

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

## 5.5 Slice 005 — Resume Tailoring

> **Designed 2026-08-22**:
> [`docs/superpowers/specs/2026-08-22-resume-tailoring-design.md`](superpowers/specs/2026-08-22-resume-tailoring-design.md),
> which is the authoritative description. This section says only what the roadmap needs.

**The flagship, scoped to what one slice can carry.** A recorded job becomes a tailored
resume: the agent plans what to emphasise, drafts it, criticises its own draft, revises, and
presents a diff the user approves item by item. Nothing is kept without that approval.

The **Reviewer** is the point. It verifies every claim traces to existing profile content,
detects overstated phrasing, checks coverage, and returns a confidence score that sends work
back without asking the user. It is what makes the system trustworthy rather than merely
generative, and it is the loop `docs/07` §3.3 assigned to "004" before slice 004 was split.

**LangGraph orchestrates and owns nothing.** Persistence, business state, audit and
ownership stay in CareerHQ; every model call goes through the existing `complete()` seam.
The checkpointer is declined for now, because approval starts no further graph execution and
two persistent representations of one workflow leave no answer to which is authoritative.

**RAG and PDF export are deliberately not here** — see §5.6. §5.4's original scope was six
subsystems; slice 004 was one structured call and ran 89 tasks.

---

## 5.6 Slice 006 — Document & Retrieval

**Delivers the half of the Optimizer slice 005 left out**, and turns an approved version into
a document that can actually be sent:

- **Knowledge Context** — document ingestion, chunking, embeddings, and pgvector retrieval
  with citations preserved. This is the project's only RAG, and it retrieves **resume-writing
  guidelines**, which the Draft node consumes in place of slice 005's static rubric.
- **PDF export** against one well-designed ATS-safe template, the `Exported` and `Submitted`
  lifecycle states, and `SubmittedResume` — locked permanently, which is what lets slice 009
  later analyse which versions led to interviews.

**The constraint that matters**: structured facts are retrieved relationally; only semantic
knowledge goes through vector search ([03_Domain_Model.md](03_Domain_Model.md) §7.5).
Embedding structured profile data and asking a model to retrieve it produces approximate
answers to questions the database answers exactly (ADR-008).

**Why after 005**: swapping the Draft node's rubric from static code to retrieval changes one
node's input, not the design — so the workflow can be built, run and corrected first, against
a rubric that is fully under control.

---

## 5.7 Slice 007 — Evaluation & Benchmark

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

**Why here, and not earlier**: it was 005 in an earlier version of this plan, and moved twice.
Four of the seven metrics above measure the tailoring agent — requirement coverage of a tailored
resume, retrieval quality of the RAG step, LLM-as-judge of tailored output, and grounding accuracy
of generated claims. Building the harness before them means building a measuring instrument for
something that does not exist, then extending it anyway. Retrieval quality is one of the four,
which is what puts this behind 006 rather than between 005 and 006.

**The risk in that, stated rather than buried**: evaluation is a graded requirement and it has now
been deferred twice. If the budget runs short, 008 and 009 are what get dropped — they are
droppable by design (§5, and [08_Technical_Spec.md](08_Technical_Spec.md) §11). This is not.

---

## 5.8 Slice 008 — Company Research

**Delivers** on-demand company research — what the company does, its product and customers, its
market and competitors, publicly visible technologies, and interview-preparation notes — summarized
into immutable snapshots that preserve their sources and retrieval timestamps.

**Implemented over a web search tool behind a port**, rather than a hand-rolled client inlined
into the use case. *This was planned as an MCP stdio server and shipped as plain HTTPS to Tavily* —
the argument is in `infrastructure/research/tavily_search.py`: a single fixed host that no
untrusted input can influence is a smaller attack surface and one less moving part than a stdio
subprocess. **The tool boundary is what mattered and it is unchanged** — the provider sits behind
`WebSearch` in `application/ports.py` and is replaceable.

---

## 5.9 Slice 009 — Career Advisor

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
| Tools / MCPs | Knowledge retrieval (RAG) and PDF export in 006; **web search** in 008, behind the `WebSearch` port over plain HTTPS rather than MCP |
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
| Application Workflow Agent | Proactive follow-up prompts, stale-application detection, deadline awareness. Genuinely agentic and cheap on top of the lineage model — the first stretch goal if slices 001–007 land early. |
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

**All ten slices are complete, merged and deployed**; `main` is the authoritative branch and the
deployed system runs from it. Migration head is `0023`. The current suite: **1,506 backend tests
at 89.84% coverage** (gate 80%) and **313 frontend component tests** across 19 files, with CI
green on `main`.

One capability shipped outside the slice cycle, recorded as a deviation rather than a
recommendation: **theme-faithful export** — an imported CV's visual design extracted
deterministically at import, persisted by migrations `0022`–`0023`, and reproduced on export —
was specified, planned and implemented conversationally, so there is no `specs/011-*` for it.

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
