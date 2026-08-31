# Feature Specification: Career Advisor Agent with Career Memory

**Feature Branch**: `009-career-advisor`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Slice 009 — Career Advisor Agent with persistent Career Memory. An agent that develops and manages evidence-backed knowledge about the user's job search over time: it derives deterministic quantitative facts from application history and match analyses (SQL aggregation — the LLM never produces a number), reasons over those facts plus its own prior memories, and creates/confirms/supersedes/retires structured career memories (one falsifiable claim + frozen evidence with denominators + provenance + lineage), which power evidence-backed career insights that improve as history accumulates. Insert-only memory lifecycle with supersession lineage; relational retrieval of all active memories (no vector infrastructure); ungrounded insights discarded before persistence; small-N honesty with explicit denominators and an insufficient-data answer; Tier 1 memories from outcome/status/trend data available today (96 imported applications lack posting content), Tier 2 skill-gap memories growing as match analyses accumulate; bulk posting backfill explicitly deferred. Async advisor runs following the match-analysis pending-row pattern; usage/cost recorded per run; new llm_model_advisor task config entries. Frontend surface showing active memories with evidence and lineage."

---

## The one-paragraph version

The Career Advisor is the capability that proves CareerHQ *uses* its accumulated memory rather
than merely storing it (docs/07 §5: "the Core is the memory; the Advisor is what proves it is
being used"). It maintains a set of **career memories**: falsifiable, evidence-backed claims
about the user's job search ("AWS is a recurring gap in the Backend roles you target — required
by 16 of 20 analysed postings, identified as a gap in 14 of them"). The advisor derives every
number deterministically from stored history, reasons over those facts **together with its own
prior memories**, and manages the memory set over time — creating, confirming, superseding and
retiring claims as evidence accumulates or changes. The database stays the source of truth for
raw facts; memory holds only derived, provenance-carrying interpretation. The lifecycle — not a
statistics page — is the feature.

## What "memory" means here, and what it does not

**Raw history** (applications, postings, match requirements and verdicts, statuses, outcomes,
dates) is owned by the existing domains and is never duplicated into memory (Constitution I).

**A career memory** is one derived claim the agent judged worth preserving, carrying:

- a single falsifiable statement in plain language;
- the **frozen evidence** that justified it at the moment it was written — every count with its
  denominator, the identifiers of the underlying records, and the as-of date;
- lifecycle state and lineage — a memory is never edited in place; changed understanding is a
  **new** memory that supersedes the old one, and the chain is the user-visible history of how
  the agent's understanding evolved.

A memory whose claim cannot be traced to its evidence is not stored — the discard-before-
persistence rule the tailoring workflow already applies to ungrounded resume claims applies
identically here (Constitution III).

**Memories are AI-derived data about the user, not user data.** They are shown as the agent's
understanding, visually and structurally distinct from profile facts, and nothing elsewhere in
the product treats them as profile facts (docs/03 §5.5: "AI-derived insights must remain
distinguishable"). Writing a memory therefore does not require per-item user approval — the
agent must be able to manage its own memory (this is what distinguishes it from a
recommendation that changes user-owned data under Principle II) — but the user retains
curation rights over what is shown to them (User Story 4).

## Clarifications

### Session 2026-09-01

- Q: Full learning roadmap, lightweight prioritization, or defer entirely? → A: **B (lightweight)**
  — actionable memories carry an agent-assigned priority with its supporting reasoning/evidence;
  the surface orders by it; a distinct roadmap artifact/page is **explicitly deferred** until
  Tier 2 skill-level data can support honest frequency/impact ranking. docs/07 §3.5's roadmap
  promise is preserved through the prioritization, and the deferral is recorded rather than
  silent.
- Q: Initial value for the small-sample floor? → A: **5**. Claims over denominators under 5
  are tentative or withheld; at or above 5 they may be full-confidence active memories when
  the grounding rules are satisfied. The value is an explicitly calibratable, named and
  versioned constant — an initial placeholder in the `CONFIDENCE_THRESHOLD` discipline, not
  a statistical truth.
- Q: Cap on active memories per user? → A: **Hard cap of 25**, a named and versioned
  constant. At the cap, creating a new memory must be accompanied by retiring at least one
  active memory with an explicit reason — forgetting is part of memory management. Superseded
  and retired memories stay persisted for lineage but do not count toward the cap.
- Q: How is a dismissed claim kept from being recreated? → A: **Both layers** (the
  validator-and-constraint pattern): dismissed memories enter the reasoning input marked
  "dismissed by the user — do not recreate", and a deterministic gate refuses a proposed
  create matching a dismissed memory's kind and scope unless its evidence materially differs
  from what the dismissed memory froze. When genuinely new evidence justifies the claim
  again, the new memory is created with the dismissal history preserved and visible.
- Q: Where does the Advisor live in the interface? → A: **The existing dedicated entry.**
  Navigation already carries a "Career Advisor" item at `/advisor` marked *Soon*; this slice
  activates that entry and builds the page behind it — no navigation redesign, no dashboard
  teaser (a possible future enhancement). The page is the home for the user-scoped memory
  set: active memories, evidence, priority, lifecycle/lineage, run status, and the honest
  empty/insufficient-data states.
- Stated invariant (product owner, this session): a memory counts as **genuinely managed by
  the agent** only if subsequent runs (1) retrieve the prior memory, (2) use it as reasoning
  input, and (3) explicitly disposition it — confirm, supersede, or retire. The lifecycle
  must be demonstrable and testable end to end; persistence alone is not memory. (Sharpens
  FR-013/SC-002 from implication to definition.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - First analysis: history becomes evidence-backed memories (Priority: P1)

A user with accumulated application history (today: 97 real applications, 63 of the 96 imported
ones rejected, statuses, dates, self-assessed match ratings) opens the Career Advisor and
requests an analysis. The agent computes deterministic facts from that history, reasons over
them, and persists a set of career memories. The user sees each memory as a plain-language
claim with its evidence beside it — every number carrying its denominator ("14 of 20"), the
date range it covers, and what it was computed from. Where the data cannot honestly support a
pattern, the advisor says so ("not enough analysed postings to identify skill patterns yet —
1 of 97 applications has a match analysis") rather than padding.

**Why this priority**: without a first run that turns real history into honest, evidence-backed
memories there is no product and nothing for any later story to build on. It is independently
demoable on the data that exists today.

**Independent Test**: seed a scratch user with applications and outcomes (no match analyses
required), request an analysis, and verify: memories exist; every quantitative statement in
every claim is independently recomputable from the seeded rows; claims without support were
not persisted; the insufficient-data answer appears for pattern kinds the seed cannot support.

**Acceptance Scenarios**:

1. **Given** a user with application history but no prior advisor run, **When** they request an
   analysis, **Then** an in-progress state is visible immediately, and on completion a set of
   active memories is shown, each with claim, evidence (counts with denominators), covered date
   range, and as-of date.
2. **Given** the analysis completes, **Then** every number appearing in any persisted claim
   also appears in that memory's frozen evidence, and the evidence identifies the underlying
   records it was computed from.
3. **Given** a pattern kind the current data cannot support (e.g. skill gaps with almost no
   analysed postings), **When** the analysis completes, **Then** the surface states what is
   missing and how it grows, instead of showing a fabricated or padded insight.
4. **Given** a user with no application history at all, **When** they open the advisor,
   **Then** they see an honest empty state naming what the advisor needs, and no run is
   spent.
5. **Given** an analysis fails after starting, **Then** the failure and its reason are visible,
   whatever the run cost is recorded, and any previously active memories remain shown and
   untouched.

---

### User Story 2 - The memory lifecycle: understanding evolves with evidence (Priority: P1)

After the first analysis, the user's history grows — new applications, new outcomes, new match
analyses. The user requests another analysis. This time the agent receives **its own prior
memories alongside the fresh facts** and must reconcile them: a claim the new evidence still
supports is **confirmed** (same memory, refreshed confirmation and evidence delta); a claim the
new evidence changes is **superseded** by a new memory that names the change ("your AWS gap is
narrowing — identified in 2 of the last 10 analysed postings, against 14 of the 20 before");
a claim that no longer applies is **retired** with a stated reason. The user sees continuity:
"since the last analysis…" framing, and per-memory lineage they can open to read how the
agent's understanding of them evolved.

**Why this priority**: this is the requirement. An advisor that starts from zero every run is a
report generator; the lifecycle is what makes the memory real, and it is the graded
demonstration (docs/07 §3.5 evaluates the advisor on whether identified gaps *narrow over
time*, which is unanswerable without a prior state to compare against). It is P1 alongside
Story 1 because shipping Story 1 alone would ship exactly the dashboard this slice was
re-scoped not to be.

**Independent Test**: run an analysis against seeded history, change the history in a way that
confirms one memory, contradicts a second, and moots a third, run again, and verify the three
outcomes — including that the superseding memory links to its predecessor, the predecessor's
frozen evidence is unchanged, and the reasoning step demonstrably received the prior memories
as input.

**Acceptance Scenarios**:

1. **Given** active memories from a prior run, **When** a new analysis runs, **Then** the
   reasoning step receives every active memory as input, and this is asserted from what the
   step actually received, not from plumbing that could have supplied it.
2. **Given** new evidence consistent with an active memory, **Then** the memory remains the
   same memory — confirmed, with its confirmation date advanced and the fresh figures recorded
   beside the original frozen evidence, not overwriting it.
3. **Given** new evidence contradicting an active memory, **Then** a new memory referencing
   the old one is created stating the change, the old memory becomes superseded (never
   deleted, evidence intact), and only the new one counts as active.
4. **Given** an active memory whose subject no longer applies, **Then** it is retired with a
   recorded reason and remains readable in history.
5. **Given** any completed second run, **Then** the user-facing surface distinguishes new,
   confirmed, superseded and retired memories, and each memory's lineage chain is readable.
6. **Given** a run in flight, **When** another is requested, **Then** the second request is
   refused while the first remains recoverable if it is abandoned (the stuck-run lesson from
   match analysis applies).

---

### User Story 3 - Skill-level patterns from analysed postings (Priority: P2)

As the user match-analyses applications (each analysis already stores per-requirement verdicts
with quoted evidence), the advisor gains skill-level material: recurring gaps, recurring
strengths, requirements growing or shrinking in the user's target market, role families where
their match runs stronger. Requirement texts are stored verbatim by design ("5+ years of
Python" and "Python" are different rows), and job titles are free text — so the agent proposes
groupings over the enumerated raw items, deterministic counting then runs over those groups,
and the grouping itself is preserved as part of the evidence ("these 16 requirement texts were
read as AWS"), so a reader can audit both the grouping and the arithmetic.

**Why this priority**: this is the headline example ("AWS in 16 of 20 postings") and the
richest memory source — but it depends on data that today is nearly empty (1 analysed
application in production) and grows organically as the user match-analyses new applications.
It must ship in the slice, honest at small N, and get better on its own.

**Independent Test**: seed a user with several match analyses whose requirement rows share
skills under varying wordings, run an analysis, and verify skill-pattern memories exist whose
counts are recomputable from the seeded verdict rows *via the stored grouping*, that the
grouping maps only real requirement rows (by identifier), and that verdicts are respected
(a gap memory counts gap/partial verdicts, not confirmed ones).

**Acceptance Scenarios**:

1. **Given** several analysed applications with recurring requirements, **When** an analysis
   runs, **Then** skill-pattern memories state frequency with denominators scoped to analysed
   postings ("of the 6 analysed Backend postings"), never to all applications.
2. **Given** the grouping step, **Then** every group member is a real stored requirement row
   referenced by identifier, the group is frozen into the memory's evidence, and counts are
   computed from the stored grouping rather than asserted by the reasoning step.
3. **Given** few analysed postings (below the honesty floor), **Then** skill patterns are
   either withheld with the insufficient-data answer or marked tentative with their small
   denominator stated — and no causal claim (e.g. "this gap causes rejections") is made at
   any N in this slice.
4. **Given** the 96 imported applications without posting content, **Then** they are never
   silently counted into skill denominators, and the surface says why the skill sections
   grow only as analyses accumulate.

---

### User Story 4 - The user curates what the advisor remembers about them (Priority: P3)

The memories are about the user, so the user can act on them: dismiss a memory they consider
wrong or unwelcome (it is retired with "dismissed by you" as the recorded reason and is not
recreated in identical form by later runs), and read the full memory history including
superseded and retired items. Pinning, editing, or annotating memories is out of scope for
this slice.

**Why this priority**: the Principle II instinct — the person owns their career narrative —
applied to AI-derived data. Valuable, small, and droppable without harming the core lifecycle
(approved as a product question rather than an MVP blocker).

**Independent Test**: dismiss an active memory, verify it leaves the active set with the
dismissal recorded, run a new analysis on unchanged data, and verify the dismissed claim does
not reappear as a new active memory.

**Acceptance Scenarios**:

1. **Given** an active memory, **When** the user dismisses it, **Then** it is retired with the
   dismissal recorded as the reason and disappears from the active set without being deleted.
2. **Given** a dismissed memory, **When** a later analysis runs over unchanged evidence,
   **Then** the run is aware of the dismissal and does not recreate the same claim as active.
3. **Given** the history view, **Then** superseded, retired and dismissed memories are
   readable with their reasons and lineage.

---

### Edge Cases

- **No history at all**: honest empty state; no run spent (Story 1, scenario 4).
- **Nothing new since the last run**: the run is permitted, and confirming everything (or
  changing nothing) is a legitimate outcome that is shown as such — "no change since
  <date>" is a result, not a failure.
- **Run failure mid-flight**: the failure is recorded with a reason and its cost; previously
  active memories are untouched and still served (the last-success rule research already
  follows).
- **Abandoned run**: a run that will never finish must not block the next one forever, and
  must not be mistaken for one plausibly still in flight.
- **Contradiction within one run**: the reasoning step may not emit two active memories that
  contradict each other; reconciliation happens before persistence.
- **A memory's underlying records disappear** (e.g. the user deletes an application): the
  memory's frozen evidence still names what it was computed from at the time; the next run
  reconciles against current data. Frozen evidence is a record of past justification, not a
  live pointer that must stay resolvable.
- **Numbers below any floor**: a denominator of 1 or 2 is stated as such, and the tentative
  marking (Story 3, scenario 3) applies; the advisor never rounds, extrapolates, or projects.
- **The reasoning step returns nothing usable**: the run fails honestly with cost recorded;
  no retry within the run (the project-wide no-automatic-retry rule).
- **Every insight proposal is discarded by the grounding gate**: the run completes with zero
  new memories and the discards are observable to the operator — a run that quietly persists
  nothing is indistinguishable from a run that found nothing, and they are different results.

## Requirements *(mandatory)*

### Functional Requirements

**The run**

- **FR-001**: Users MUST be able to request a career analysis on demand for their own history
  only; the run executes asynchronously with an immediately visible in-progress state, and at
  most one run per user may be in flight (enforced where it cannot be raced).
- **FR-002**: A stuck or abandoned run MUST stay recoverable: a row no longer plausibly in
  flight is treated as failed and does not block a new request.
- **FR-003**: Every run MUST record what it consumed and produced: model configuration, token
  usage and cost — including on failure, where the run records what it actually spent rather
  than reading as free.
- **FR-004**: A failed run MUST leave previously active memories untouched and served, with
  the failure reason visible to the user (kind of failure, not internal detail).

**Facts before reasoning**

- **FR-005**: All quantitative facts MUST be computed deterministically from stored history
  before any reasoning step, each fact carrying its value, denominator, covered date range,
  and the identifiers of the records it was computed from. The reasoning step receives facts;
  it MUST NOT be the source of any number.
- **FR-006**: The set of facts computed for a run MUST be reproducible: the same stored
  history yields the same facts, so any persisted memory's evidence can be independently
  recomputed and checked.
- **FR-007**: Where grouping of free-text values (job titles into role families, requirement
  texts into skills) is needed, the reasoning step MAY propose groupings — but only over
  enumerated stored items referenced by identifier; counting then runs deterministically over
  the proposed groups, and the grouping is preserved in the evidence of any memory that
  relies on it.

**Memory content and grounding**

- **FR-008**: A career memory MUST consist of exactly one falsifiable plain-language claim,
  a pattern kind, a scope (which slice of history it is about), and frozen evidence: the
  facts (with denominators and record identifiers) that justified it, plus the as-of date.
- **FR-009**: Every quantitative statement in a persisted claim MUST be present in that
  memory's evidence. A proposed insight citing facts that do not exist, or containing numbers
  its cited evidence does not contain, MUST be discarded before persistence — it never
  reaches a stored row — and each discard MUST be observable to the operator with what was
  discarded and why. Zero-new-memories-because-all-discarded and
  zero-new-memories-because-nothing-found MUST be distinguishable outcomes.
- **FR-010**: Claims below the small-sample floor MUST be either withheld with the
  insufficient-data answer or persisted as tentative with the small denominator stated in
  the claim. No memory in this slice may assert causation; observed co-occurrence must be
  worded as such. The floor is a named, versioned constant so changing it is an honest act;
  its initial value is **5** (Clarification Q2) — a calibratable placeholder, not a
  statistical claim.
- **FR-011**: Insufficient data MUST be a first-class user-visible answer naming what is
  missing and how it accumulates — for skill-level patterns today, that only match-analysed
  applications count and imported applications without posting content never enter those
  denominators.

**Memory lifecycle**

- **FR-012**: Memories MUST be insert-only. Understanding that changes is expressed by a new
  memory superseding the old one (with a link and a stated change), never by editing a
  persisted claim or its frozen evidence. Confirmation advances a confirmation date and
  appends fresh figures without altering the original evidence.
- **FR-013**: Each analysis after the first MUST receive every active memory as reasoning
  input and MUST disposition every one of them: confirm, supersede, retire (with reason), or
  explicitly leave open where evidence is absent either way. The reasoning step proposes;
  deterministic application logic validates and applies. Unaccounted-for active memories are
  a run defect, not a silent omission. **This is the definition of agent-managed memory**
  (stated invariant): a memory counts as managed only if subsequent runs retrieve it, use it
  as reasoning input, and explicitly disposition it — each of the three demonstrable from
  what the run actually did, not from plumbing that could have done it. Persistence alone is
  not memory.
- **FR-014**: Superseded and retired memories MUST remain readable with their evidence,
  reasons and lineage; only active (and tentative) memories represent the advisor's current
  understanding, and only they are fed to subsequent runs as its prior state.
- **FR-015**: Active memories for a user MUST be retrieved relationally and in full for both
  reasoning and display. No vector or semantic retrieval infrastructure is introduced by this
  slice.
- **FR-016**: A run MUST NOT leave two active memories asserting contradictory claims about
  the same subject; reconciliation is part of dispositioning before persistence.
- **FR-016a**: The active set is bounded by a hard cap of **25** memories per user, a named
  and versioned constant (Clarification Q3). A run may not end with more than 25 active
  memories; at the cap, a create must be accompanied by at least one retire with an explicit
  reason — and the cap is evaluated with dispositions applied first, so a same-run
  create-plus-retire at the cap is valid and ends at the cap. Superseded and retired
  memories persist for lineage and do not count toward the cap.

**Boundaries**

- **FR-017**: Memories are AI-derived interpretation and MUST remain structurally and
  visually distinct from user-owned data. No other capability (matching, tailoring, research,
  import, profile) may read career memories as profile facts or write to them; raw history
  remains the sole source of quantitative truth.
- **FR-018**: All access MUST derive ownership from the session (the existing rule: no
  client-supplied user identifier), and career memories MUST be scoped to their user.
- **FR-019**: This slice MUST NOT modify the research capability (slice 010) or its
  provider seam, and MUST NOT perform bulk posting backfill. Enriching an individual
  application (pasting a posting, running a match analysis) remains the existing product
  path and is how the advisor's skill-level material grows.

**Prioritization** *(Clarification Q1)*

- **FR-022**: Actionable memories MUST carry an agent-assigned priority whose reasoning is
  stated and whose supporting facts live in the memory's evidence like any other claim; the
  user-facing surface orders memories by it. A distinct learning-roadmap artifact or page is
  **deferred** until Tier 2 skill-level data can support honest frequency/impact ranking —
  a recorded deferral (docs/07 §3.5 promises the roadmap; this slice keeps the promise
  through prioritization and names what is postponed).

**Surface**

- **FR-020**: Users MUST be able to see their active memories with claim, evidence
  (denominators and date ranges), scope, priority, as-of and last-confirmed dates;
  distinguish new/confirmed/superseded/retired after a run; open a memory's lineage; see run
  status, failure states, the honest empty state, and the insufficient-data answers. The
  surface is the existing dedicated "Career Advisor" navigation entry, currently marked
  *Soon* — this slice activates it and builds the page behind it; no navigation redesign and
  no dashboard teaser (Clarification Q5).
- **FR-021**: Users MUST be able to dismiss an active memory; dismissal retires it with the
  user's action as the recorded reason. Non-recreation is enforced in two layers
  (Clarification Q4): dismissed memories enter later runs' reasoning input marked "dismissed
  by the user — do not recreate", **and** a deterministic gate refuses a proposed create
  matching a dismissed memory's kind and scope unless its evidence materially differs from
  the evidence the dismissed memory froze. A genuinely new evidence-backed recreation is
  shown as new with the dismissal history preserved. *(User Story 4 — droppable without
  affecting FR-001–FR-020.)*

### Key Entities

- **Career Memory**: one falsifiable claim the agent judged worth preserving. Claim text,
  pattern kind (open vocabulary — the agent may discover pattern types not anticipated
  here), scope, frozen evidence (facts with denominators, record identifiers, date range,
  as-of), lifecycle state (active / tentative / superseded / retired), supersession link,
  created / last-confirmed timestamps, and the run that wrote it.
- **Advisor Run**: one analysis execution. Status (pending / ready / failed), timestamps,
  model configuration, token usage, cost, failure reason; the audit anchor every memory
  points back to (Constitution V).
- **Evidence** (within a memory, not a free-standing store): the deterministic facts — and,
  where used, the groupings — that justified the claim at write time. Frozen: a record of
  past justification, never a live view.
- **Memory lineage**: the supersession chain from any active memory back through its
  predecessors — the user-readable history of how the agent's understanding evolved, and
  the substrate for "is this gap narrowing" (docs/07 §3.5's evaluation question).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: **Groundedness is total.** For every persisted memory, every number in its
  claim appears in its frozen evidence, and independently recomputing each evidence fact
  from stored history reproduces it exactly. Verified over all memories produced in the
  acceptance runs — the count of memories audited is asserted, so an empty audit cannot
  pass.
- **SC-002**: **The lifecycle demonstrably works end to end.** On real (or realistic seeded)
  history: a first run produces evidence-backed memories; after history changes, a second
  run confirms at least one, supersedes at least one with a lineage link and a stated
  change, and retires at least one with a reason — and the second run demonstrably
  **retrieved** the prior memories, **received them as reasoning input**, and
  **dispositioned every one** (the agent-managed-memory invariant), with zero active
  memories left unaccounted for.
- **SC-003**: **Small-N honesty holds everywhere.** No persisted claim lacks a denominator;
  every claim below the floor is tentative or withheld; imported applications without
  posting content appear in no skill-pattern denominator; zero causal claims. Verified
  over all memories from the acceptance runs.
- **SC-004**: **The advisor is honest about today's data.** Against current production-shaped
  history (97 applications, ~1 analysed), a run yields outcome/status/trend memories plus
  the insufficient-data answer for skill patterns — not zero results and not fabricated
  skill insights.
- **SC-005**: **Failure is never free or destructive.** A run that fails after starting
  records a non-zero-or-explained cost and reason, and the previously active memory set is
  byte-for-byte unchanged.
- **SC-006**: **The user reaches insight cheaply.** From opening the advisor to seeing
  evidence-backed memories: one action plus the run's wall-clock time, with a visible
  in-progress state throughout; a typical run completes within two minutes.
- **SC-007**: **A run's cost is bounded and known.** Reasoning-step spend per run is recorded
  per Constitution V and a measured typical run costs at most a configured budget of the
  same order as a match analysis (single-digit cents to low tens of cents), not a tailoring
  run.

## Assumptions

- **Data reality (measured 2026-08-31)**: production holds 97 applications for one real
  user; 96 imported rows have no posting content and are refused by scoreability — so
  outcome/status/trend memories are the day-one material and skill-level memories start
  near-empty and grow. The spec treats this as a feature constraint, not a blocker.
- **Bulk posting backfill is deferred** (approved): it is billable, touches irreplaceable
  production rows, and the per-application enrichment path already exists. If a future
  slice builds it, the advisor benefits without change.
- **Interview feedback is out of scope**: docs/03 anticipates it feeding the advisor, but
  the entity is not implemented; this slice reasons only over data that exists.
- **No vector infrastructure** (approved): one user accumulates tens of memories; full
  relational retrieval is the simplest genuine memory. Nothing here forecloses semantic
  retrieval later if memory counts warrant it.
- **Memory writes need no per-item user approval**: memories are the agent's own derived
  understanding, not user-owned professional data, so Principle II's approval gate does not
  apply to writing them — it is what makes the agent able to manage memory at all. The
  user's control is curation (Story 4) and the fact that raw data stays authoritative.
- **Reasoning uses the existing single completion seam** with per-task model configuration
  (a new task name configured explicitly — the Opus-fallback pricing trap is known), the
  existing async pending-row pattern, and the existing ownership/security rules. No new
  agent-framework machinery is assumed.
- **One user, one memory set**: memories are per user (not per application or per role
  family as ownership), with scope expressed inside the memory.
- **Kind vocabulary is open** (approved): the agent may record pattern kinds beyond the
  examples in this spec; grounding rules, not topic whitelists, are the constraint.
