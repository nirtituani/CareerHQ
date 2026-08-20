# Feature Specification: Match Analysis

**Feature Branch**: `004-match-analysis`

**Created**: 2026-08-18

**Status**: Draft

**Input**: The approved design at [docs/superpowers/specs/2026-08-17-match-analysis-design.md](../../docs/superpowers/specs/2026-08-17-match-analysis-design.md) — score a recorded job against the user's approved Professional Profile, persist the result with a named criteria version, and show why it fits and what is missing.

## Why This Slice Exists

A person with forty recorded jobs and one profile has a question the system cannot yet answer:
**which of these is worth my afternoon?** Everything slice 003 built — a reviewed profile, a job
record holding its description — exists so that question becomes answerable.

It also answers the second half: *where am I weak?* That is the input a person needs **before**
tailoring, not after. Tailoring a resume for a role missing three must-haves is effort spent in
the wrong place.

### This is not the tailoring agent

`docs/05` §5.4 defines slice 004 as the Resume Tailoring Agent. **Match analysis has been pulled
out ahead of it as its own slice**, because it is independently valuable, independently
shippable, and needs none of the tailoring agent's machinery — no multi-step workflow, no
retrieval, no Reviewer, no version lineage. `docs/05` must be amended to record the split rather
than quietly contradicted here.

The scope guard from slice 003 still holds and is tightened here: **this slice adds no agent
loop, no embeddings, and no vector retrieval.** It is one structured call through the existing
seam. Anything needing planning, tools, or self-critique belongs to the tailoring agent.

### Two measurements that must not be conflated

- **This score** answers *how well does my profile fit this job* — read before applying.
- **A tailoring score** answers *how well does this tailored resume match* — read after drafting,
  and it belongs with tailoring.
- **`imported_match_rating`** is the person's own 1–5 judgement carried from JobTracker. It is
  never overwritten. What the person thought and what the system computed are two facts; one
  field for both would drift exactly as the source app's `rejected` flag drifted from its status.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Learn whether a job is worth pursuing, without asking (Priority: P1)

A person adds a job. Without doing anything further, a match band appears against it in their
applications list a few seconds later. Scanning the list, they can tell a *strong* from a
*low probability* at a glance and decide where to spend the evening.

**Why this priority**: This is the whole capability's reason to exist, and it is the smallest
thing that delivers it. A score with no breakdown is still useful; a breakdown with no score is
not scannable. Everything else refines this.

**Independent Test**: Add a job with a description, wait, and confirm a score appears in the
applications table without any further interaction. Delivers the "which of these is worth my
afternoon" answer on its own.

**Acceptance Scenarios**:

1. **Given** an approved profile and a job saved with a description, **When** the job is saved,
   **Then** saving returns immediately and a match band appears against that job within seconds.
2. **Given** an analysis is still running, **When** the person looks at the applications table,
   **Then** that job shows a pending indicator, distinct from both a score and a failure.
3. **Given** a job saved with no description and no requirements, **When** the person views it,
   **Then** it reads as *nothing to score against yet* — muted, and **not** as an error.
4. **Given** the analysis call fails, **When** the person views the job, **Then** the failure is
   stated with its reason, the job record is still fully usable, and no score is shown.
5. **Given** a job carrying an imported 1–5 rating from JobTracker, **When** an analysis
   completes, **Then** the imported rating is unchanged and both values remain visible as
   separate facts.

---

### User Story 2 - See why it fits and what is missing (Priority: P2)

The person opens the job and reads the reasoning: a one-sentence verdict, the requirements they
meet with the profile text that proves each one, and the requirements they do not meet with
must-haves called out ahead of nice-to-haves.

**Why this priority**: The score alone says *whether*; this says *why*, which is what makes the
number trustworthy and what turns it into an action. It depends on US1 having produced an
analysis, so it follows.

**Independent Test**: Open a job with a completed analysis and confirm every met requirement
shows supporting profile text, and missing must-haves are distinguishable from missing
preferences.

**Acceptance Scenarios**:

