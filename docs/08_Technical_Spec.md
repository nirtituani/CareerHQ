# CareerHQ

> **Technical Specification**

**Version:** 1.0
**Status:** Active
**Author:** Nir Tituani
**Last Updated:** August 2026
**Reviewers:** —

---

# 1. Front Matter

## 1.1 What this document is

A single technical specification for CareerHQ, written to be read start to finish by
someone with no prior context. It follows the structure in
[*A practical guide to writing technical specs*](https://stackoverflow.blog/2020/04/06/a-practical-guide-to-writing-technical-specs/),
tailored to a solo project — sections that only apply to multi-team organisations are
omitted rather than left empty.

It is a **synthesis, not a replacement**. The design documents remain the source of
truth for their own areas; this document owns the narrative and links down for detail.

| Question | This doc | Full detail |
|---|---|---|
| Why does CareerHQ exist? | §2.1–2.2 | [docs/00](00_Product_Vision.md) |
| What does each capability do? | §3.2.1 | [docs/07](07_Capabilities.md) |
| What are the rules? | §2.4 | [constitution](../.specify/memory/constitution.md) |
| What is the data model? | §3.2.2 | [docs/03](03_Domain_Model.md) |
| How is it built? | §3.2.3 | [docs/04](04_System_Design.md) |
| Why these choices? | §3.7 | [docs/02](02_Architecture_Decision_Records.md) |
| What order? | §6 | [docs/05](05_Implementation_Plan.md) |

## 1.2 Status at a glance

**Slices 001–008 are complete and the system is deployed.** Slice 009 (Career Advisor) is
planned and droppable. Everything in this document carries an explicit status marker so that
planned work is never mistaken for shipped work.

| | |
|---|---|
| **Live at** | **https://frontend-production-02ac.up.railway.app** |
| **Built and verified** | Slices 001–008 — platform, deployment, data foundation, match analysis, resume tailoring, retrieval/export/submission, evaluation, company research. **527 / 527 tasks** across the eight slices |
| **Not built** | Slice 009 — Career Advisor (planned, droppable). Slice 008's **Layer 2** role research is built and tested but has **no route and no UI** |
| **Next** | Slice 009, or wiring Layer 2 — neither is scheduled |
| **Evidence** | **1,232 backend tests at 87.52% coverage** (gate 80%), **207 frontend component tests** across 14 files, 6 Playwright smoke tests, CI green on `main` |
| **Verified how** | Locally: full quickstart from a fresh clone on wiped volumes. **On the deployed system**: a real Google sign-in taking the database from `0\|0` to `1\|1`; a real CV imported and confirmed non-fixture; migration `0005` applied with constraints C2 and C3 present and no `rejected` column anywhere; a real job posting read end to end through the deployed extraction path — see [`specs/002-deployment/observations.md`](../specs/002-deployment/observations.md) |

---

# 2. Introduction

## 2.1 Overview and problem

The modern job search is fragmented across disconnected tools: resume builders, ATS
optimisers, application trackers, company research sites, interview prep. Each solves one
slice and stores a fraction of the candidate's professional information.

The cost is not merely inconvenience. **Knowledge is destroyed at every step.** A resume
tailored for one role teaches the system nothing about the next. A rejection after a
technical round produces no signal about which skill gap caused it. After twenty
applications a candidate has twenty disconnected documents and no accumulated
understanding of their own career.

CareerHQ is a career intelligence platform that keeps that knowledge. A deterministic
**Application Management Core** owns all business data; a set of **specialised agents**
reasons over it and proposes actions. No agent may change anything without the user's
explicit approval.

## 2.2 Context and background

CareerHQ succeeds [JobTracker](https://github.com/nirtituani/job-tracker-web), a working
but minimal application tracker built by the same author. JobTracker proved the tracking
workflow and accumulated roughly twenty real applications — data which seeds this system
on day one and gives the Career Advisor genuine history to analyse rather than waiting
months for it to accumulate.

It is built solo as a course project on a **four-to-six-week budget**. That constraint is
real and shapes every decision recorded here; it is the reason the roadmap has seven
slices of which five are the defensible core.

## 2.3 Glossary

| Term | Meaning |
|---|---|
| **Professional Profile** | The single source of truth holding all of a user's professional knowledge. Exactly one per user. |
| **Resume Profile** | A career-oriented presentation of a Professional Profile — references profile facts, never duplicates them. |
| **Resume Version** | A tailored resume generated for one specific job description. |
| **Submitted Resume** | An immutable snapshot of an exported Resume Version, with a stable file checksum. |
| **Application** | A tracked job application, linked to a Submitted Resume once status reaches `Applied`. |
| **Match Score** | A quantified fit between a job description and a tailored resume. |
| **Confidence Score** | The Reviewer's judgement of how well-grounded a draft is. Below threshold triggers revision. |
| **Grounding** | The property that every claim in generated output traces to existing profile content. |
| **Slice** | A vertical increment shipping API, UI, and tests together — not an architectural layer. |

## 2.4 Goals

The system is governed by **seven constitutional principles**. Violations of II–IV are
release blockers, not review comments.

| # | Principle | What it forbids |
|---|---|---|
| I | Professional Profile is the single source of truth | Duplicating profile facts into resumes |
| II | **Human-in-the-loop** *(non-negotiable)* | AI writing to user data without explicit approval |
| III | **Explainable and honest AI** | Recommendations without evidence; fabricated experience |
| IV | **Immutable history** | Editing a submitted resume or rewriting status history |
| V | AI is a platform capability, not a data owner | Business domains calling AI providers directly |
| VI | Structured data first | Storing professional information as unvalidated prose |
| VII | Test-first quality | Merging below 80% coverage, or with lint/type failures |

Product goals follow from these: import a CV once and never retype it; tailor a resume to
a job description with per-item approval; reproduce exactly what was sent for any past
application; and quantify recurring skill gaps across real history.

## 2.5 Non-goals

Explicitly out of scope for version 1, each with a stated reason
([docs/05](05_Implementation_Plan.md) §7):

| Not building | Why |
|---|---|
| From-scratch resume builder and presentation designer | ~40 presentation settings and weeks of interface work that demonstrate none of the project requirements. Import reaches identical structured data far faster (ADR-013). |
| Multi-provider LLM routing | LiteLLM makes providers swappable by configuration. Building routing before a second provider is needed is speculative complexity. |
| Full WYSIWYG resume editor | Item-level approval delivers the control users need without the editor surface. |
| Cover letters, LinkedIn, calendar, email integration | Out of scope per [docs/01](01_Functional_Product_Requirements.md) §11. |

Two things are **not optional despite being unbuilt**: the Reviewer/evaluation layer
(slice 005) and deployment (slice 002). Both are graded requirements.

## 2.6 Future goals

The Interview Coach and the Application Workflow Agent are the first stretch goals — both
cheap because they compose work already done. The Resume Builder is genuine future work,
and because ADR-013 makes the parsed data model identical to what a builder would produce,
it becomes a pure interface addition rather than a rebuild.

## 2.7 Assumptions

| # | Assumption | If wrong |
|---|---|---|
| A1 | The user has an existing CV to import | The profile starts empty; no builder exists to fill it (§2.5) |
| A2 | ~~Railway's managed Postgres supports `pgvector`~~ — **verified, no longer an assumption** | Closed. PostgreSQL 18.4 with `vector` 0.8.6, created successfully on the deployed database (§3.5) |
| A3 | `PUBLIC_BASE_URL` already drives every browser-facing URL | OAuth redirect becomes a code change rather than configuration |
| A4 | Job descriptions are pasted as text, not scraped | No scraping infrastructure is planned |
| A5 | A single user's data fits comfortably in one Postgres instance | Sharding was never designed (§3.2.5) |
| A6 | A local model on the development machine can serve the dev loop | Dev-loop LLM cost returns to roughly $50 — **untested, see §4.4** |
| A7 | A Sonnet-class model can revise well enough to clear an Opus Reviewer within two attempts | The escalation trigger in §3.2.3 fires on most runs and the mix costs closer to all-Opus — calibrated in slice 005 |

---

# 3. Solutions

## 3.1 Current solution

Today a candidate uses some combination of a word processor, a spreadsheet, an ATS
checker, and a browser. JobTracker replaced the spreadsheet with a real application, which
is why its data is worth importing.

| | Pros | Cons |
|---|---|---|
| **Word processor + spreadsheet** | Universal, free, no lock-in | Nothing is structured; every tailoring pass is manual retyping; no memory between applications |
| **JobTracker** | Real tracking, real data, already populated | Tracking only — no profile, no tailoring, no analysis. Its `rejected` boolean is a second source of truth for a fact the status already encodes |
| **Commercial tools (Teal, Rezi…)** | Polished, ATS-aware | Each owns a fragment of the data; none reason across accumulated history; the user's knowledge lives in someone else's silo |

**Migration note.** JobTracker's `rejected` boolean must not survive import as an
independent field — rejection is derived from normalised status
([docs/03](03_Domain_Model.md) §14). Two sources of truth for one fact drift apart.

## 3.2 Proposed solution

### 3.2.1 Capabilities and their status

Full descriptions in [docs/07](07_Capabilities.md) — not repeated here. What follows is the
map plus honest status.

```text
                    Application Management Core
                    (deterministic — owns the data)
                                 │
        ┌────────────┬───────────┼───────────┬────────────┐
   Resume       Company      Career     Interview    Application
  Optimizer     Research     Advisor      Coach       Workflow
        └────────────┴───────────┴───────────┴────────────┘
                                 │
                     Reviewer / Evaluation Layer
```

| Capability | Agent? | Slice | Status |
|---|---|---|---|
| Platform foundation — containers, auth, CI | No | 001 | ✅ **Built and verified** |
| Deployment — public HTTPS, continuous deploy | No | 002 | ✅ **Built and verified** |
| Application Management Core | No — deliberately CRUD | 003 | ✅ **Built** (JobTracker import outstanding) |
| Professional Profile + CV import | No | 003 | ✅ **Built and verified** |
| **Match analysis** — score a job against the profile | No — one structured call | 004 | ✅ **Built and verified** |
| **Resume Optimizer** — the flagship | Yes | 005 (workflow), 006 (RAG, PDF) | ✅ **Built and deployed** |
| **Reviewer / evaluation layer** | Yes | 005 (the loop), 007 (the metrics) | ✅ **Built** — self-critique in 005, metrics and LLM-as-judge in 007 |
| Company Research | Yes — web search over plain HTTPS (008); a research provider behind a seam (010) | 008, 010 | ✅ **Built** — 008's Layer 1 deployed; 010 makes research role-aware and keeps 008's pipeline as its fallback (merged as PR #22 and deployed) |
| Career Advisor | Yes | 009 | 📋 Planned |
| Interview Coach | Yes | — | 💤 Deferred (stretch) |
| Application Workflow Agent | Yes | — | 💤 Deferred (stretch) |
| Resume Builder | No | — | 🚫 Future (§2.5) |

**Not everything is an agent, and that is the point.** Tracking applications is CRUD and
stays CRUD. Agents are reserved for work that genuinely requires reasoning — which is what
makes Principle V enforceable: business domains never call an AI provider.

### 3.2.2 Data model

Four bounded contexts, each with its own aggregate root
([docs/03](03_Domain_Model.md) §9):

| Aggregate | Owns | Key invariant |
|---|---|---|
| **Professional** | Professional Profile, Resume Profiles, Resume Versions | Exactly one profile per user; resumes reference facts, never copy them |
| **Application** | Applications, status history, Submitted Resumes | Status history is append-only; `Applied`+ requires a Submitted Resume |
| **AI Workflow** | Workflow executions, tool calls, recommendations | Every execution preserves inputs, model config, tokens, and cost |
| **Knowledge** | Documents, chunks, embeddings, citations | Citation metadata survives retrieval |

**Business invariants belong in the schema.** A UNIQUE constraint cannot be raced or
forgotten; an application-level check can be both. This is already load-bearing: slice 001
enforces one-profile-per-user with a database constraint, and a test proves concurrent
first sign-in still yields exactly one profile.

**Ownership comes from the session, never the request.** No endpoint accepts a
client-supplied user or profile id. A test enumerates every route and asserts non-public
ones return 401 — ✅ verified in slice 001.

**Structured facts are retrieved relationally; only semantic knowledge goes through vector
search** ([docs/03](03_Domain_Model.md) §7.5). Embedding structured profile data and asking
a model to retrieve it produces approximate answers to questions the database answers
exactly.

### 3.2.3 Business logic — the agentic design

The Resume Optimizer is a LangGraph workflow (ADR-005), and the loop is the spec's most
important mechanism:

```text
Analyze job description
  → Retrieve resume guidelines        (RAG over pgvector, citations preserved)
  → Draft tailored content
  → Reviewer: grounding check, overstatement detection, confidence score
  → Revise if below threshold          ← self-critique loop, no user involvement
  → Present diff for item-level approval  ← the human gate (Principle II)
  → Frozen Resume Version with recorded lineage
  → PDF export → Submitted and locked  (Principle IV)
```

> **Retrieval is an input, not a step** (added 2026-08-22). The diagram above draws
> `Retrieve resume guidelines` between Analyze and Draft, but it is not a graph node. Slice
> 005 builds the workflow with guidance behind a `GuidelineSource` port backed by a static
> rubric; slice 006 re-implements that port over pgvector. The Plan and Draft nodes call the
> port, so adding RAG changes no vertex and no edge. Draft's query depends on what Plan
> decided, which is why the call sits inside the nodes rather than ahead of the graph. See
> `docs/superpowers/specs/2026-08-22-resume-tailoring-design.md` §3.4.

**Model selection is per node, matched to how much judgement each step needs.** LangGraph
nodes carry their own model configuration and LiteLLM makes the provider a setting
(ADR-005), so this is configuration rather than architecture.

| Node | Model | Why |
|---|---|---|
| Analyze job description | Sonnet | Extraction and classification — mechanical, well-specified |
| Draft | Sonnet | Rewriting existing facts against a retrieved rubric |
| **Reviewer** | **Opus** | The hardest judgement in the system, and the one whose failure is a release blocker |
| Revise | Sonnet, **escalating to Opus** | Usually mechanical; escalates when the cheaper model has already failed |

**The escalation trigger is the Reviewer's own verdict:** Revise runs on Sonnet for the
first attempt and escalates to Opus for the second, because a Sonnet revision that has
already failed to clear the threshold once is unlikely to clear it on a retry with the same
model.

That trigger exists to close a failure mode this mix creates. An Opus Reviewer reading a
Sonnet draft can identify problems a Sonnet reviser cannot fix, which would otherwise loop
— draft, reject, revise, reject — consuming attempts without converging. Escalating on the
second attempt bounds that loop with the more capable model rather than with a giving-up
condition.

**What the Reviewer actually does.** It verifies every claim traces to existing profile
content, detects overstated phrasing, checks coverage against the job's requirements, and
returns a confidence score that can send the draft back without asking the user. It is
what makes the system trustworthy rather than merely generative.

**The rule that must never break:** the Optimizer may reorder, re-emphasise, and rewrite
existing facts. It may never invent experience, skills, or qualifications the profile does
not contain (AI-008, Principle III).

**Version lineage is recorded, never inherited** (ADR-012). Live inheritance would silently
alter already-submitted resumes and make historical analysis impossible.

### 3.2.4 Presentation layer

**Built** — four surfaces exist and are Playwright-covered:

| Surface | File | Behaviour |
|---|---|---|
| Sign-in | [login/page.tsx](../frontend/src/app/login/page.tsx) | Google OAuth; declined consent explains itself and creates nothing |
| Dashboard | [dashboard/page.tsx](../frontend/src/app/dashboard/page.tsx) | Authenticated landing, currently an empty placeholder |
| App shell | [app-shell.tsx](../frontend/src/components/app-shell.tsx) | Navigation and user menu |
| Route guard | [middleware.ts](../frontend/src/middleware.ts) | Signed-out visitors are redirected to sign-in |

**Planned** — from [docs/01](01_Functional_Product_Requirements.md) §8: CV import with a
parsed-content review step, the application list and detail, and the item-level approval
diff.

**No wireframes or mockups exist.** The design is described in workflow prose only, which
is an accepted gap: one ATS-safe resume template is the entire presentation scope, and the
`ResumeLayout` value object already carries the fields a designer surface would need, so
that stays an interface addition rather than a schema change.

**The one genuinely novel interaction is the item-level approval diff.** It is where
Principle II is enforced in the interface rather than in code, and it is the screen a user
cannot skip. It deserves design attention that the rest of the UI does not.

### 3.2.5 Scalability, limitations, and failure recovery

**Honest limits.** This is a single-user-scale system. There is no horizontal scaling, no
read replica, no sharding, and no queue in the request path — Celery is in the stack but
unbuilt. None of this is a defect; it is correctly sized for the deadline in §2.2, and
Postgres on modest hardware serves this workload comfortably.

**LLM-specific failure modes** are the interesting ones, because they have no analogue in
the CRUD layer:

| Failure | Behaviour | Why it is safe |
|---|---|---|
| Model call times out mid-workflow | The execution is marked failed; no partial write occurs | Principle II — nothing is applied without approval, so a failed run is always discardable |
| Reviewer never converges below threshold | Bounded revision attempts, then surface the draft **with its findings** rather than silently accepting | The user sees the low confidence score, which is more useful than a hidden retry |
| Provider returns a refusal or is rate-limited | Surfaced as a failed execution with the cause recorded | The AI Workflow aggregate preserves inputs, so re-running costs nothing but tokens |
| Cost spike from a runaway loop | Every execution records token usage and cost (Principle V) | Makes the spike visible; §4.4 sets the budget it is measured against |

**Recovery is uniformly "discard and re-run."** Because agents write nothing without
approval, there is no partial-write state to repair — which is a direct dividend of
Principle II, not a separate design effort.

## 3.3 Test plan

| Layer | Tool | Gate | Current |
|---|---|---|---|
| Backend unit + integration | pytest | **≥80% coverage** | ✅ 285 tests, 81% |
| Backend format | `ruff format --check` | zero diffs | ✅ 86 files |
| Backend lint | `ruff check` | zero findings | ✅ passing |
| Backend types | `mypy` strict | zero errors | ✅ 49 files |
| Frontend components | Vitest | passing | ✅ 99 tests |
| Frontend lint | oxlint | zero findings | ✅ passing |
| Frontend types | `tsc --noEmit` | zero errors | ✅ passing |
| Frontend build | `next build` | exit 0 | ✅ passing |
| End-to-end | Playwright | passing | ✅ 6 tests |

**Tests come first.** Write the test, run it, confirm it fails for the right reason, then
implement. An `ImportError` because the module does not exist yet is a valid red; a test
that passes before implementation is a broken test.

**Domain invariants get explicit tests** (Principle VII): immutability, approval gates, and
ownership isolation each have named coverage rather than being implied by feature tests.

**Docker verification is a separate step from pytest**, and it has caught bugs the suite
could not — a dependency that existed only in a local venv, an empty `SESSION_SECRET` being
accepted, and an OAuth redirect pointing at an internal Docker hostname. Every user story
ends with a task that runs the real stack.

**A gate nobody has watched fail is not a gate.** When adding one, prove it catches
something: push a deliberate break, confirm the failure is named, then remove it.

**Agent evaluation is a different discipline entirely** and gets its own slice — §5.

## 3.4 Monitoring and alerting

The question observability must answer is *"what is broken, right now, and which request
did it?"* — answerable from the system's own output, without reproducing the problem.

| Mechanism | Status | Detail |
|---|---|---|
| Structured JSON logs, one object per line | ✅ Built | Uvicorn's handlers are removed and its records propagate to ours, so **every** line is parseable — a log that is structured only most of the time cannot be queried |
| Request-id correlation | ✅ Built | Taken from inbound `X-Request-ID` when present, generated otherwise; on every line |
| Liveness — `/api/health` | ✅ Built | Process is up; touches no dependency |
| Readiness — `/api/health/ready` | ✅ Built | Probes every dependency concurrently with a 2s timeout and reports each **by name** |
| AI execution logging | 📋 Slice 004 | Inputs, model config, token usage, cost per execution (Principle V) |
| Alerting | 🚫 None | No paging, no on-call. A solo project with no availability commitment does not need one; Railway's own health checks cover restart-on-failure |

**Unauthenticated endpoints disclose the kind of failure, not the detail.** Readiness
returns `OperationalError`; the driver's message — which names the internal IP, port, and
database user — goes only to the log.

## 3.5 Rollout plan

Continuous deployment from slice 002 onward: merge to `main` → CI gates → deploy. CI must
pass before deploying, so a red gate blocks the release rather than following it.

**Deployment is deliberately early — before the agent exists.** OAuth redirect URIs,
managed database provisioning, and HTTPS all fail in unfamiliar ways the first time.
Doing it against a nearly-empty application means debugging deployment alone rather than
deployment tangled with a half-finished agent.

**Slice 002 scope**: Railway hosting the existing Dockerfiles, managed Postgres with
pgvector, secrets configured, and the Google OAuth client updated for the deployed domain.
Redis and object storage are **not** deployed — nothing depends on them yet beyond the
readiness probe, so they arrive with slices 003/004. That in turn requires the readiness
endpoint to probe only configured dependencies, since it currently hardcodes all three and
requires all to pass.

**Database provisioning is constrained, and the constraint is not reversible cheaply.**
Railway's default Postgres service does not carry `pgvector`, and adding it afterwards is
not a configuration change — Railway's own guidance is to deploy a pgvector-enabled
Postgres and migrate across with `pg_dump`. The database must therefore be provisioned
from the pgvector image at creation time, which is what was done: `pgvector/pgvector:pg18`,
verified as PostgreSQL 18.4 with `vector` 0.8.6 created successfully.

**Local and deployed run the same Postgres build.** Local was moved from `pg17` to `pg18`
to match, and both report `PostgreSQL 18.4 (Debian 18.4-1.pgdg12+1)` — differing only in
CPU architecture. That alignment surfaced a real incompatibility on the development machine
rather than during a deploy: Postgres 18 images store data in a major-version subdirectory
and expect the volume mounted at `/var/lib/postgresql`, so the pg17 mount path makes the
container exit on startup. Finding it locally cost minutes; finding it mid-deploy, alongside
first-run OAuth and HTTPS, would have cost considerably more. Recorded in `CLAUDE.md`.

**`ENVIRONMENT=production` will run for the first time**, activating HSTS, `Secure`
cookies, and `https_only` sessions. None of that path has ever executed. It must be
verified in the deployed environment, not assumed.

## 3.6 Rollback plan

Three layers that fail differently and must not be conflated:

| Layer | Mechanism | Limit |
|---|---|---|
| **Application** | Redeploy the previous image from Railway's deployment history | Fast and safe — containers are stateless |
| **Schema** | `alembic downgrade` | Works for reversible migrations. **Cannot recover data an irreversible migration dropped** — a `DROP COLUMN` is not undone by re-adding it |
| **Business data** | None, deliberately | Principle IV makes Submitted Resumes and status history immutable |

**The third row is a design decision, not a gap.** Rolling code back does not roll data
back, and it should not: an application whose history rewrites itself on deploy cannot
reproduce what was sent to an employer, which is the guarantee Principle IV exists to
provide.

**Practical consequence:** destructive migrations need a database snapshot taken
immediately before deploy, because the rollback path for them is restore-from-backup, not
`downgrade`. Additive migrations — the overwhelming majority — need nothing.

## 3.7 Alternate solutions considered

Thirteen decisions are recorded as ADRs, each with alternatives and consequences
([docs/02](02_Architecture_Decision_Records.md)). The ones that most shape this spec:

| ADR | Decision | Chosen over |
|---|---|---|
| 001 | Professional Profile as system of record | Document-centric storage, where each resume is primary data |
| 004 | Multi-agent architecture | One large prompt doing everything |
| 005 | LangGraph as orchestrator | Hand-rolled state machine; a linear chain framework |
| 006 | Human-in-the-loop approval | Auto-apply with undo |
| 007 | Immutable submitted resumes | Editable history with an audit trail |
| 008 | RAG over structured knowledge | Embedding everything, including relational facts |
| 012 | Template lineage over live inheritance | Live inheritance — rejected because it silently mutates submitted resumes |
| 013 | Structured parsing over document editing | Storing the uploaded CV as an opaque file |

**Seven corrections to the original design** are recorded in
[docs/05](05_Implementation_Plan.md) §8, including the most serious: evaluation was
originally deferred out of the MVP and has been promoted to a full slice.

---

# 4. Further Considerations

## 4.1 Third-party services

| Service | Provides | If it disappears | Replaceable? |
|---|---|---|---|
| **Railway** | Hosting, managed Postgres | Application is offline; data needs restore elsewhere | Yes — the app is plain Docker; Fly/Render are same-day migrations |
| **Anthropic** | Claude models for every agent | Agents stop; CRUD keeps working | Yes, by configuration — that is what LiteLLM is for (ADR-005) |
| **Google OAuth** | The only identity provider | Nobody can sign in | Moderate — the claims seam is abstracted, but it is the sole provider |
| **LiteLLM** | Provider-agnostic AI gateway | Direct provider calls needed | It *is* the replaceability layer; removing it is the risk |

**LiteLLM is the interesting entry.** It exists so that the Anthropic dependency is
configuration rather than architecture, which is what makes Principle V's
"providers replaceable" claim testable instead of aspirational.

## 4.2 Security

Established conventions from the slice-001 security review — these are standing rules, not
one-off fixes:

- **Configuration errors name the field, never the value.** `get_settings()` catches
  `ValidationError` and rebuilds the message, because pydantic puts rejected input in its
  own error text — a too-short `SESSION_SECRET` was being printed in full by the very
  crash meant to protect it. Secret fields are detected from their `SecretStr` annotation,
  so a new secret is covered automatically.
- **`SecurityHeadersMiddleware` sets `nosniff`, `DENY`, and `no-referrer` on every
  response**, including errors. HSTS is production-only — sending it from plain-HTTP
  localhost pins a scheme that does not work there, and browsers cache the pin.
- **Ownership comes from the session, never the request** (§3.2.2).
- **Unauthenticated endpoints disclose failure kind, not detail** (§3.4).

**The production security path is now proven.** HSTS, `Secure` and `https_only` have run with
`ENVIRONMENT=production` and were confirmed by observing real responses and the real session
cookie in a browser (§5, `specs/002-deployment/observations.md`).

One correction that observation produced and code review could not: **`SecurityHeadersMiddleware`
covers only half the origin.** It is backend-only, so its four headers were present on `/api/*`
and absent from every page a browser navigates to — the frontend serves that HTML, and the
middleware never sees it. `frontend/next.config.ts` now sets the same four with the same values.
**They must stay in step**: a header added to one half and not the other leaves the origin
inconsistent in a way nothing tests.

**Still not done:** a full `/security-review` of the branch diff has never been run — the
slice-001 review was scoped to cookies, headers, and secret handling, and slice 002 verified
behaviour rather than auditing the diff.

## 4.3 Privacy

CareerHQ holds a user's complete career history. That makes privacy a product property,
not a compliance checkbox.

| | |
|---|---|
| **Data held** | Full CV content, employment history, job descriptions applied to, application outcomes |
| **Isolation** | Per-user, enforced from the session; a test asserts cross-user access fails |
| **Third-party exposure** | Profile content is sent to the LLM provider during tailoring — unavoidable for the core feature, and the reason §4.4 rejects training-funded free tiers |
| **Retention / deletion** | 🚫 **Not designed.** No account deletion, no export, no retention policy |

**Retention and deletion are a genuine gap**, listed in §7. For a single-user course
project the exposure is the author's own data; for anything beyond that it is a blocker.

## 4.4 Cost analysis

All figures from published rates as of August 2026. Every assumption is stated so a reader
can recompute rather than trust.

### Recurring — every month the stack is deployed

Railway bills per second for actual memory, CPU, and disk (memory ≈ $0.0139/GB-hour, CPU
≈ $0.0278/vCPU-hour, egress $0.05/GB). Three services — backend, frontend, Postgres.

| Assumption | Value |
|---|---|
| Total memory across three services | 1.0–1.5 GB |
| Average CPU | 0.15–0.25 vCPU |
| Volume | ~1 GB |
| Plan | Hobby, $5/mo including $5 usage credit |
| **Recurring total** | **$10–20 / month** |

Because billing is per second of actual use, **the recurring cost is a function of uptime,
not a flat fee** — pausing services between demos stops the meter. Worth deciding
separately from "redeploys on every merge."

### One-time — during slices 004–005 only

Per tailoring run the workflow makes roughly four model calls (analyse, draft, review,
revise) totalling ~26K input and ~4.3K output tokens.

Rates are $5 / $25 per MTok for Claude Opus 5 and $3 / $15 for Claude Sonnet 5. Applying
the per-node model selection from §3.2.3:

| Node | Model | Tokens (in / out) | Cost |
|---|---|---|---|
| Analyze | Sonnet 5 | 3K / 0.5K | $0.017 |
| Draft | Sonnet 5 | 6K / 1.5K | $0.041 |
| **Reviewer** | **Opus 5** | 8K / 0.8K | **$0.060** |
| Revise | Sonnet 5 | 9K / 1.5K | $0.050 |
| | | | **~$0.17** |

| Configuration | Per run | vs all-Opus |
|---|---|---|
| All Opus 5 | $0.24 | — |
| **Per-node mix (chosen)** | **$0.17** | **−30%** |
| Mix with escalation firing on ~30% of runs | $0.18 | −25% |
| All Sonnet 5 | $0.14 | −42% |

**The Reviewer is 35% of the run cost and it is the right place for the money** — it is the
node whose failure violates Principle III, which is a release blocker. The mix buys Opus
judgement exactly there for roughly 20% more than an all-Sonnet pipeline.

**Prompt caching takes roughly a further 20% off input.** Each node re-sends the same
stable prefix — the Professional Profile, the retrieved guidelines, the system prompts —
and the benchmark re-sends the guidelines across all twenty job descriptions. Cached reads
bill at about a tenth of the input rate, bringing a run to **~$0.15**. That is the figure
used for marginal cost below; $0.18 uncached is the worst case.

| Item | Cost |
|---|---|
| Dev loop — prompt iteration, LangGraph wiring (local model) | **$0** |
| Benchmark + regression runs, ~100 runs at the shipping mix | ~$18 |
| LLM-as-judge scoring (Opus — it is judging quality) | ~$8 |
| Embeddings — local sentence-transformers, no API | **$0** |
| **One-time total** | **~$26** |

**The benchmark must run the mix that ships.** Evaluating an all-Opus pipeline while
production runs the mix would produce metrics describing a system that is never deployed.
Running the real configuration is also cheaper, so this costs nothing to honour.

### Project total and marginal cost

| | |
|---|---|
| Railway over 1.5–2 months | $15–40 |
| LLM one-time | ~$26 |
| **Project total** | **~$41–66** |
| **After launch** | $10–20/month + **~$0.15 per tailoring run** |

**The dominant LLM cost is slice 005's regression runs, not user traffic.** Evaluation
re-runs the same benchmark after every prompt change; that is the whole point of the slice,
and it is what the budget is mostly buying.

### Recommended: split by role, not by budget

Two splits operate at different levels and should not be confused:

| Level | Split | Where it is decided |
|---|---|---|
| **Provider** | Local model for the dev loop; Claude for everything graded | Here — hundreds of throwaway calls need no rate limit, and profile data never leaves the machine (untested — see A6) |
| **Model** | Sonnet per node, Opus for the Reviewer and for escalated revisions | §3.2.3, by how much judgement each node needs |

This is exactly what LiteLLM exists for (ADR-005): both splits are configuration, so they
demonstrate the provider-agnostic claim rather than merely asserting it.

**Free hosted tiers were considered and rejected for the graded path**, for three reasons
that are specific to this system rather than generic quality concerns:

1. **Data.** Mistral's ~1B-token tier *requires* opting into training on submitted data;
   Google's free tier may use prompts to improve its products. CareerHQ's core promise is
   that the user owns their professional identity (§4.3). That trade is not available.
2. **Rate limits break slice 005.** One benchmark run is ~20 job descriptions × 4 workflow
   nodes = **80 calls**. Gemini's free 2.5 Pro tier allows 100 requests/day — roughly one
   regression run per day, in the phase that most needs fast iteration.
3. **The Reviewer is the worst place to economise.** Principle III is a release blocker and
   the Reviewer enforces it. Distinguishing "led a team" from "contributed to a team" is
   the hardest judgement in the system.

Free tiers remain viable for the *dev loop* alongside a local model; the split above is the
recommendation, not a prohibition.

## 4.5 Accessibility

**Current state, honestly:** shadcn/ui builds on Radix primitives, which supply keyboard
navigation, focus management, and ARIA semantics for the dropdown menu and avatar
components in use. **Nothing has been audited** — no axe run, no keyboard-only pass, no
screen-reader testing.

**The specific risk is the item-level approval diff.** It is a dense, comparison-heavy,
interactive surface, it is the one screen a user cannot route around, and diff interfaces
are among the harder patterns to make accessible. Building it without an accessibility pass
would put the system's central interaction out of reach for some users.

Listed as an open question in §7 rather than claimed as handled.

## 4.6 Operational considerations

Solo project: no on-call, no runbook, no SLA. Operations reduce to the quickstart, the
Docker commands, and the recorded gotchas — all in
[CLAUDE.md](../CLAUDE.md) and [README.md](../README.md).

**Gotchas are recorded rather than rediscovered.** A representative sample, each of which
cost real time once: `docker compose restart` does not pick up `.env` changes (environment
is injected at container *creation*, so use `up -d`); Playwright must target `127.0.0.1`
because Node resolves `localhost` to `::1` while Docker publishes IPv4 only; and every
checkout of the repo shares one set of Docker volumes, because `docker-compose.yml` pins
`name: careerhq` — cloning into a new directory does *not* give a clean database.

## 4.7 Risk analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Four-to-six weeks is not enough for nine slices** | High | High | Slices 001–007 are the core and satisfy every graded requirement; 008 and 009 are explicitly droppable ([docs/05](05_Implementation_Plan.md) §5) |
| **Reviewer fails to catch fabrication** | Medium | **Critical** | Principle III is a release blocker. Slice 005 *measures* grounding accuracy rather than assuming it — this is precisely why evaluation was promoted to a slice |
| ~~Railway pgvector support unverified (A2)~~ | — | — | **Retired.** Verified on the deployed database: PostgreSQL 18.4, `vector` 0.8.6 created successfully |
| Production security path unproven (§4.2) | Medium | Medium | Slice 002 exists partly to prove it; deploying early is the mitigation |
| Solo developer, no redundancy | Medium | High | SDD artifacts in `specs/` make project state legible to anyone; nothing lives only in the author's head |
| LLM cost overrun from a runaway loop | Low | Medium | Every execution records tokens and cost (Principle V); §4.4 sets the budget it is measured against |
| Scope creep into the deferred builder | Low | High | Recorded as a non-goal with a stated reason (§2.5, ADR-013) |

---

# 5. Success Evaluation

Two different kinds of measurement, because deterministic code and model output cannot be
judged the same way.

## 5.1 Deterministic components

Measured by the gates in §3.3. There is no model output to judge; a test either passes or
it does not.

## 5.2 Agent quality — slice 005

This is the difference between *"I built an agent"* and *"I know how well my agent works"*,
which is the more interesting claim.

| Metric | Question it answers |
|---|---|
| **Grounding accuracy** | What proportion of generated claims trace to existing profile content? |
| **Requirement coverage** | How much of a job description's must-have list does the tailored resume address? |
| **Match Score calibration** | Do higher scores actually correspond to better human-rated resumes? |
| **Retrieval quality** | Are the guidelines the RAG step returns actually relevant? |
| **LLM-as-judge score** | How does output rate against a rubric — with a human-rated sample to check the judge? |
| **Regression delta** | Did the last prompt or model change improve or degrade the benchmark? |

Built on a **fixed benchmark set** of job descriptions paired with profile states, so
results are comparable across runs, with a results view showing metrics over time.

**Product-level success**, from [docs/00](00_Product_Vision.md): a user imports a CV once
and never retypes it; tailoring takes minutes rather than an hour; and the Career Advisor's
identified gaps demonstrably narrow over time.

---

# 6. Work

## 6.1 Roadmap

| # | Slice | Delivers | Depends on | Status |
|---|---|---|---|---|
| 001 | Platform Foundation | Containers, Google sign-in, authenticated shell, CI | — | ✅ **Complete** |
| 002 | Deployment | Public HTTPS URL, redeploy on merge | 001 | ✅ Complete |
| 003 | Data Foundation | CV import and parsing, profile, applications, JobTracker import | 001 | ✅ **Complete** — 109/109, including the JobTracker import run against production |
| 004 | Match Analysis | Score a job against the profile, per-requirement evidence | 003 | ✅ **Complete**, verified in production |
| 005 | **Resume Tailoring** | LangGraph workflow, Reviewer, versions, item-level approval | 004 | ✅ **Complete** — 101/101, deployed, and exercised by a real paid production run (T088). SC-006 met by one run of four; **SC-001 missed by all four** and the target was not adjusted |
| 006 | Document & Retrieval | RAG over resume guidelines, PDF export, submit-and-lock | 005 | ✅ **Complete** — 57/57, deployed. **SC-008 (006) missed at 3.22%** against a ≤2% threshold; the target was not adjusted |
| 007 | Evaluation & Benchmark | Benchmark set, metrics, LLM-as-judge, regression runs | 006 | ✅ **Complete** — 50/50. Paid benchmark pass run at **$4.925403** of a $10 ceiling |
| 008 | Company Research | Search → fetch → synthesise, citation-preserving snapshots | 003 | ✅ **Complete** and merged. Web search over **plain HTTPS, not MCP** — argued in `tavily_search.py`. Its **primary path is superseded by 010**, which keeps this pipeline as the configured fallback; Layer 2 (role research) never had a route, and 010's migration `0020` reshaped its table |
| 009 | Career Advisor | Quantified skill gaps over history | 003, 004 | 📋 Planned — droppable |
| 010 | Role-Aware Research | ResearchProvider seam, application-scoped and role-aware, sections-first UI | 008 | ✅ **Complete** — 40/40 tasks, merged as PR #22 and deployed. SC-001 measured on 5 real applications (4 correct, 1 honest-uncertain, 0 wrong) |

**Slices 001–007 are the core** and together satisfy every project requirement. 008 and 009
add the most product value per unit of effort, but the project is defensible without them.

## 6.2 Definition of done

A slice is complete when **all** hold: every functional requirement has passing test
coverage; backend coverage is ≥80% with ruff and mypy passing; the quickstart runs clean
from a fresh clone; **the slice works on the deployed environment, not only locally**; the
capability can be demonstrated end to end to a person; and design documents and code agree.

## 6.3 Method

Spec-Driven Development using GitHub Spec-Kit. Every slice runs
`specify → plan → tasks → analyze → implement → verify`, and artifacts are
version-controlled under `specs/`.

**`analyze` is not skipped** — it is a cross-artifact consistency check that runs before any
code is written, and it has caught requirements with no task coverage and conflicts with
the constitution while they were still cheap to fix.

## 6.4 Requirement coverage

**Corrected in slice 005 (T091).** Four rows still named pre-renumbering slices — the
2026-08-22 renumbering reached `docs/05` and the roadmap above but not this table, so it
credited the agent to 004, retrieval to 004, and evaluation to 005. Evaluation is **007**,
and it is the row that matters most: it is a graded requirement that has now been deferred
twice.

| Project requirement | Satisfied by | Status |
|---|---|---|
| Specifications | `docs/00`–`docs/08`, `specs/` | ✅ |
| Plan with milestones | [docs/05](05_Implementation_Plan.md), §6.1 | ✅ |
| Agent with backend and frontend | Slice 005 — FastAPI + Next.js, the Tailor tab | ✅ built, not yet deployed |
| Agent manages memory | Profile, application history, submitted versions; slice 009 reasons over all of it | 📋 |
| Tools / MCPs | Retrieval, PDF export (006); web search + research provider (008/010, plain HTTPS rather than MCP — argued in `tavily_search.py`) | ✅ |
| Agentic workflow matched to the problem | Self-critique + human approval (005); RAG (006) | ✅ built, not yet deployed |
| Evaluation, benchmark, metrics | Slice 007, §5.2 | 📋 **graded, and deferred twice** |
| Deployed using Docker | Slice 002, then continuously | ✅ |
| Team roles | Solo; SDD keeps specification, evaluation, and engineering separated as artifacts | ✅ |

---

# 7. Deliberation — open questions

Unresolved, listed rather than hidden.

| # | Question | Blocks | Notes |
|---|---|---|---|
| ~~Q1~~ | ~~Does Railway's managed Postgres support `pgvector`?~~ | — | **Closed.** Verified on the deployed database — PostgreSQL 18.4, `vector` 0.8.6 available and created. Provisioning constraint recorded in §3.5 |
| ~~Q2~~ | ~~How should readiness report dependencies that are configured-but-absent?~~ | — | **Closed.** Probing follows configuration, and an unconfigured dependency reports `not_configured` — never `ok`, and never omitted. Overall status considers checked dependencies only, so an absent dependency can neither fail the check nor mask a real failure. Verified on the deployed system. The blocker turned out to sit one layer earlier than the endpoint: `REDIS_URL` and the `S3_*` settings were required fields, so the backend could not start at all without them |
| Q3 | Can a local model on this machine serve the dev loop? | §4.4 savings | Assumption A6, **untested**. If not, dev-loop cost returns to ~$50 |
| Q4 | Three coupled parameters: the Reviewer's confidence threshold, the maximum revision attempts, and the attempt at which Revise escalates to Opus (§3.2.3) | Slice 004 | Needs the benchmark from slice 005 to set empirically — chicken-and-egg; start with threshold-plus-two-attempts-escalating-on-the-second and calibrate. Slice 005 can then measure whether escalation actually improves grounding accuracy or merely costs more, which is a sharper evaluation question than tuning a threshold alone |
| Q5 | Account deletion, data export, retention policy | Beyond course scope | §4.3. Unbuilt and undesigned |
| Q6 | Accessibility audit of the item-level approval diff | Slice 004 | §4.5. No audit has been run on anything |
| Q7 | Open questions inherited from the domain model | Various | [docs/03](03_Domain_Model.md) §16 |

---

# 8. End Matter

## 8.1 Related documents

| Document | Answers |
|---|---|
| [00_Product_Vision.md](00_Product_Vision.md) | Why CareerHQ exists |
| [01_Functional_Product_Requirements.md](01_Functional_Product_Requirements.md) | What it must do |
| [02_Architecture_Decision_Records.md](02_Architecture_Decision_Records.md) | Why each choice was made |
| [03_Domain_Model.md](03_Domain_Model.md) | What the entities are |
| [04_System_Design.md](04_System_Design.md) | How it is built |
| [05_Implementation_Plan.md](05_Implementation_Plan.md) | In what order |
| [06_Technology_Stack.md](06_Technology_Stack.md) | With what tools |
| [07_Capabilities.md](07_Capabilities.md) | What each part does — the one-page map |
| [constitution.md](../.specify/memory/constitution.md) | What must always be true |
| `specs/00N-<slice>/` | Per-slice spec, plan, and tasks |

## 8.2 External references

- [A practical guide to writing technical specs](https://stackoverflow.blog/2020/04/06/a-practical-guide-to-writing-technical-specs/) — the structure of this document
- [GitHub Spec-Kit](https://github.com/github/spec-kit) — the SDD tooling
- [JobTracker](https://github.com/nirtituani/job-tracker-web) — the predecessor and migration source
- [Railway pricing](https://railway.com/pricing) and [Anthropic pricing](https://platform.claude.com/docs/en/pricing) — the rates in §4.4

Original source material — course requirements, the author's design notes, and the
resume-builder reference — is in [`reference/`](reference/).

## 8.3 Acknowledgements

Built solo. The design owes its shape to the original course brief and to JobTracker,
which proved the tracking workflow and supplied the data that makes the Career Advisor
possible on day one.
