# CareerHQ

> **Capabilities**

**Version:** 1.0
**Status:** Active
**Author:** Nir Tituani
**Last Updated:** August 2026

---

# 1. Purpose

One page answering: **what is CareerHQ, and what does each part of it do?**

The other design documents each answer a narrower question — `00` the vision, `01` the
requirements, `03` the domain, `04` the architecture, `05` the build order. This one is the map
you read first, and the one to present.

---

# 2. The System in One Sentence

CareerHQ is a stable, deterministic **Application Management Core** that owns all business data,
with a set of **specialized agents** on top of it that reason over that data and propose actions —
none of which may change anything without the user's explicit approval.

```text
                    Application Management Core
                    (deterministic — owns the data)
                                 │
        ┌────────────┬───────────┼───────────┬────────────┐
        │            │           │           │            │
   Resume       Company      Career     Interview    Application
  Optimizer     Research     Advisor      Coach       Workflow
        │            │           │           │            │
        └────────────┴───────────┴───────────┴────────────┘
                                 │
                     Reviewer / Evaluation Layer
                    (grounding, integrity, confidence)
```

Not every part of the product is an agent, and that is deliberate. Tracking applications is CRUD
and should stay CRUD. Agents are reserved for work that genuinely requires reasoning.

---

# 2a. Status at a glance

**Verified against `main`.** A capability is *implemented* only if it is reachable in the running
system; design documents do not count.

| Capability | Status | Where |
|---|---|---|
| Application Management Core | ✅ **Implemented** | 003 — deterministic CRUD, no model calls |
| CV import → reviewed Professional Profile | ✅ **Implemented** | 003 |
| JobTracker history import | ✅ **Implemented** | 003 — run against production |
| Match Analysis | ✅ **Implemented** | 004 |
| Resume Optimizer (tailoring workflow) | ✅ **Implemented** | 005 |
| Reviewer / self-critique | ✅ **Implemented** | 005 — the in-workflow loop |
| RAG over resume guidelines | ✅ **Implemented** | 006 |
| PDF export, submit-and-lock | ✅ **Implemented** | 006 |
| Evaluation harness, metrics, LLM-as-judge | ✅ **Implemented** | 007 — paid benchmark pass run |
| Company Research — company-scoped (008) | ✅ **Implemented** | 008 — retained as the configured fallback under 010 |
| Company Research — role-aware (010) | 🔨 **Built, not deployed** | 010 — the active architecture: application-scoped research behind a `ResearchProvider` port, driven by the job description |
| Company Research — 008's Layer 2 (role) | 🚫 **Superseded by 010** | Its use case and schema survive as dead code; its `role_research_snapshots` table was reshaped by migration `0020` into the application-scoped store 010 uses |
| Career Advisor | 🔨 **Built** — on branch `009-career-advisor`, unmerged | 009 |
| Interview Coach | 💤 **Deferred** — stretch goal | — |
| Application Workflow Agent | 💤 **Deferred** — stretch goal | — |
| Resume Builder / Designer | 🚫 **Non-goal** — scoped out (ADR-013) | — |

**"Agent" is used narrowly here.** A capability is an agent when it plans, acts and revises over
multiple steps — which, today, means the Resume Optimizer. Match Analysis and research synthesis
are single structured completions; calling them agents would inflate the architecture. Business
logic stays deterministic, and every provider call goes through the one AI boundary.

---

# 3. Capabilities

## 3.1 Application Management Core

**Not an agent.** Deterministic business logic that owns applications, companies, job
descriptions, statuses, and history.

| | |
|---|---|
| **Does** | Create and track job applications through their lifecycle, with append-only status history, notes, contacts, salary, and links |
| **Input** | User entries, plus a one-time import from JobTracker |
| **Output** | The application record every agent reads from |
| **Memory** | This *is* the long-term memory — the accumulated record everything else reasons over |
| **Evaluated by** | Deterministic tests. There is no model output to judge. |
| **Slice** | 003 |

Why it stays deterministic: business rules that must always hold — a submitted resume is immutable,
status history is append-only, every record belongs to exactly one user — are enforced by the
database and by code, never by a model. This is Constitution Principle V.

---

## 3.1a Match Analysis — *built, slice 004*

Answers **"is this worth applying to, and where am I weak?"** for one recorded job, read before
any resume work.

