# Feature Specification: Resume Tailoring

**Feature Branch**: `005-resume-tailoring`

**Created**: 2026-08-22

**Status**: Draft

**Input**: The approved design at [docs/superpowers/specs/2026-08-22-resume-tailoring-design.md](../../docs/superpowers/specs/2026-08-22-resume-tailoring-design.md) — adapt the owner's resume to a recorded job through a bounded agent loop that criticises its own work, and let the owner approve or reject every change item by item.

## Why This Slice Exists

Slice 004 answers *is this job worth my afternoon, and where am I weak*. A person who reads that
answer and decides yes has nowhere to go. This slice is where they go.

It is also **the flagship**. `docs/05` §5.4 puts it plainly: everything before it exists to make
it possible, and everything after builds on it. Four project requirements are demonstrated here
and nowhere else — multi-step agent orchestration, self-critique, guardrails against fabrication,
and human-in-the-loop approval.

### This is the first loop

Every AI call in CareerHQ so far is one structured completion in, one validated object out. The
seam was built that way deliberately, and its own docstring reserves this slice: *"A caller that
needs the model to react to its own previous output belongs in the agent runtime, not here."*

This slice builds that runtime. The seam does not change; four new callers sit above it.

### The Reviewer is the point

A model asked to make a resume match a job description will invent experience. That is not a
risk to mitigate later — it is the default behaviour, and Principle III makes it a release
blocker. The Reviewer is a separate, stronger judgement pass that reads the draft against the
profile and refuses claims that trace to nothing. It runs without asking the owner, and what it
rejects for fabrication never reaches an approval screen at all.

A guardrail nobody can see is indistinguishable from one that is not running, which is why its
findings are shown rather than merely acted on.

### Two scores that must not be conflated

- **The match score** (slice 004) answers *how well does my profile fit this job*, read before
  applying.
- **A tailoring confidence score** answers *how sound is this draft*, read after drafting. It is
  a quality judgement about generated text, not a fit judgement about a person.

They are different questions with different units and must never be shown as one number.

### Deliberately not here

**RAG and PDF export are slice 006**, and the boundary is structural rather than aspirational:
resume-writing guidance reaches the workflow through a replaceable source, which here is a static
rubric and in 006 is semantic retrieval over a guideline library. Slice 006 upgrades this agent's knowledge source; it
does not redesign the agent. No node, edge, state field, or approval rule changes when retrieval
arrives.

`docs/05` §5.4 as originally written was six subsystems in one slice. It has been split, and
`docs/05` amended, rather than quietly contradicted here.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn a job into a tailored resume I approved (Priority: P1)

A person opens a job they have already scored and asks for a tailored resume. A few tens of
seconds later they are shown what the agent proposes: which experiences and skills it kept, in
what order, and how it reworded them. They accept or reject each proposal and confirm. What they
approved becomes a saved version of their resume for that job; what they rejected keeps their own
wording.

**Why this priority**: This is the entire capability, and the smallest version of it that
delivers value. Everything else refines how confidently a person can make those accept/reject
decisions.

**Independent Test**: Open a scored job, request tailoring, wait for the draft, accept everything,
confirm. A saved version exists that differs from the master resume in ways the person saw before
agreeing to them. Delivers a tailored resume on its own.

**Acceptance Scenarios**:

1. **Given** a job with a completed, current match analysis and an approved profile, **When** the
   owner requests tailoring, **Then** the request returns immediately and the version reports that
   work is in progress.
2. **Given** a tailoring run has finished, **When** the owner opens the version, **Then** every
   proposed change is shown with the original wording beside the proposed wording.
3. **Given** a draft is shown, **When** the owner rejects a proposal and confirms, **Then** the
   saved version contains the owner's original wording for that item and the proposal is recorded
   as rejected.
4. **Given** a draft is shown, **When** the owner confirms without touching anything, **Then**
   every proposal not explicitly rejected is included.
5. **Given** the owner has confirmed, **When** the version is reopened, **Then** it reports that it
   was approved by the owner and still permits further editing.
6. **Given** a job with no completed match analysis, or one computed against an older profile,
   **When** the owner requests tailoring, **Then** the system refuses and tells them to run or
   re-run the match first.

---

### User Story 2 - See what the Reviewer thought, beside the thing it thought about (Priority: P2)

The person reading a diff has no way to tell a faithful rewording from an inflated one by
eye — that is precisely the judgement they lack time for. Each proposal therefore carries the
Reviewer's finding about *that* proposal, and the draft as a whole carries a confidence score.

**Why this priority**: It converts approval from rubber-stamping into judgement. Without it the
owner is asked to guarantee something they cannot check, which is the failure mode
human-in-the-loop is meant to prevent rather than create. It is P2 only because a draft that has
already had its fabrications removed is safe to approve without it.

