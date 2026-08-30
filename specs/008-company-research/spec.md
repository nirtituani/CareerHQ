# Slice 008 — Company Research: specification

**Depends on**: slice 003 (Data Foundation) only, per `docs/05_Implementation_Plan.md:91`.
**Status**: Planned — droppable. Slices 001–007 are the core; 008 and 009 follow if budget allows.
**Companion**: `research.md` carries the evidence behind every decision here.

Requirement numbers below are **slice-scoped** (`FR-001…`), matching the convention in
`specs/005-resume-tailoring/spec.md`. They realise `docs/01`'s FR-019 and FR-020 and capability
`docs/07` §3.4.

---

## 1. What this delivers

On-demand research about an employer, produced by an agent that searches the public web through an
**MCP server**, and saved as an **immutable, timestamped snapshot in which every claim carries its
source**.

The output has **two complementary layers**:

| | **Layer 1 — General company understanding** | **Layer 2 — Role-specific perspective** |
|---|---|---|
| Answers | What does this company do, build and sell, and for whom? | What does this company look like through the lens of *this job*? |
| Scope | **Company** — one per employer | **Application** — one per job |
| Role-dependent? | **No, deliberately** | Yes |
| Prepares you for | A general or HR conversation, or simply understanding the employer | A technical or team-specific conversation |
| Reused | Across every application to that employer | Not reused; it is about one job |

**Layer 1 must remain useful with no job attached.** A design in which the whole output is shaped by
the target role would defeat its purpose and forfeit its reuse. Layer 2 is where role-specific and
technical depth belongs.

The point is not a summary. The point is a summary you can check.

---

## 2. Why it exists

Two reasons, and they are different:

1. **Product.** `docs/00_Product_Vision.md:42` names the problem — "Company research is repeatedly
   repeated." A candidate researches the same employer before applying, before a phone screen, and
   before an onsite, and throws the work away each time.
2. **Project.** It is the system's **second agent** and the only capability that introduces an
   **MCP** tool boundary, which `docs/05:330` names as an explicit reason for the slice. It also
   gives slice 007 a second, differently-shaped capability to evaluate — one graded on *citation
   accuracy* rather than on score calibration.

---

## 3. User stories

### US1 — Understand a company after adding a job

*As a job seeker who has just added a job I am considering, I want to understand what the company
actually does and sells, so I can judge whether it interests me and hold an informed general
conversation — whether or not an interview is ever scheduled.*

**Acceptance criteria**

- Research is requested explicitly, from an application or from the company. It never runs
  automatically. (`docs/01`: "Research is generated on demand.")
- Research is available **from the moment an application exists**. Nothing about the request path
  requires a scheduled interview, and no acceptance criterion may assume one.
- Layer 1 covers, each section present even when empty: **what the company does**, its **products
  and services**, its **market, customers and business context**, and other materially important
  general facts.
- **What the company does and what it builds is the primary output.** Location, working conditions
  and benefits are secondary: included when found, never at the expense of the above.
- Layer 1 is **independent of the target role** and reads identically for two different jobs at the
  same employer.
- Every factual claim carries at least one source: a URL, the page title, and the timestamp at which
  it was retrieved.
- A section the research could not support comes back explicitly empty with a stated reason, never
  silently absent.
- The run is bounded: a stated maximum number of sources, and a stated maximum wall-clock time, both
  configured rather than emergent.

### US2 — See the company through the lens of the job

*As a job seeker who has added a specific job, I want that company analyzed against the role I would
actually be doing, so I can hold a technical conversation with the people I would report to or work
with — typically a team lead or hiring manager — and ask informed questions.*

**Acceptance criteria**

- Layer 2 takes the **application** as its context: the job title, its description, and its extracted
  requirements — not merely the company name.
- The **emphasis is determined by the role**. For a software-engineering role this may include
  architecture, technologies, infrastructure, AI and data systems, scale, engineering challenges and
  **engineering practices**; a different role draws a different emphasis. The section set is
  therefore not fixed.
- Layer 2 surfaces technical detail **only where reliable public evidence exists**. Where it does
  not, it says so. It never invents architecture, scale or tooling to fill a heading.