1. **Given** a completed analysis, **When** the person opens the job's Match view, **Then** they
   see the score, a one-sentence verdict, the requirements met with evidence, and the
   requirements missing.
2. **Given** a requirement judged confirmed, partial or transferable, **When** the person
   inspects it, **Then** it shows supporting text drawn from their own profile.
3. **Given** a requirement the profile falls short of, **When** the person inspects it, **Then**
   it is shown as a gap **with the profile text that demonstrates the shortfall**, and is
   presented as ordinary rather than as a failure.
3a. **Given** a requirement the profile says nothing about, **When** the person inspects it,
   **Then** it reads as *unverified* — not as a gap — and carries no supporting text.
3b. **Given** a requirement met by adjacent experience, **When** the person inspects it, **Then**
   it is labelled transferable and is visually distinct from a confirmed match.
4. **Given** an analysis with many missing requirements, **When** the person views the list,
   **Then** the presentation does not read as an error state, and each verdict is
   distinguishable without relying on colour alone.
5. **Given** any completed analysis, **When** the person views it, **Then** it is visibly
   AI-generated and shows which model produced it and what it cost.

---

### User Story 3 - Trust a score that has gone stale (Priority: P3)

The person corrects their profile — adds a role, fixes a skill. Scores computed before that edit
no longer reflect who they are. Opening such a job tells them so and offers to score it again.

**Why this priority**: It protects the credibility of US1's number over time, but a first version
is useful without it. It is also the requirement that keeps re-scoring under the person's control
rather than silently expensive.

**Independent Test**: Complete an analysis, edit the profile, reopen the job, and confirm the
staleness is surfaced and a re-run can be triggered by hand.

**Acceptance Scenarios**:

1. **Given** a completed analysis and a profile edited afterwards, **When** the person opens the
   job, **Then** they are told the profile has changed since scoring and offered a re-run.
2. **Given** the person triggers a re-run, **When** it is running, **Then** the previously
   computed score remains visible rather than blanking out.
3. **Given** a re-run that fails, **When** the person views the job, **Then** the last good score
   is still shown and the failure is reported alongside it.
4. **Given** a re-run that succeeds, **When** it completes, **Then** the new score is displayed
   and the previous analysis is still retained.
5. **Given** a profile edit affecting a hundred recorded jobs, **When** the edit is saved,
   **Then** no automatic re-scoring occurs.

---

### Edge Cases

- **A job with a description but no extractable requirements** — treated as *nothing to score
  against*, not as a failure and not as a zero.
- **An empty or near-empty profile** — the analysis must not report every requirement as missing
  with confident evidence; with nothing to match against, there is nothing to score.
- **A posting in a language other than the profile's** — scored on meaning, not string overlap.
- **A re-run racing a first run** — only one analysis may be in flight per job at a time.
- **An analysis that completes after the job is deleted** — the result is discarded without error.
- **A posting whose requirements are duplicated or near-duplicated** — the coverage count must not
  be inflated by the same requirement stated twice.
- **A requirement the profile partially satisfies** (three years' experience against a five-year
  ask) — must be expressible as partial rather than forced to met or missing.
- **A very long posting** — must not be silently truncated in a way that drops requirements from
  the second half.

## Requirements *(mandatory)*

### Functional Requirements

**Producing an analysis**

- **FR-001**: The system MUST score a recorded job against the owner's approved Professional
  Profile, producing an overall score from 0–100, a qualitative band, and a one-sentence verdict.
- **FR-001a**: The **band** is what the person is shown — *strong*, *moderate*, *stretch*, or
  *low probability*. The numeric score is retained for sorting and for calibration over history,
  but MUST NOT be presented as a bare percentage, which implies a precision the method does not
  have.
- **FR-002**: The system MUST score against the **whole posting text**, not only an extracted
  requirements list, so that signals stated outside a requirements section still count.
- **FR-003**: The system MUST store the full posting text and the extracted requirement list as
  two distinct pieces of data, each retrievable independently.