**Independent Test**: Run tailoring on a profile whose evidence for one requirement is thin,
confirm the resulting draft carries a finding attached to the specific item, and confirm the
overall confidence score is visible and distinguishable from the match score.

**Acceptance Scenarios**:

1. **Given** the Reviewer raised a concern about one proposal, **When** the owner views the diff,
   **Then** that concern is displayed with that proposal and not as a general warning.
2. **Given** a draft cleared the Reviewer with no concerns, **When** the owner views the diff,
   **Then** the confidence score is still shown, so a clean result is visibly a result.
3. **Given** the Reviewer found a claim unsupported by the profile, **When** the owner views the
   diff, **Then** no such claim appears anywhere in the draft, and the item shows the owner's
   original wording.
4. **Given** a version has a confidence score and its job has a match score, **When** both are on
   screen, **Then** they are labelled distinctly and are not presentable as the same measurement.

---

### User Story 3 - Fix the wording myself (Priority: P3)

A rejected proposal restores the person's own wording, but sometimes their wording was not right
either — the agent was wrong about *how* to say it, not about *whether* to say it. They correct
the text by hand.

**Why this priority**: It closes the loop for the common case where neither version is right,
without a second agent round trip. It is last because rejection alone already produces a correct,
honest resume.

**Independent Test**: Reject a proposal, edit the restored text, confirm, and verify the saved
version contains the hand-written text marked as the owner's own.

**Acceptance Scenarios**:

1. **Given** a proposal has been rejected, **When** the owner edits the restored text and confirms,
   **Then** the saved version contains their text.
2. **Given** the owner has hand-edited an item, **When** the version is reopened, **Then** that
   item is identifiable as owner-authored rather than agent-proposed or master-original.

---

### Edge Cases

- **The Reviewer never clears the draft.** Bounded revision attempts are exhausted and concerns
  remain. Fabricated claims are removed regardless; the rest is shown to the owner, flagged, and
  left to their judgement.
- **Every proposal is rejected.** The version equals the master resume. This is a valid outcome
  and must save without error.
- **A run stops without finishing** — process restart, provider outage, timeout. The version must
  not sit in progress forever, and the owner must be able to try again.
- **A second tailoring request arrives while one is running** for the same job.
- **The profile is edited while a run is in flight.** The draft was built against a profile state
  that no longer exists.
- **The profile has nothing relevant** — no experience matching any requirement. The agent must
  produce an honest thin resume rather than inventing filler.
- **The match analysis becomes stale between the precondition check and the run starting.**
- **A proposal rewrites an item the owner had already corrected by hand in their profile.**
- **The provider returns output that fails validation** at any node.
- **The owner opens the diff while the run is still in progress.**

## Requirements *(mandatory)*

### Preconditions and run lifecycle

- **FR-001**: The system MUST refuse to start tailoring for a job that has no **completed** match
  analysis, or whose analysis was computed against an **older state of the profile**, and MUST say
  which of the two is the reason.
- **FR-002**: Requesting tailoring MUST return without waiting for the work; the work MUST run in
  the background and its progress MUST be observable.
- **FR-003**: A resume version and its run record MUST both be created before the background work
  starts, in the same transaction as each other, and the request MUST return the identifier of the
  **version**.
- **FR-004**: The system MUST allow at most one tailoring run in flight per job, enforced so that
  two simultaneous requests cannot both start.
- **FR-005**: A run that stops without finishing MUST be detectable and MUST be recoverable by the
  owner without manual database intervention.
- **FR-006**: A run that fails MUST leave the version readable and MUST record why it failed.
- **FR-007**: A failed or abandoned run MUST NOT prevent a subsequent run for the same job.

### The workflow and the Reviewer

- **FR-008**: Tailoring MUST proceed as an ordered workflow of distinct steps: decide a strategy,
  draft against it, review the draft, and revise when review is not satisfied.
- **FR-009**: The strategy step MUST produce a **persisted, structured plan** — what to emphasise,
  what to de-emphasise, and which gaps must not be misrepresented — and the drafting step MUST work
  from that plan rather than deriving its own strategy.
- **FR-010**: The plan MUST take the existing match analysis as input and MUST NOT recompute the
  fit assessment.
- **FR-011**: The system MUST NOT modify a match analysis during tailoring, under any outcome.
- **FR-012**: The review step MUST assess whether each claim traces to profile content, whether
  wording overstates what the profile supports, and whether the draft addresses the job's
  requirements, and MUST return a confidence score.
- **FR-013**: The revision loop MUST be bounded at **two revisions**, and the bound MUST NOT be
  extendable at run time.