- Layer 2 records which Layer 1 snapshot it was derived from, and that snapshot's age.
- Layer 2 is useful **before any interview is scheduled** — it is preparation *and* evaluation of
  whether the job is worth pursuing.
- Layer 2 surfaces **which technical topics are likely to come up** in a conversation about this
  role at this company, so the user knows what to prepare — not only what the company is like.
- The test it must pass: could a candidate walk into a conversation with this and ask a question
  that shows they understand the engineering problem?

### US3 — Read research that is honest about its age

*As a job seeker returning to an employer months later, I want to see when the research was done,
so I can tell current fact from stale fact.*

**Acceptance criteria**

- Every snapshot displays its retrieval timestamp prominently, not in a tooltip.
- A snapshot is **never** edited or overwritten. Re-running research writes a new snapshot.
- Earlier snapshots for the same company remain readable.
- Research older than the configured **stale** window is visibly marked. It is still shown —
  `docs/07:152`: "Research from three months ago is still useful, but it must be visibly three
  months old rather than silently wrong."
- A **separate, shorter reuse window** governs whether a Layer 1 snapshot may be reused instead of
  re-researched. The two windows are independent: research may be too old to reuse while still being
  fresh enough to display unmarked.

### US4 — Reuse research across applications to the same employer

*As a job seeker who applied to three roles at one company, I want one body of research, not three.*

**Acceptance criteria**

- A snapshot belongs to a **company**, and is visible from every application to that company.
- Research requested in the context of a specific posting may additionally be linked to that
  application, without becoming invisible to the others.
- Research is **never shared across users**, inheriting slice 003's decision that a `Company` row is
  per-user precisely so one person's research cannot leak into another's account
  (`backend/src/careerhq/domain/models/application.py:131-137`).

---

## 4. Functional requirements

### Producing research

- **FR-001** The system shall generate company research on explicit request, never automatically.
- **FR-002** Research shall be requested with a company name and, when known, a domain — the input
  `docs/07:141` specifies. The existing `Company.domain` column supplies the second half.
  **When the request originates from an application, that application is additionally supplied as
  context** — job title, description, and extracted requirements — and drives Layer 2 (FR-022).
  Layer 1 does not read it.
- **FR-003** Research shall be performed over an **MCP** web-search tool boundary. A hand-rolled
  search client does not satisfy this requirement.
- **FR-004** A run shall be bounded by a configured maximum number of sources consulted and a
  configured maximum duration. Both are named constants, not prompt instructions.
- **FR-005** No prompt shall ask a model to reproduce retrieved page text verbatim. Retrieved
  content is summarised and quoted in short excerpts only. (`research.md` R7 — the measured
  52-second failure in slice 003.)

### The two layers

- **FR-020** Research shall produce **two complementary layers**: a general company understanding
  (Layer 1) and a role-specific perspective (Layer 2).
- **FR-021** **Layer 1 shall be independent of the target role** and scoped to the **company**. It
  shall not read the job title, description or requirements, and shall be reusable unchanged by
  every application to that employer. A Layer 1 snapshot produced for one job must be valid for
  another job at the same company.
- **FR-022** **Layer 2 shall be scoped to the application** and driven by the **target role**: the
  job title, the job description, and the extracted requirements. Its emphasis is determined by that
  target role, so its section set is **variable rather than fixed**. It does not read the user's own
  profile or history — the lens is the job being applied for, not the applicant.
- **FR-023** Layer 2 shall record the identity and retrieval timestamp of the Layer 1 snapshot it
  was derived from, so a role analysis can state what company research it rests on and how old that
  research was.
- **FR-033** A Layer 2 snapshot's **effective age is the older of its own age and that of the Layer 1
  snapshot it rests on**, and staleness shall be judged on that effective age. A recent role
  analysis built on long-stale company research is not fresh, and presenting it as fresh is the
  "silently wrong" failure `docs/07:152` warns against.
- **FR-024** Layer 2 shall assert technical detail **only where reliable public evidence exists**,
  and shall state the absence explicitly where it does not. Filling a heading with plausible
  architecture, tooling or scale is a fabrication and is forbidden by Principle III.
- **FR-025** Location, working conditions, benefits and similar practical facts are **secondary**.
  They belong to Layer 1, are included when found, and shall never displace what the company does
  and builds.