| | |
|---|---|
| **Does** | Score the whole posting against the approved Professional Profile, and say which requirements it supports, which it does not, and what to do about each |
| **Input** | The stored posting + the approved Professional Profile |
| **Output** | A 0–100 score with the four judgements it is made of, a band, and one row per requirement with a verdict and quoted evidence |
| **Not an agent** | One structured call. No loop, no tools, no self-critique, no retrieval — the entire profile fits in the prompt many times over |
| **Memory** | Reads the profile; writes only to its own tables |
| **Evaluated by** | Grounding (every verdict but one quotes the profile), and Match Score calibration over history via `criteria_version` |
| **Slice** | 004 ✅ |

**The rule it must never break:** it may not assert experience the profile does not contain — and
**may not assert its absence either**. A profile silent about a requirement supports neither claim,
which is why `unverified` exists beside `gap` and is the only verdict carrying no evidence.

**Not the same measurement as the Optimizer's Match Score below.** This one asks *how well does my
profile fit this job*, read before applying. That one asks *how well does this tailored resume
match*, read after drafting. They share a schema so the two numbers stay comparable, and a later
slice can show "54 before tailoring → 71 after".

---

## 3.2 Resume Optimizer Agent — *the flagship*

Takes a job description and adapts the CV to it.

| | |
|---|---|
| **Does** | Analyze a job description, retrieve resume-writing guidelines, select and rewrite content from the Professional Profile, score the match, explain each proposed change, and present a diff for approval |
| **Input** | Job description + Professional Profile + selected Master Resume |
| **Output** | A tailored Resume Version, a Match Score, per-item recommendations with reasons |
| **Tools** | Knowledge retrieval (RAG over pgvector), resume diff, PDF export |
| **Memory** | Reads the Professional Profile; writes nothing without approval |
| **Workflow** | `Analyze → Retrieve → Draft → Self-Critique → Revise → Human Approval` |
| **Evaluated by** | Grounding accuracy, requirement coverage, Match Score calibration, LLM-as-judge against a rubric |
| **Slice** | 005 (workflow, Reviewer, versions, approval), 006 (RAG, PDF) |

**The rule it must never break:** it may reorder, re-emphasize, and rewrite existing facts. It may
never invent experience, skills, or qualifications the profile does not contain (AI-008).

---

## 3.3 Reviewer / Evaluation Layer

Runs behind the scenes, not as a user-facing agent. It is what makes the system trustworthy rather
than merely generative.

| | |
|---|---|
| **Does** | Verify every claim is grounded in existing profile content, detect overstated phrasing, check coverage against the job requirements, check consistency between resume, job description, and profile, and return a Confidence Score |
| **Input** | The Optimizer's draft, the source profile, the job description |
| **Output** | Confidence Score, a list of findings, and a revision request when the score is below threshold |
| **Workflow** | Self-critique loop — it can send work back to the Optimizer without asking the user |
| **Evaluated by** | Agreement with human judgement on a labelled sample; does the judge catch what a person would? |
| **Slice** | 005 (the loop), 007 (the metrics) |

This is the component that demonstrates self-critique, guardrails, quality control, and
evaluation — four things production agentic systems are judged on.

---

## 3.4 Company Research Agent

| | |
|---|---|
| **Does** | Research a company on demand: what it does, its product and customers, market and competitors, publicly visible technology, and interview preparation notes |
| **Input** | Company name and domain |
| **Output** | An immutable research snapshot **with sources and retrieval timestamps** |
| **Tools** | **Web search** behind the `WebSearch` port — plain HTTPS to Tavily, not MCP. The provider returns URLs only; CareerHQ fetches the pages itself, which is what makes verbatim citation checking possible |
| **Memory** | Snapshots accumulate per company; historical research is never overwritten |
| **Evaluated by** | Citation accuracy — does each claim trace to a real source? |
| **Slice** | 008 |

Snapshots are immutable and timestamped because company facts go stale. Research from three months
ago is still useful, but it must be visibly three months old rather than silently wrong.

---

## 3.5 Career Advisor Agent

The clearest demonstration that the system reasons over accumulated memory rather than answering a
single prompt.

| | |
|---|---|
| **Does** | Analyze every job description applied to, count how often each skill is required, separate critical gaps from nice-to-have, identify role families where match scores run higher, and produce a prioritized learning roadmap |
| **Input** | Full application history, match analyses, interview feedback |
| **Output** | Quantified gaps and a learning roadmap — *"Python appeared in 14 of 20 roles, Kubernetes in 9, Java in 4"* |
| **Memory** | Reads everything the platform has accumulated; this capability is meaningless without it |
| **Evaluated by** | Do identified gaps match the job descriptions on inspection? Do they narrow over time? |
| **Slice** | 009 |

The output is **quantitative on purpose**. "You should learn Kubernetes" is an opinion; "Kubernetes
appeared in 9 of your last 20 applications and in 6 you were rejected after the technical round" is
evidence.