- **FR-004**: Saving a job MUST return without waiting for the analysis; the analysis MUST run in
  the background.
- **FR-005**: An analysis record MUST be created in the same transaction as the job it belongs
  to, so a running analysis and a failed one each have somewhere to be recorded.
- **FR-006**: The system MUST NOT begin an analysis for a job with no requirements to score
  against.
- **FR-007**: The system MUST allow at most one analysis in flight per job.

**Grounding and honesty (Principle III, AI-008)**

- **FR-008**: **Every verdict except *unverified* MUST carry evidence quoted from the owner's
  profile** — including negative verdicts. An analysis returning any other verdict without
  evidence MUST be rejected rather than shown.
- **FR-009**: The system MUST NOT assert experience, skills, or qualifications the profile does
  not contain — **and MUST NOT assert their absence either.** A profile that is silent about a
  requirement supports neither claim; that case is *unverified*.
- **FR-010**: Every analysis MUST be presented as AI-generated, showing the model that produced
  it and its cost.
- **FR-011**: Each requirement MUST record whether it is a **must-have** or a **preference**, and
  one of five verdicts:

  | verdict | meaning | evidence |
  |---|---|---|
  | `confirmed` | the profile directly shows it | required |
  | `partial` | the profile shows some of it — three years against a five-year ask | required |
  | `transferable` | the profile shows the same capability in another context | required |
  | `gap` | the profile shows the person falls short | **required** — quote the shortfall |
  | `unverified` | the profile says nothing either way | **must be absent** |

- **FR-011a**: A `gap` MUST be distinguishable from an `unverified`, and the system MUST NOT
  present the second as the first. *Not mentioned* is not *does not have*.
- **FR-011b**: `transferable` MUST NOT be presented as equivalent to `confirmed`. Adjacent
  experience shown as direct experience is the same fabrication FR-009 forbids, one step removed.
- **FR-011c**: Each requirement that is not met MUST record whether the shortfall is one of
  **wording**, **evidence**, or **capability** — because the action differs: rephrase, supply
  proof, or acknowledge it.

**Ownership and history (Principles I, II, IV)**

- **FR-012**: The analysis MUST NOT modify the Professional Profile or any user-owned
  professional data. It observes only.
- **FR-013**: The system MUST NOT overwrite a job's imported user rating.
- **FR-014**: Analyses MUST be append-only; a new analysis MUST NOT destroy or overwrite a
  previous one.
- **FR-015**: Each job MUST identify which analysis is currently displayed, and that pointer MUST
  advance only when a new analysis completes successfully — so a running or failed re-run leaves
  the last good score standing.
- **FR-016**: Requirements MUST be stored as individually queryable records, not as an opaque
  blob, so that later work can count how often a skill is required and separate critical gaps
  from nice-to-haves.

**Auditability and cost (Principle V)**

- **FR-017**: Every analysis MUST record the model used, input and output token counts, cost, and
  whether it came from a fixture — written in the same transaction as the result.
- **FR-018**: Every analysis MUST record the version of the scoring criteria that produced it, so
  scores from different criteria are never compared as if equivalent.
- **FR-019**: The model for this task MUST be configured explicitly by task name. Relying on the
  default would run it at roughly 2.5× the cost with no quality gain.
- **FR-020**: The analysis MUST be produced by a single structured call whose output is validated
  against a schema before use. **No agent loop, no self-critique, no tool use, no embeddings, and
  no vector retrieval.**

**Presentation**

- **FR-021**: The applications list MUST show each job's **band**, and the job record MUST offer
  a dedicated view holding the verdict, the requirements the profile supports with their evidence,
  the requirements it does not with must-haves first, and a coverage count.
- **FR-022**: The interface MUST render four states distinctly and MUST NOT conflate them:
  *running*, *scored*, *failed*, and *nothing to score against*.
- **FR-023**: A gap or unverified requirement MUST NOT be presented in the visual language
  reserved for failures. All five verdicts MUST remain distinguishable without colour.