- **FR-026** Each layer shall carry its own interview-preparation notes: **Layer 1** for a general or
  HR conversation, **Layer 2** for a technical conversation with a team lead or hiring manager.
  Layer 2's notes shall include the **technical topics likely to be discussed** for this role at
  this company, and questions worth asking — preparation is anticipatory, not merely descriptive.
  Neither layer's notes replace the other: they are the two levels of the same preparation.
- **FR-027** Neither layer shall require a scheduled interview. Both are produced and useful from the
  moment an application exists.

### Citations

- **FR-006** Every factual claim in a snapshot shall carry at least one source reference
  comprising a URL, a page title, and a retrieval timestamp.
- **FR-007** The schema shall make an uncited **factual** claim **unrepresentable**, following the
  slice 004 precedent where every verdict but `unverified` must quote its evidence, and the slice
  005 precedent enforced in the database by `ck_reviewer_findings_ungrounded_quotes`. This binds
  the `fact` tier specifically; FR-029 sets what the other two tiers owe instead.
- **FR-008** Each cited claim shall store the **excerpt** from the source that supports it, so
  slice 007 can grade citation accuracy without re-fetching pages that may since have changed.
- **FR-009** A source that could not be retrieved shall be recorded as attempted-and-failed, not
  silently dropped.
- **FR-032** Every stored excerpt shall be verified to appear **verbatim** in the document CareerHQ
  retrieved, and a claim whose excerpt fails that check shall not be presented as sourced. This is a
  **deterministic string check, not a model call** — it is possible only because CareerHQ performs
  its own fetching (`research.md` R10) and therefore holds the document the excerpt is drawn from.
  It defeats citation laundering: an invented claim paired with a real URL cannot survive it.

### Fact, interpretation, inference

The output is only useful if a reader can weigh it. Both layers therefore carry three distinct
kinds of content, and the distinction is structural rather than stylistic.

- **FR-028** Every claim in either layer shall be **typed** as exactly one of:
  - **`fact`** — something a source states. *"They process payments for European retailers."*
  - **`interpretation`** — a reading of stated facts, in the context of the role where relevant.
    *"The volume they describe implies a high-throughput transactional system."*
  - **`inference`** — a reasoned guess that goes beyond what any source states.
    *"They likely run an event-driven architecture."*
- **FR-029** The three tiers carry **different evidence obligations**, and the schema shall enforce
  each:
  - a `fact` must quote at least one source (FR-006, FR-007);
  - an `interpretation` must reference the facts it rests on;
  - an `inference` may be uncited, but must be labelled and may never be presented as a fact.
- **FR-030** The interface shall render the three tiers **visibly differently**. A reader must be
  able to tell a sourced fact from a reasoned guess without opening the citation.
- **FR-031** The tier distinction applies to **both layers**. Layer 1 is expected to be mostly
  `fact`; Layer 2 is expected to carry proportionally more `interpretation` and `inference`. That
  asymmetry is a property of the questions each layer answers, not a defect in either.

### Snapshots

- **FR-010** A snapshot shall be **immutable** once written. There is no edit path.
- **FR-011** Re-running research shall write a new snapshot and leave every earlier one intact.
- **FR-012** A snapshot shall record the retrieval timestamp, the model and prompt version used,
  and the token usage and cost of the run — the audit record Principle V requires, written in the
  same transaction as the work.
- **FR-013** A **Layer 1** snapshot shall belong to a company and shall **not** reference an
  application. A **Layer 2** snapshot shall belong to an application (FR-022) and shall record the
  Layer 1 snapshot it rests on (FR-023). Together these realise OQ-002's MVP decision — "preserve
  Company-level research while allowing Application-specific snapshots" — by giving each half its
  own row rather than one row with an optional scope.

  > **Amended.** This requirement previously read *"A snapshot shall belong to a company, and may
  > optionally reference the application whose context prompted it"*, following `research.md` R5's
  > reading of OQ-002 as a nullable `application_id` on a single snapshot table. **OQ-F later
  > decided two layers** (`open-questions.md`), which moved application scope to Layer 2 wholesale
  > and made the optional column both unnecessary and harmful: a Layer 1 row able to name an
  > application would eventually be *shaped* by one, and FR-021's guarantee — that Layer 1 reads
  > identically for two different jobs at the same employer — is what the reuse in `plan.md` §6
  > rests on. The original wording is preserved here rather than deleted because it explains why
  > `research.md` R5 still describes a nullable `application_id`: that paragraph records the
  > interpretation as it stood before OQ-F, and is accurate history rather than a live design.