**As built (slice 009)**: the advisor maintains **career memories** — falsifiable claims with
frozen evidence, denominators and lineage — which later runs retrieve, reason over and
explicitly confirm, supersede or retire; every number is computed deterministically and a claim
the gate cannot verify is discarded before persistence. Two corrections to the table above,
recorded rather than silently applied: **interview feedback is not an input** (the entity was
never implemented), and the **prioritized learning roadmap is delivered as lightweight
prioritization** — actionable memories carry an agent-assigned priority with its stated reason
and the surface orders by it; a distinct roadmap artifact is **explicitly deferred** until
enough analysed postings exist to rank by frequency and impact honestly (spec 009,
clarification Q1).

---

## 3.6 Interview Coach — *stretch*

| | |
|---|---|
| **Does** | Identify likely interview topics for a specific role, generate expected questions, map job requirements to your actual experience, suggest which stories to prepare, and build a prep plan sized to the time remaining |
| **Input** | Job description, profile, and the Company Research snapshot |
| **Output** | A company-specific briefing and checklist |
| **Slice** | Deferred — built only if the core lands early |

Cheap to build because it composes work already done: the research agent's output plus the profile.

---

## 3.7 Application Workflow Agent — *stretch*

The only proactive capability. Everything else is request-response.

| | |
|---|---|
| **Does** | Notice an application sitting without a reply, suggest a follow-up, flag an approaching deadline, recommend the next action, detect missing information, and trigger another agent based on application state |
| **Input** | Application state and elapsed time |
| **Output** | Suggestions — never automatic changes |
| **Slice** | Deferred — first stretch goal |

Also the natural home for *"FastAPI was added to your AI Backend Master. Use the updated version for
the next application?"* — informing without modifying anything already submitted (ADR-012).

---

## 3.8 Resume Builder — *future*

Building a CV from scratch through a guided editor, with a live preview, per-item inclusion
toggles, and presentation controls — the Teal experience.

Version 1 populates the profile by **importing an existing CV** instead. The parsed data model is
identical, so this becomes a pure interface addition rather than a rebuild (ADR-013).

---

# 4. What Each Capability Demonstrates

Mapping capabilities to the project requirements.

| Requirement | Demonstrated by |
|---|---|
| Multi-agent | Optimizer, Research, Advisor, and Reviewer coordinated by the workflow engine |
| RAG | Guideline retrieval over pgvector in the Optimizer (slice 006) |
| Tools / MCP | Knowledge retrieval (RAG), PDF export; **web search** in Research — behind a port, over plain HTTPS rather than MCP |
| Memory | The Core is the memory; the Advisor is what proves it is being used |
| Self-critique | The Reviewer's revision loop |
| Human-in-the-loop | Item-level approval before any resume version is created |
| Evaluation and metrics | Slice 007, measuring the Optimizer and Reviewer |
| Backend + frontend | FastAPI + Next.js throughout |
| Deployed with Docker | Slice 002, then continuously |

---

# 5. The End-to-End Flow

What a user actually does, and which capability handles each step.

```text
Import CV                    → parsed into the Professional Profile
   ↓
Add a job                    → Application Management Core
   ↓
Research the company         → Company Research (web search, plain HTTPS)
   ↓
Analyze and score the match  → Resume Optimizer
   ↓
Tailor the resume            → Resume Optimizer
   ↓
Review and validate          → Reviewer / Evaluation Layer
   ↓
Approve, item by item        → the user
   ↓
Export PDF, mark submitted   → frozen, locked, immutable
   ↓
Prepare for the interview    → Interview Coach (stretch)
   ↓
Track the outcome            → Application Management Core
   ↓
Learn from the pattern       → Career Advisor
```

The loop closes at the bottom: every application makes the Career Advisor's analysis sharper, which
is the product premise — *knowledge accumulates instead of being lost after submission*.

---

# 6. Build Priority

Two deep agents and a working system beat five shallow ones.

| Priority | Capability | Why |
|---|---|---|
| 1 | Application Core + Resume Optimizer + Reviewer | The flagship. Everything else builds on it. |
| 2 | Evaluation | Turns "I built an agent" into "I know how well it works" |
| 3 | Company Research | Adds the external-tool requirement — web search behind a port |
| 4 | Career Advisor | Best demonstration of memory; cheap once history exists |
| 5 | Interview Coach, Application Workflow Agent | Stretch |
| 6 | Resume Builder | Future |

Full sequencing and reasoning: [05_Implementation_Plan.md](05_Implementation_Plan.md).