- **FR-024**: The owner MUST be able to trigger a re-run by hand.
- **FR-025**: Where the profile has changed since a job was scored, the system MUST surface that
  the score is stale and offer a re-run. It MUST NOT re-score automatically.
- **FR-026**: A failed analysis MUST leave the job record fully readable and usable.

**Testing**

- **FR-027**: No automated test may make a live AI provider call; the completion seam MUST be
  overridable in tests.
- **FR-028**: The grounding rule in FR-008 MUST have an explicit test asserting that an
  evidence-free *met* verdict is rejected.
- **FR-029**: Every stored analysis and requirement value MUST be asserted to reach the person
  viewing it, in the manner of the slice 003 test that reads the stored columns directly — a
  fixture cannot catch a dropped field.

### Key Entities

- **Match Analysis**: One scoring run for one job. Holds its state (running, scored, failed), the
  overall score, the one-sentence verdict, the criteria version, the model and usage metadata, and
  when it started and finished. Append-only.
- **Match Requirement**: One requirement drawn from the posting, belonging to one analysis. Holds
  its text, its ordinal position, whether it is a must-have or a preference, the verdict, and the
  supporting profile evidence where one exists.
- **Application** (existing, extended): Gains a distinct requirements field, has its description
  field returned to meaning the full posting, and identifies its currently displayed analysis.
- **Professional Profile** (existing, read-only here): The thing being scored against. Never
  written by this feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person who adds a job sees a score against it within 20 seconds, without taking
  any further action.
- **SC-002**: 100% of verdicts other than *unverified* carry supporting text that can be located
  in the person's own profile. Zero verdicts assert experience the profile does not contain, and
  **zero assert an absence the profile does not demonstrate**.
- **SC-003**: A person shown the four states can tell *not scored yet*, *scored*, *failed*, and
  *nothing to score against* apart, in greyscale — as can they the five requirement verdicts.
- **SC-004**: Scoring one job costs no more than $0.03, and a hundred jobs no more than $3.
  **Not met as measured — $0.0355 and $0.0715** on two real jobs (T075), the second 2.4x the
  target. Output scales with the *length of the posting*, not the requirement count. The target
  was set from a projection assuming three verdicts and no `importance` or `shortfall` field;
  v2 has five verdicts and both, and output nearly doubled. Options are in research.md R8;
  none has been applied, because each trades away something the feature exists for.
- **SC-005**: A failed or running analysis never prevents a person from opening, editing, or
  progressing the job record — measured as zero blocked interactions.
- **SC-006**: After a re-run fails, the previously displayed score is still shown. No score is
  ever lost to a failed re-run.
- **SC-007**: Every stored analysis can state which criteria version produced it, so no two
  scores from different criteria are compared as equivalent.
- **SC-008**: A person can answer *what am I missing for this job* in under 30 seconds of opening
  the record.

## Resolved Decisions

Carried from the approved design so they are not re-derived. Each was decided, not assumed.

- **Scored against the whole posting, not the requirements list.** Requirements-only was tried
  first and reversed: *"design and operate services handling millions of requests per day"*
  appears in no requirements section but is exactly what makes a production backend history
  relevant. Both are stored; they serve different readers.
- **Not an agent.** This is profile + posting → one structured judgement. No loop, no tools,
  nothing to critique. An agent runtime would add retries and state to something that runs once.
- **Not retrieval.** A profile measures ~760 tokens and a posting 2,400–4,500 — the entire corpus
  fits in the prompt many times over. More decisively, the feature's central question is *which
  requirements do I lack*, which can only be answered by seeing the **entire** profile. A
  retrieval miss would invent a gap, silently, and that is the most damaging error this feature
  can make.
- **Requirements as rows, not a blob**, because counting how often a skill is required is a
  grouping query over rows and is unqueryable as JSON — it would have to be re-extracted from
  analyses already paid for.
- **Every job is scored on add**, whether or not it is ever opened. A split of quick-score then
  detail was rejected: both read the same input, so it saves nothing on the expensive half and
  produces two independently generated numbers that can disagree on one screen.