- **FR-014** A pointer to the current snapshot for a company shall be maintained, and shall be
  written **only on success** — copying the `current_match_analysis_id` pattern from slice 004
  *including* its T093 correction, so a run in flight is visible rather than reported as the
  previous result.

### Safety

- **FR-015** Every HTTP request made on this slice's behalf shall pass the existing SSRF guard in
  `backend/src/careerhq/infrastructure/jobs/fetch.py` — hostname resolved, non-global addresses
  refused, every redirect hop re-checked, http/https only, and the failure reason never naming what
  was found.
- **FR-016** Retrieved page content shall be framed to the model as untrusted data. Instructions
  found inside retrieved content carry no authority.
- **FR-017** A page that yields only template placeholders or boilerplate shall be refused as a
  source rather than summarised, following the slice 003 finding that a model will happily
  "extract" `{{position.name}}` into a plausible-looking empty result.

### Ownership and isolation

- **FR-018** Ownership shall come from the session, never from the request. No endpoint accepts a
  client-supplied user, company, or snapshot id.
- **FR-019** Research shall never be shared or cached across users.

---

## 5. Non-goals

Each is scoped out for a stated reason, so nobody re-opens it by accident:

- **Automatic or scheduled research.** FR-001 makes it on-demand. Background research would spend
  money on employers the user may never interview with.
- **Editing a snapshot.** Immutability is the feature (FR-010). Correcting research means running
  it again.
- **Cross-user or global research caching.** Contradicts slice 003's stated privacy rationale.
  Attractive on cost, and still out.
- **Interview question generation and mock interviews.** That is the Interview Coach, `docs/07` §3.6,
  a stretch capability. This slice produces *preparation notes*, not a rehearsal.
- **Salary and compensation data.** Not in FR-020's list, and it is the section most likely to be
  confidently wrong from public sources.
- **Judging whether a source supports its claim.** Detecting citation *laundering* — a fabricated
  claim paired with a real URL — is real (`research.md` R4) but needs a reviewer node. Deferred to
  `open-questions.md` rather than assumed.
- **Making the whole output role-dependent.** Layer 2 is personalised; Layer 1 deliberately is not.
  Shaping the general layer by the target role would forfeit its reuse across applications and its
  usefulness to a candidate who simply wants to understand the employer. This is the failure mode
  this spec most needs to avoid.
- **Deciding the number of model calls here.** Two layers is a *product* requirement. How many
  search passes and model calls implement it is an *implementation* question, answered in
  `plan.md` §2 and deliberately not fixed by this document.
- **Reusing slice 006's retrieval layer.** Slice 006 is being designed in parallel. Any overlap is
  reconciled after both specs exist, not guessed at now.

---

## 6. Success criteria

This slice is done when:

1. A user can request research on a company and receive a sectioned brief in which every factual
   claim is clickable through to a source.
2. The same Layer 1 snapshot serves two different jobs at the same employer, and reads identically
   for both — demonstrating it is genuinely role-independent.
3. Layer 2 for a software-engineering role surfaces engineering-relevant material where public
   evidence exists, and explicitly reports its absence where it does not.
4. A reader can tell a sourced fact from an interpretation from an inference at a glance.
5. Both layers are produced, and useful, for an application with no interview scheduled.
6. Re-running research produces a second snapshot, and the first is still readable with its
   original timestamp.
7. Research requested from one application to an employer is visible from another application to
   the same employer.
8. A snapshot older than the configured staleness threshold is visibly marked, not hidden.
9. Every model call and every fetch is recorded with usage and cost.
10. The architecture test still passes: no module under `application/` imports a provider SDK or an
   MCP client directly.
11. The suite runs green with **no provider and no network**, via a scripted search double, exactly
   as `ScriptedSeam` allows the tailoring loop to be tested today.