- **FR-014**: Revision after a first failure MUST use a **stronger model** than the first attempt,
  so that a reviewer able to identify a problem is not repeatedly paired with a reviser unable to
  fix it.
- **FR-015**: Resume-writing guidance MUST reach the strategy and drafting steps through a
  replaceable source, so that changing where guidance comes from requires no change to the
  workflow's steps, ordering, or rules.
- **FR-016**: Each run MUST record the guidance it actually used, together with where that guidance
  came from.

### Honesty and grounding

- **FR-017**: The system MUST NOT assert experience, skills, or qualifications the Professional
  Profile does not contain.
- **FR-018**: A proposed change the review step judges **unsupported by the profile** MUST be
  discarded **before the draft is saved**, leaving the owner's original wording, and MUST NOT be
  presented to the owner as a choice.
- **FR-019**: Concerns that are matters of degree — overstated wording, unaddressed requirements —
  MUST be preserved and shown to the owner rather than acted on automatically.
- **FR-020**: The rules distinguishing FR-018 from FR-019 MUST be **named and versioned**, and every
  run MUST record which version it was finalised under. Changing a rule MUST produce a new version
  rather than an edit.
- **FR-021**: Tailoring MUST NOT modify the Professional Profile or any other owner-owned data.
- **FR-022**: Every tailored version MUST be presented as AI-generated, showing the model or models
  that produced it.

### Approval

- **FR-023**: No proposed change may enter a saved version without the owner's approval.
- **FR-024**: Approval MUST be available **per item**, not only for the draft as a whole.
- **FR-025**: A draft the owner confirms without touching MUST include every proposal not
  explicitly rejected.
- **FR-026**: Rejecting a proposal MUST restore the owner's original wording for that item and MUST
  NOT trigger further AI work.
- **FR-027**: The owner MUST be able to replace an item's text by hand, and such text MUST be
  distinguishable from both the agent's proposal and the master's original.
- **FR-028**: Approval MUST move the version to an approved state and MUST start no further
  automated work.
- **FR-029**: An approved version MUST remain editable.

### Versions and history

- **FR-030**: Every version MUST record which master resume it was created from, and the state of
  that master at creation time.
- **FR-031**: A version MUST NOT change when the Professional Profile or its source master changes
  afterwards.
- **FR-032**: A version MUST record which job it was tailored for.
- **FR-033**: A version MUST record which items are included and in what order, and excluding an
  item from a version MUST NOT remove it from the Professional Profile.
- **FR-034**: Each version MUST reference the run that produced it, and each run MUST be
  retrievable for inspection after the fact.

### Audit and model configuration

- **FR-035**: Every run MUST record, for each step, the model used, input and output token counts,
  and cost — written in the same transaction as the work it paid for.
- **FR-036**: The model for each step MUST be configured explicitly by step name. Relying on a
  default MUST be treated as a defect, because the default is the most expensive model.
- **FR-037**: Every AI output MUST be validated against a declared schema before use; unvalidated
  text MUST NOT reach business logic.
- **FR-038**: No step of the workflow may reach a provider except through the established
  completion seam, and this MUST be enforced automatically rather than by convention.

### Interface

- **FR-039**: The system MUST render the states of a version distinctly and MUST NOT conflate them:
  not yet tailored, tailoring in progress, **awaiting the owner's approval**, approved, and failed.
- **FR-040**: "The agent is still reviewing" MUST be distinguishable from "the agent has finished
  and it is your turn".
- **FR-041**: Each proposal MUST show the original and the proposed text together.
- **FR-042**: A Reviewer concern MUST be displayed against the proposal it concerns.
- **FR-043**: The confidence score and the job's match score MUST be labelled distinctly and MUST
  NOT be presented as the same measurement.
- **FR-044**: A run in progress or failed MUST NOT prevent the owner from opening or working with
  the job record or their profile.

### Verification

- **FR-045**: No automated test may make a live AI provider call.
- **FR-046**: FR-018 MUST have an explicit test asserting that an unsupported claim is absent from
  what is saved — and that test MUST be watched failing before it is trusted.
- **FR-047**: Every state transition MUST be exercised against a record **re-read from storage**,
  not one still held in memory from its own creation.
- **FR-048**: Every stored value on a version, item, finding, and run MUST be asserted to reach the
  owner-facing interface.

### Key Entities

- **Resume Version**: One tailored resume for one job. Records its source master and that master's
  state at creation, which items are included and in what order, its lifecycle state, and the run
  that produced it. Independent of its source after creation.
- **Tailoring Run**: One execution of the workflow. Records the plan, the number of attempts, the
  guidance used and its sources, per-step model and cost, the finalisation rules version, and the
  failure reason when there is one.