- **Run in the background rather than through a queue.** No queue is currently deployed, and
  standing one up for a task of this length is more infrastructure than the feature warrants.
- **Re-running is manual.** Silently re-scoring a hundred jobs because a typo was fixed would be
  expensive and surprising.
- **Model chosen by task name**, per docs/08 §3.2.3's assignment of *analyze*, so it can move to a
  cheaper model by configuration rather than a code change.

### Decisions driven by the two supplied sources

Two external skills were supplied as rubric input:
[`varunr89/resume-tailoring-skill`](https://github.com/varunr89/resume-tailoring-skill) (MIT) and
[`shahar84/shahar-polaks-career-studio`](https://github.com/shahar84/shahar-polaks-career-studio).
They disagreed with each other, and resolving that disagreement changed three things.

- **Five verdicts, not three.** The taxonomy separates *transferable* from *confirmed*, and
  *unverified* from *gap*. The second separation fixes a real defect in the original
  specification: it collapsed "your profile does not mention this" into "you do not have this",
  which asserts a negative fact about the person that the profile does not support. Principle III
  and AI-008 forbid inventing experience; inventing its absence is the same error pointed the
  other way, and the first draft did not catch it.
- **A band is displayed, a number is stored.** One source argues against fit percentages as
  false precision; the other supplies a weighted numeric rubric. Both are right about different
  things — a bare *84%* overstates the method, but *something* must be sortable across forty jobs
  and comparable across time for the calibration docs/07 §3.2 requires. So the score is retained
  and the band is shown.
- **Gaps are classified as wording, evidence, or capability**, because the action differs:
  rephrase what is already there, supply proof, or acknowledge the gap honestly. A gap list that
  does not say which is a list of problems with no next step.

**On the numeric rubric's shape**: the weighted dimensions (direct, transferable, adjacent,
impact) were designed to score *one experience against one template slot*. Here the unit is a
whole profile against a whole posting, so the weights are adapted rather than copied, and v1
records that it is an adaptation.

## Assumptions

- **The scoring rubric now exists and ships as `criteria_version` v1.** It is adapted from two
  supplied sources (see Resolved Decisions) rather than being the model's own unnamed judgement.
  The uncalibrated `v0` state the design planned for was never entered — but FR-018 still governs,
  because a v2 rubric must remain distinguishable from this one.
- **No canonical skill vocabulary in the first version.** Requirements are scored as written.
  Collapsing "K8s", "Kubernetes" and "container orchestration" into one requirement is a later
  refinement; whether it is needed will be visible from real analyses.
- **The model assignment is not revisited on speculation.** A cheaper model may well suffice, but
  the seam raises rather than accepting partial data, so a weaker model trades cost for extraction
  failures. That trade is decided by a measured comparison once real analyses exist.
- **Slice 003's User Story 3 (JobTracker import) is not a dependency.** This needs a profile and a
  job with a description, both of which exist.
- **The profile is the approved one.** Facts still awaiting review are not scored against.
- **Cost figures assume the introductory pricing in force until 31 August 2026**; the same volume
  costs roughly 50% more afterwards.

## Out of Scope

- **Tailoring, drafting, or revising a resume.** That is the tailoring agent, and it brings the
  workflow, retrieval, and Reviewer this slice deliberately does not.
- **A tailoring quality score** — *how well does this tailored resume match* — which shares a
  schema with this one so the two stay comparable, but is produced elsewhere and read elsewhere.
- **Retrieval over resume-writing guidelines.** Retrieval belongs over external knowledge, never
  over the user's own data.
- **Automatic re-scoring** when the profile changes (FR-025).
- **Cross-job analytics** — "which skill do I lack most often" — which the row-level storage in
  FR-016 exists to make possible later, in the Career Advisor.
- **Acting on the score**: no filtering, sorting, ranking, or archiving driven by it in this
  slice.
- **Reducing output cost** by returning references instead of quoted evidence. The lever is
  identified and roughly halves output, but it is not needed yet and would complicate the
  grounding check that FR-008 makes structural.