- **Version Item**: One item in a tailored version — the source item it derives from, the original
  text, the proposed text, the owner's decision, and the final text.
- **Reviewer Finding**: One concern about one item: what kind, how severe, and the Reviewer's own
  words.
- **Tailoring Plan**: The strategy the draft is written against — emphasis, de-emphasis, and the
  gaps that must not be misrepresented.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person who asks for a tailored resume is shown a draft to approve within **90
  seconds** when the draft passes review on the first attempt, and within **3 minutes** when the
  full revision budget is spent — or is told the run failed. At no point is the state unreported.
- **SC-002**: **100%** of statements in an approved version can be traced to content that existed
  in the Professional Profile before the run started.
- **SC-003**: A person can decide on a single proposed change in under **15 seconds**, having been
  shown the original, the proposal, and any concern about it.
- **SC-004**: A person shown a version can correctly state which of the five states it is in —
  including telling *the agent is working* from *it is your turn* — without asking.
- **SC-005**: Rejecting every proposal produces a saved version identical in content to the master
  resume, with no error.
- **SC-006**: A tailoring run costs no more than **$0.30**, measured on a real job rather than
  estimated.
- **SC-007**: Every saved version can state which criteria produced it and which profile state it
  came from, so two versions are never silently incomparable.
- **SC-008**: A run that stops without finishing is recoverable by the owner within **one hour**
  and without database access.
- **SC-009**: A person can explain why a specific bullet was reworded, from what the interface
  shows, without reading logs.

## Resolved Decisions

Settled during design. Recorded so they are not re-litigated in planning.

| Question | Decision | Why |
|---|---|---|
| What may the agent change? | Selection, ordering, **and** wording | The domain model already carries an item inclusion set, section order, and per-version titles. Selection alone cannot fabricate, but leaves the Reviewer nothing to check. |
| Does rejection re-prompt the agent? | No — it restores the original, and the text is editable by hand | A second loop outside the Reviewer's control, with cost and latency per rejected item, to solve what a text field solves |
| Is the Reviewer visible? | Findings per item, plus one confidence score | A finding beside the item it concerns is what makes approval a judgement rather than a formality |
| What if the Reviewer never clears the draft? | Split by severity — fabrications dropped silently, matters of degree shown flagged | Principle III is enforced by the system; Principle II governs everything else |
| Does the plan re-analyse the job? | No — it consumes the match analysis and produces a tailoring strategy | Two different questions: *how well does this fit* versus *how should this be tailored* |
| What if there is no fresh match analysis? | Refuse | A plan built on a stale assessment cites evidence that no longer exists, and the Reviewer then rejects claims that were grounded when analysed |
| When is the version created? | Synchronously, before the run starts; the request returns its id | The lifecycle makes tailoring a transition *out of* an existing draft, and status lives on the version, so it is what the client polls |
| Does approval resume any workflow? | No | Nothing runs after approval in this slice |
| Where does persistence happen? | In the application layer, never inside a workflow step | Workflow steps take state and return state; the layer that owns transactions owns the writes |

## Assumptions

- The owner has an approved Professional Profile with at least one work experience. Tailoring an
  empty profile is not a scenario worth designing for.
- The master resume created at import approval is the source for tailoring. Selecting among several
  masters is not part of this slice.
- One job is tailored for at a time. Bulk tailoring across many jobs is not in scope.
- Cover letters are not in scope.
- The static rubric standing in for retrieved guidance is written once and is not owner-editable.
- A version is tailored for the job that was recorded; changing the job description afterwards does
  not retroactively alter a version, consistent with lineage being recorded rather than inherited.
- Latency and cost targets assume the deployed provider configuration, not a local model.

## Out of Scope

Deliberately excluded, each with a reason recorded elsewhere.

- **Retrieval over resume-writing guidelines** — slice 006. A static rubric stands in, behind a
  replaceable source (FR-015).
- **PDF export, the ATS-safe template, and the exported and submitted states** — slice 006.
- **A submitted, locked resume record** — slice 006, where export makes it meaningful.
- **A full editing surface for resumes.** Per-item text replacement is in scope (FR-027); a
  document editor is an explicit project non-goal.
- **Re-prompting the agent from a rejection**, and any second loop the Reviewer does not govern.
- **Evaluation, benchmarking, and calibration of the confidence threshold** — slice 007. The
  threshold's first value is an uncalibrated constant, and it is versioned so that it can be
  changed honestly later.
- **Comparing a tailored version's match against the original profile's match** — designed but
  held back, because it depends on a distinction between presentation gaps and real ones that has
  never been validated.
- **Multiple master resumes**, and selecting among them.
