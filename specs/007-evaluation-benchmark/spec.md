# Feature Specification: Evaluation & Benchmark

**Feature Branch**: `007-evaluation-benchmark`

**Created**: 2026-08-29

**Status**: **Measured.** D1, D2 and D3 approved 2026-08-29; the paid pass ran the same day at
**$4.925403 of a $10 ceiling**. Results in [results/paid-benchmark.md](results/paid-benchmark.md).

**Input**: The evaluation harness for the tailoring agent: a fixed, versioned benchmark set of job
postings paired with profile states; metrics for grounding accuracy, requirement coverage,
retrieval quality, match-score calibration and LLM-as-judge scoring with a human-rated sample to
check the judge; regression runs so a prompt or model change is measured rather than assumed; and
a results view showing metrics over time.

> ### A naming hazard, stated once
>
> **Every slice numbers its own criteria from SC-001.** Slice 006 has an `SC-008` — retrieval's
> cost per run, ≤2%, currently **missed at 3.22%** — and this slice will have one too, meaning
> something entirely different. Throughout this document, slice 006's criteria are written
> **SC-008 (006)** and this slice's are written plain. Conflating them would be easy and the
> consequence — believing a threshold was met because a differently-numbered one was — is exactly
> the class of error this slice exists to prevent.

---

## Why This Slice Exists

### The measuring instrument is the deliverable

Every slice so far produced a capability. This one produces the ability to say **how well the
capability works** — the difference between *"I built an agent"* and *"I know how well my agent
works"*, which is the more interesting claim and the one the course grades
(`docs/reference/01_course_requirements.md`: *"Design evaluation + benchmark. Metrics + analytics
of success."*).

**It is graded and it has been deferred twice.** It was slice 005 in an earlier plan and moved
twice; `docs/05` §5.7 records that deferral as *"the most serious error in version 1.0 of this
plan"*, and states in as many words that if the budget runs short, **008 and 009 are what get
dropped — this is not**.

### The data has been laid down for four slices, deliberately, and almost nothing reads it

This slice is unusual in that most of its inputs already exist. Earlier slices wrote columns whose
stated justification was *this* slice:

| Already persisted | Written for |
|---|---|
| `tailoring_runs.plan` | Whether the draft executed the plan |
| `tailoring_runs.guidelines_used` — every guideline with its source and content hash | Retrieval quality. Slice 005 called it *"redundant while the source is a static rubric; the only thing that makes slice 007's retrieval-quality metric measurable once it is not"* |
| `tailoring_runs.review_confidences` — every pass, not just the last | Calibrating the confidence threshold |
| `tailoring_runs.model_config_used`, `finalisation_rules_version` | Making historical runs comparable and refusing to compare incomparable ones |
| `tailoring_run_calls` — per-call task, model, tokens, cost | Attributing cost to a node rather than to a run |
| `reviewer_findings` — `ungrounded` / `overstated` / `uncovered`, each quoting what it objects to | Grounding accuracy and requirement coverage |
| `match_requirements` as rows rather than a blob | Counting requirement frequency across analyses |
| `application/plan_adherence.py` | Explicitly: *"so that when slice 007 can judge it there is a distribution to judge rather than an anecdote"* |

**The harness is therefore mostly a reader, not a new pipeline.** That is the cheapest possible
shape for a slice this late in the budget, and it is not an accident — it is four slices of
deliberate preparation coming due.

### SC-008 (006) is the proof that this slice is needed

Slice 006 finished with a threshold it could measure but could not **resolve**. SC-008 (006)
divides a *fixed* per-run overhead — retrieval's ~3,754 extra input tokens — by a *total run cost
that varies 2.7× with whether the Reviewer triggered a revision*. Two paid re-measurements
demonstrated the failure mode from both directions: the numerator improved 21% and the reported
ratio got **worse**, 2.12% → 3.22% — **missed before the fix and still missed after it** — because
that session's baseline happened not to revise.

`research.md` R15 closes with the question left open on purpose:

> *"Whether SC-008 should be expressed against something less volatile than total run cost is a
> metric-definition question, deliberately left open."*

**That is an evaluation-methodology question, and this is the evaluation slice.** A single paired
run cannot resolve a 2% threshold through an 85% spread — which means the answer is not a better
measurement of one pair but a harness that controls for revision count, reports n, and reports
variance. **The ≤2% threshold is not changed by this slice** (see D1); what changes is whether
anything can be said about it with confidence.

### Two deferred changes are waiting for something to be judged against

- **T057** (slice 006, open, deferred by decision) — Education and Language items capture one
  field and drop the rest, so the exported PDF says *"Ben-Gurion University"* where the profile
  holds *"B.Sc. in Computer Science"*. The fix is small and measured at **+16 tokens, 1.07%** of
  the master block. It was deferred because **it changes what the model is sent**, and judging
  that needs an evaluation rather than a token count.
- **M-002** (slice 006, carried forward) — disabling thinking measured **8,707 → 3,448 completion
  tokens and 93.2s → 45.9s** on the real Draft prompt, with **quality impact not established**.
  Slice 006 recorded that this *"MUST NOT be turned into a configuration change without a quality
  measurement"*.

Both are blocked on the same missing thing. A harness that cannot judge either of them has not
delivered its purpose, whatever else it reports.

### Deliberately not here

Company Research (008) and the Career Advisor (009). Both are droppable by design; this is not.

---

## User Scenarios & Testing *(mandatory)*

The user throughout is **the evaluator** — one of the four roles the course requires, held here by
the same person as the engineer, which is precisely why the separation has to live in artifacts
rather than in people.

### User Story 1 - Run a fixed benchmark and get numbers that mean the same thing twice (Priority: P1)

The evaluator runs the whole benchmark with one command against a fixed, versioned set of cases.
When it finishes, every metric is reported alongside the number of cases it was computed over, the
cost it incurred, and the exact configuration it ran — model per task, guideline source,
finalisation rules version. Running it again on unchanged code produces a comparable result, and
the difference between the two runs is the measurement noise every later claim has to clear.

**Why this priority**: Nothing else in the slice exists without it. A metric with no fixed input
set is an anecdote, and the project already has thirteen of those. It is also the only story that
delivers value on its own: the moment a benchmark can be re-run, *"did that change help?"* stops
being a matter of opinion.

**Independent Test**: Run the benchmark twice with no change between runs, against canned model
responses so nothing is billed, and confirm that both runs produce the same set of cases, that
every reported metric names its `n`, and that the run record captures the configuration. The
canned arm proves the harness; it does not produce agent-quality numbers, and the harness must say
so (FR-030).

**Acceptance Scenarios**:

1. **Given** a versioned benchmark set, **When** the evaluator starts a benchmark run, **Then** the
   projected cost is reported *before* any billable work begins, and the run refuses to start if
   that projection exceeds the configured ceiling.
2. **Given** a completed benchmark run, **When** the evaluator reads its report, **Then** every
   metric carries the number of cases it was computed over, and a metric with zero cases is
   reported as *not measured* rather than as a value.
3. **Given** a benchmark run in which some cases failed, **When** the report is produced, **Then**
   the failures are counted and named, and the remaining metrics state that they exclude them.
4. **Given** a benchmark run that used canned model responses, a fallback to static guidelines, or
   a model mix other than the one that ships, **When** the evaluator asks for agent-quality
   metrics, **Then** the harness refuses and names which of those conditions applies.
5. **Given** two benchmark runs of the same version of the system, **When** they are compared,
   **Then** the report states the run-to-run variation per metric, so a later change can be judged
   against noise rather than against a single run.

---

### User Story 2 - Judge the quality of what the agent wrote, and check the judge (Priority: P2)

For each benchmark case the harness reports whether the tailored résumé stayed honest, how much of
the posting it addressed, whether the guidance retrieved for it was relevant, and how a model
judging against a written rubric scores it. Because a model grading a model is not evidence on its
own, the evaluator rates a sample by hand and the harness reports how well the judge agreed.

**Why this priority**: These are the metrics the course names and the ones `docs/08` §5.2 lists.
Grounding accuracy in particular is the Principle III release-blocker made measurable — slice 005
built a Reviewer that discards ungrounded claims before persistence, and nobody has yet counted
how often it fires or whether anything gets past it.

**Independent Test**: Compute grounding accuracy, requirement coverage and retrieval quality over
the **thirteen tailoring runs that already exist**, without any new model call. If those numbers
can be produced from persisted records alone, the metric definitions are sound before a single
benchmark case is billed.

**Acceptance Scenarios**:

1. **Given** a completed tailored version, **When** grounding accuracy is computed, **Then** it
   reports the proportion of proposed claims that trace to profile content, counts the claims the
   Reviewer classified `ungrounded`, and confirms that none of them reached a persisted proposal.
2. **Given** a job posting with a must-have requirement list, **When** requirement coverage is
   computed, **Then** must-have coverage is reported separately from overall coverage, because a
   résumé addressing every "nice to have" and no "must have" is not 50% good.
3. **Given** a run that retrieved guidance, **When** retrieval quality is computed, **Then** the
   proportion of retrieved guidelines judged relevant to that posting is reported, along with the
   proportion of the retrieved set that was pinned integrity guidance rather than selected.
4. **Given** a judge score for an output, **When** it is reported anywhere, **Then** it carries the
   judge's measured agreement with the human-rated sample, and a judge whose agreement has never
   been measured produces scores labelled unvalidated.
5. **Given** a set of completed match analyses with human ratings of the résumés produced from
   them, **When** calibration is computed, **Then** the report states whether higher match scores
   correspond to better-rated résumés, and states the sample size rather than implying one.

---

### User Story 3 - Tell me whether the change I just made helped (Priority: P3)

The evaluator changes a prompt, a model assignment, a retrieval parameter or a snapshot field,
re-runs the benchmark, and reads a single comparison: per metric, the before value, the after
value, the difference, and whether that difference exceeds the run-to-run variation established in
User Story 1. Results accumulate, so the trend across changes is visible rather than reconstructed.

**Why this priority**: It is the payoff, but it is worthless before the first two stories exist.
It is also the story that makes T057 and M-002 decidable — each is a change whose effect nobody
can currently judge.

**Independent Test**: Take a baseline, land T057 (a real, deliberately deferred change to what the
model is sent), re-run, and read the comparison. If the harness cannot say whether +16 tokens of
degree text helped, hurt, or did neither, it has not delivered User Story 3.

**Acceptance Scenarios**:

1. **Given** two benchmark runs on different versions of the system, **When** they are compared,
   **Then** each metric shows before, after, delta, and whether the delta exceeds measured noise.
2. **Given** two runs whose configuration differs in more than the thing under test — a different
   model mix, a different finalisation rules version, a different benchmark set version — **When**
   they are compared, **Then** the harness names every differing dimension rather than reporting a
   clean delta.
3. **Given** a history of benchmark runs, **When** the evaluator opens the results view, **Then**
   each metric is shown over time with the change that separated each pair of runs identified.

---

### Edge Cases

- **A benchmark case fails mid-run.** Counted, named, and excluded from every metric — with the
  exclusion stated. Slice 006 already established the rule the harness must follow here: filter on
  run `status`, never on the presence of `guidelines_used`, because a failed run can carry
  guidance it never used.
- **A metric has nothing to compute over.** Reported as *not measured*, never as `0`. The project
  already draws this distinction twice — `plan_adherence` returns `None` rather than `0.0`, and a
  posting with no requirements is *"nothing to score against, not a zero"*.
- **The judge is unavailable or its output fails validation.** The case is reported without a judge
  score; the run continues and says how many cases lack one.
- **The corpus changed between two runs.** Retrieval quality is not comparable across a corpus
  edit. The harness records what corpus each run retrieved against and refuses a silent comparison.
- **The benchmark is run against a database holding real evaluation evidence.** It must add rows
  and never modify or delete existing ones (§5A of `HANDOFF.md` — that evidence was paid for).
- **The projected cost exceeds the ceiling.** Refused before any billable call, naming the
  projection and the ceiling.
- **A pricing change lands between two runs.** Cost figures are not comparable across it. The
  harness records the pricing basis each run used and names the difference rather than reporting a
  pricing change as a regression — the trap SC-008 (006) already had to write a clause against.
- **A benchmark case's posting or profile has been edited since the last run.** The benchmark set
  is versioned; a run records the version, and a comparison across versions is refused or flagged.

---

## Requirements *(mandatory)*

### The benchmark set

- **FR-001**: The system MUST hold a **fixed benchmark set** of cases, each pairing a job posting
  with a profile state, so that results are comparable across runs.
- **FR-002**: The benchmark set MUST be **versioned**, and every benchmark run MUST record which
  version it ran. Editing a case is a new version, never an edit in place — the same rule the
  match criteria and the finalisation rules already follow, and for the same reason: otherwise
  every historical result silently becomes incomparable.
- **FR-003**: The benchmark set MUST span **at least three disciplines**, so that retrieval quality
  and requirement coverage are measured against variety rather than against one hiring market.
- **FR-004**: Each case MUST carry the posting content in a form the pipeline can consume through
  its ordinary path, so that a benchmark run exercises the shipping code and not a parallel one.
- **FR-005**: The benchmark set MUST be reproducible from version-controlled inputs — a run must
  not depend on rows a person seeded by hand.
- **FR-005a**: The committed benchmark set MUST be **fully synthetic** and MUST contain no real
  personal data, so that it can live in a public repository and be reproduced by anyone, including
  a grader (D2).
- **FR-005b**: The synthetic set MUST NOT be artificially easy. It MUST span multiple disciplines
  and multiple seniority levels, vary profile content across cases rather than reusing one profile,
  and include cases chosen to **exercise the behaviour under evaluation** — postings whose guidance
  needs differ, profiles with genuine gaps as well as genuine matches, and at least one case where
  the honest answer is that the profile does not cover a must-have. A benchmark on which the agent
  cannot fail measures nothing (D2).
- **FR-005c**: A **separate real-world set** MAY be used for a limited sanity check that the
  synthetic set does not flatter the system. It MUST be gitignored, MUST be excluded from CI, and
  MUST NOT enter the repository or the evaluation-evidence record without a further explicit
  decision. Only aggregate findings from it may be committed (D2).
- **FR-005d**: Any conclusion drawn from the real-world set MUST be labelled as coming from it, so
  that a reproducible figure and an unreproducible one are never presented as the same kind of
  evidence.

### Running a benchmark

- **FR-006**: The evaluator MUST be able to run the entire benchmark as a **single operation** and
  receive one report.
- **FR-007**: A benchmark run MUST record its configuration: model per task, guideline source,
  finalisation rules version, benchmark set version, corpus identity, and the pricing basis costs
  were computed with.
- **FR-008**: A benchmark run MUST **project its cost before starting** and MUST refuse to start
  when the projection exceeds a configured ceiling.
- **FR-009**: A benchmark run MUST report its **actual** cost and token usage on completion,
  itemised per case and per task, including for cases that failed.
- **FR-010**: A benchmark run MUST run **the model mix that ships**. Evaluating a configuration
  that is never deployed produces metrics describing a system nobody uses.
- **FR-011**: Benchmark runs MUST be **distinguishable from user runs** in the persisted record, so
  that neither population contaminates the other's statistics.
- **FR-012**: A benchmark run MUST NOT modify or delete any existing run, version, analysis,
  export or submission. It adds rows only.
- **FR-013**: A benchmark run MUST operate against a **non-real profile**, and MUST NOT read from
  or write to the owner's live Professional Profile.

### Metrics

- **FR-014**: The system MUST compute **grounding accuracy** — the proportion of claims in a
  tailored version that trace to existing profile content — and MUST report the count of claims
  the Reviewer classified `ungrounded` alongside it.
- **FR-015**: The system MUST verify, per run, that **no `ungrounded` claim reached a persisted
  proposal**. This is the Principle III release-blocker check; the severity split already enforces
  it structurally, and this is the measurement that would notice if it stopped.
- **FR-016**: The system MUST compute **requirement coverage** — how much of a posting's
  requirement list the tailored résumé addresses — and MUST report coverage of the **must-have**
  subset separately from overall coverage.
- **FR-017**: The system MUST compute **retrieval quality** — whether the guidance retrieved for a
  posting is relevant to it — and MUST report the selected and the always-pinned integrity portions
  separately, since the pinned portion is relevant by construction and would otherwise inflate the
  figure.
- **FR-018**: The system MUST compute **match-score calibration** — whether higher match scores
  correspond to better-rated résumés — and MUST report the sample it was computed over.
- **FR-019**: The system MUST compute **plan adherence** from the data every run already persists,
  and MUST report it as a distribution rather than a single figure, since that is what it was built
  to make possible.
- **FR-020**: Every reported metric MUST carry the **number of cases** it was computed over, and a
  metric with no cases MUST be reported as *not measured* rather than as a value.
- **FR-021**: Every reported metric MUST be traceable to persisted records. No figure may be
  computed from a value the system did not store.

### The judge, and checking the judge

- **FR-022**: The system MUST score tailored output with a **model judging against a written
  rubric**, producing a structured, validated result.
- **FR-023**: The judging rubric MUST be **version-controlled and versioned**, and every judge score
  MUST record which version produced it.
- **FR-024**: The evaluator MUST be able to record **human ratings** for a sample of benchmark
  outputs.
- **FR-025**: The system MUST report the **judge's agreement with the human-rated sample**, and any
  judge score shown or exported MUST carry that agreement figure. A judge whose agreement has never
  been measured produces scores labelled **unvalidated**.
- **FR-026**: The judge MUST NOT see which arm, version or configuration produced an output it is
  scoring.
- **FR-027**: The judge's own model calls MUST be audited like every other model call — task,
  model, tokens and cost preserved (Principle V).

### Cost and latency measurement

- **FR-028**: The system MUST measure **retrieval's cost overhead in a way that controls for
  revision count**, reporting the overhead, the denominator it was expressed against, the number of
  paired observations, and the variance — so that SC-008 (006) can be evaluated against evidence
  rather than against a single pair. **The ≤2% threshold of SC-008 (006) is not changed by this
  slice**; see D1 for what may be added alongside it.
- **FR-029**: The system MUST measure **per-node latency** for a tailoring run — the remaining half
  of M-001, which slice 006 explicitly carried forward. Per-call records currently carry tokens and
  cost but no timing, so per-node latency is derivable only from throughput assumptions.

### Integrity of the harness itself

- **FR-030**: The harness MUST **refuse to report agent-quality metrics** for any run that used
  canned model responses, fell back to static guidelines when retrieval was configured, or used a
  model mix other than the shipping one — and each refusal MUST name which condition applied.
  *A measurement that cannot refuse a mocked arm, an empty corpus or a fallback is a number with no
  claim attached.*
- **FR-031**: The harness MUST refuse to compare two runs whose configuration differs in more than
  the dimension under test, or MUST name every differing dimension in the comparison.
- **FR-032**: The paid part of a measurement MUST be **separable from the reporting part**, so that
  arithmetic can be re-checked and drilled without paying again — the pattern slice 006's
  measurement scripts already established.
- **FR-033**: Every metric definition MUST be **exercised by a test that has been watched failing**.
  A measurement harness gets the same drills as production code, and its assertions are where its
  claims live.

### Regression and the results view

- **FR-034**: The system MUST report, for two benchmark runs, each metric's **before, after, delta,
  and whether the delta exceeds measured run-to-run variation**.
- **FR-035**: The system MUST establish that run-to-run variation by comparing runs of an unchanged
  system, and MUST report it rather than assume it is zero.
- **FR-036**: Benchmark results MUST persist, so that metrics over time are read rather than
  reconstructed.
- **FR-037**: The evaluator MUST be able to see each metric **over time**, with the change that
  separated each pair of runs identified.

### Ownership, privacy and audit

- **FR-038**: Benchmark and judging operations MUST be reachable only by an authenticated owner;
  no endpoint may accept a client-supplied user or profile identifier.
- **FR-039**: No benchmark input committed to the repository may contain real personal data — this
  repository is public, and it has had two near-misses already.
- **FR-040**: Every model call the harness makes MUST flow through the existing structured
  completion seam; no evaluation code may reach a provider directly (Principle V).

### Key Entities

- **Benchmark Set** — a versioned collection of cases. Identified by a version that runs record.
- **Benchmark Case** — one posting paired with one profile state, plus whatever the metrics need to
  be judged against it (for example, its requirement list).
- **Benchmark Run** — one execution of a set against one configuration, at one time, with a cost.
  Holds the configuration fingerprint that makes two runs comparable or not.
- **Case Result** — one case's outcome within a run: the tailoring run it produced, its metric
  values, its failure if it failed.
- **Judge Score** — a model's rubric score for one output, carrying its rubric version.
- **Human Rating** — an evaluator's own rating of one output, the thing the judge is checked
  against.
- **Metric Definition** — a named, versioned way of computing one number, so that a change in
  methodology is visible rather than silent.

---

## Success Criteria *(mandatory)*

*Numbered for this slice. Slice 006's criteria are written **SC-008 (006)** and are different
things — see the note at the top of this document.*

### Measurable Outcomes

- **SC-001**: Running the benchmark twice against an unchanged system produces a stated
  **run-to-run variation for every metric**, and that variation is published before any change is
  judged against it.
- **SC-002**: **100%** of reported metrics name the number of cases they were computed over, and
  **0** metrics with no cases are reported as a value.
- **SC-003**: **100%** of reported figures trace to a persisted record. No metric is derived from a
  value the system did not store.
- **SC-004**: In **100%** of attempts, the harness refuses to report agent-quality metrics for a run
  that used canned responses, fell back to static guidance when retrieval was configured, or ran a
  model mix other than the shipping one — and **every refusal names which condition applied**.
- **SC-005**: **0** existing runs, versions, analyses, exports or submissions are modified or
  deleted by any benchmark run.
- **SC-006**: Across the full benchmark, **0** claims classified `ungrounded` reach a persisted
  proposal. *(The Principle III release-blocker check, measured rather than assumed.)*
  **MET — measured 2026-08-29 across all 23 paid arms. `persisted_ungrounded = 0` on every one.**
  Preserved as evidence: **2 ungrounded claims caught and discarded before persistence**, and
  **28 overstated claims flagged** to the owner. `traceable` is 1.0 on every arm. The two caught
  claims matter beyond the count — they mean the guardrail has fired on real model output rather
  than only in tests, so SC-006 now has something to be a regression test *of*.
- **SC-007**: The judge's agreement with a human-rated sample is **measured and reported**, using a
  rating protocol that states whether it collects absolute ratings or pairwise comparisons, and a
  sample size **justified rather than assumed** (D8; the plan owes the justification). Below the
  agreement level the plan sets, the judge's scores are reported as **unvalidated** and no
  conclusion in this slice rests on them.
- **SC-008**: **A new evaluation criterion, not a replacement for SC-008 (006).** Retrieval's cost
  overhead is reported from **5 paired observations** (D3, approved) — each pair run against the same case, in the same
  process and pricing window, so revision behaviour is controlled rather than averaged over — with
  the number of pairs, the denominator and the variance all stated. The reported interval **either
  resolves against a stated position or is reported as unresolved**, and reporting *unresolved* is
  a pass of this criterion.
  **What this criterion does not do, stated so it cannot be read the other way** (D1, approved
  2026-08-29): it does not change the ≤2% threshold, does not redefine or reinterpret SC-008 (006),
  does not supersede it, and does not declare it met. **SC-008 (006) remains recorded as MISSED at
  3.22%.** The purpose here is to evaluate the *methodology problem* T052 exposed — a fixed
  numerator over a denominator that varies 2.7× with revision count — not to make an existing miss
  disappear.
  **MEASURED 2026-08-29 — verdict `unresolved`, and that is a valid outcome of this criterion
  rather than a pass/fail claim about retrieval.**
  n = **5 pairs**; numerator **3,376.6 ± 225.8 tokens** (6.7% relative spread); control
  `tailor_plan` 1,694.8, with `plan_share` 0.454–0.555 on every pair; denominator n = **18**, mean
  $0.184185, range $0.104822–$0.404111, revision rate **33.3%**; ratio at the mean 3.67%;
  **interval [1.67%, 6.44%]**, which straddles the 2% position.
  **The numerator is now well established; the uncertainty is entirely in the denominator** — and
  the live data shows why: **static arms revised 4 of 5 while retrieval arms revised 2 of 12**, so
  a total-cost comparison would have reported a revision-behaviour artefact as a cost finding.
  ⚠️ **PRICING WINDOW — the result does not generalize past it.** It holds at the Sonnet 5 input
  rate of **$2.00/MTok, valid through 2026-08-31** — LiteLLM's own table, and what the gateway
  billed. **At the post-2026-08-31 rate of $3.00/MTok the interval becomes [2.51%, 9.66%] and
  resolves *above* the 2% position.** Never quote the verdict without its window.
  **SC-008 (006) is untouched by all of this and remains MISSED at 3.22% against ≤2%.**

  **Five pairs is what the approved budget buys**, and it is defensible because the numerator is a
  near-deterministic input-token delta on a controlled call — more pairs would add noise to it, not
  signal. The denominator's distribution comes free from the benchmark's own 12 runs.
- **SC-009**: The regression capability is demonstrated on **a real change, not a rehearsal**:
  T057 lands inside this slice, and its effect on every metric is reported with a delta and a
  comparison against the SC-001 noise figure.
  **MEASURED 2026-08-29 — and closed as *measured*, not as a demonstrated improvement.**
  T057's mechanism is confirmed (the Education qualification reaches the model and the export);
  the quality delta is **mean +0.073, n = 5, range −0.20 to +0.40**. **No regression observed; no
  improvement demonstrable.** **The noise floor is unmeasured**, because D3 approved one paid pass
  and the noise repeat was the third — so the delta cannot be compared against zero, and is not.
  The experiment ran **T040 as the post-T057 arm and T045 as the pre-T057 arm**, because T057 had
  already landed at T044 before the benchmark existed; the temporary source revert was restored and
  **SHA-256 verified**. See [results/t057-experiment.md](results/t057-experiment.md).
- **SC-010**: Per-node latency is measured for **100%** of the calls a benchmark run makes, closing
  the half of M-001 that slice 006 carried forward.
- **SC-011**: **MET — $4.925403 of the $10 ceiling, 49%, $5.074597 unused.** Every run's spend is
  recorded and no run started without a projection. One component is an agreed **upper-bound
  estimate rather than a measurement**: Case 1's judge call was billed and then failed validation
  before the guard recorded usage on failures, and is represented at **$0.030**.
  Total spend on this slice stays at or under the approved hard ceiling of **$10**
  (D3), every run's spend is recorded, and **0** runs start without a projection having been
  reported first. The ceiling is deliberately above the $6.11 expected and $7.03 conservative
  estimates — **the headroom is for judge-cost variance, which is the one figure with no
  measurement behind it — and it is not a licence to spend it.**
- **SC-012**: Retrieval quality is measured over **at least 10 postings spanning at least 3
  disciplines** — which is also the sample SC-001 (006) specifies and which no slice-006 task
  records having performed.

### Why these thresholds, and what would make them decoration

Slice 006 recorded that its first draft of SC-007/SC-008 said 5 seconds and 10%, both *"so loose
they could not fail, which makes a threshold decoration rather than a gate."* The same test applies
here, and this slice has a sharper version of the problem: **most of these criteria are about the
harness, and a harness grades itself.**

- The **100% / 0** criteria (SC-002 – SC-006) are absolutes on purpose. Each names a behaviour that
  either happens every time or is broken, and each has a drill: report a metric with `n = 0`, hand
  the harness a canned run, point a benchmark at a real profile. **A criterion here is only real
  once its drill has been watched failing** (FR-033).
- **SC-007 deliberately carries no sample size and no agreement percentage yet.** An earlier draft
  set 15 outputs and 70% by analogy with SC-001 (006). Both were guesses wearing a threshold's
  clothes, and the analogy does not hold — SC-001 (006) asks one reviewer to compare two guidance
  sets, which is a different task with a different error rate from rating generated résumés. The
  plan owes a justified number and an explicit choice between absolute rating and pairwise
  comparison (D8).
- **SC-008 carries no fixed number of pairs.** The floor follows from the budget approved under D3,
  and the plan owes the arithmetic connecting them. **Whether any affordable number of pairs can
  separate a 2% effect from a step function worth a third of a run is the open question**, and it
  must be answered before the money is spent rather than after. If the answer is that it cannot,
  the honest report is *unresolved* — which SC-008 is written to accept as a pass.
- **SC-012's "at least 10 postings, 3 disciplines"** is inherited verbatim from SC-001 (006) so
  that performing it here also discharges that.

**The criterion this slice cannot set for itself** is whether the agent is *good*. Grounding
accuracy, coverage and judge scores are **reported, not gated**, because there is no prior
distribution to set a floor against — the project has thirteen runs. Setting a floor now would
encode a guess as a gate, which `plan_adherence.py` already refuses to do for exactly this reason.
A floor becomes possible once this slice has produced a distribution; that is the next slice's
argument, not this one's.

---

## Inherited Measurement — what this slice is expected to close

Each of these was deferred *to* this slice by name, in a committed artifact.

| | What | Where it was deferred | This slice |
|---|---|---|---|
| **M-001** (half) | Per-call LLM latency is not instrumented; per-node latency is derivable only from throughput assumptions | `specs/006/spec.md` — *"This half remains carried forward to slice 007"* | FR-029, SC-010 |
| **M-002** | Disabling thinking measured 8,707 → 3,448 completion tokens and 93.2s → 45.9s; **quality impact not established**, and it *"MUST NOT be turned into a configuration change without a quality measurement"* | `specs/006/spec.md` | Measurable here. Whether it is *changed* here is **D6** |
| **SC-008 (006)** | Missed at 3.22%; the metric cannot resolve its own threshold independently of revision count | `research.md` R15 — *"deliberately left open"* | FR-028, SC-008, **D1** |
| **SC-001 (006)** | ≥10 postings, ≥3 disciplines, reviewer judges retrieval more relevant than the static rubric in ≥70% of cases. **No slice-006 task records having performed it**, and `HANDOFF.md`'s criteria table reports only SC-007 and SC-008 | `specs/006/spec.md` | FR-017, SC-012 |
| **T057** | Education and Language items drop all but one field; deferred because *"it changes what the model is sent"* and judging that needs evaluation | `specs/006/tasks.md` T057 | SC-009, **D4** |
| **Confidence threshold, max attempts, escalation point** | Three coupled parameters, *"an uncalibrated constant inside a named rules version, so slice 007 can change it honestly"* | `docs/08` Q4, `specs/005/plan.md` | Measurable here. Whether it is *changed* here is **D5** |
| **`de_emphasise` adherence** | Free text with no ids, so "did the draft drop what the plan named" is not computable without changing the Plan schema and prompt | `plan_adherence.py`, `docs/05` §7 | **Out of scope** — it is a prompt change wearing a metric's clothes |

---

## Decisions

**D1 and D2 were approved by the author on 2026-08-29. D3 is pending the cost estimate the plan
owes. D4–D8 carry approved defaults and do not need separate approval before planning unless the
plan reveals a material architectural or budget consequence.** Recorded with what each rejected,
because the rejected option is the part that gets silently re-litigated later.

### D1 — SC-008 (006) stands unchanged *(APPROVED 2026-08-29)*

**Slice 006's SC-008 is kept exactly as written — the ≤2% threshold unchanged and the current
result recorded as MISSED at 3.22%.** It is not reinterpreted, not replaced, and no new threshold
is introduced for it.

Slice 007 **may** define an additional evaluation criterion around revision-controlled retrieval
overhead. That criterion is presented as a **new evaluation criterion** and never as a replacement
or reinterpretation. It appears here as SC-008 (this slice), which says so in its own text.

**The purpose is to evaluate the methodology problem T052 exposed, not to make the existing miss
disappear.** The problem is structural: a fixed per-run overhead divided by a total run cost that
varies 2.7× with revision behaviour cannot establish the overhead's position relative to a 2%
threshold independently of revision count. Two paid re-measurements demonstrated it from both
directions — the numerator improved 21% and the reported ratio got *worse*.

**Rejected**: adjusting the threshold; redefining the metric's denominator in place; and reporting
the 1.68% figure obtained against the older baseline, which is the flattering denominator from a
run that revised when neither current arm did.

**Consequence for every downstream artifact.** Wherever SC-008 (006) is mentioned — plan, tasks,
research, the results view, `HANDOFF.md` — it reads **MISSED at 3.22% against ≤2%**. A comparison
report that shows the new criterion beside it must show both, labelled as different questions.

### D2 — Two-tier benchmark data *(APPROVED 2026-08-29)*

**A committed, fully synthetic set is the reproducible regression baseline. A separate, gitignored
real-world set is used for a limited sanity check only.** The real set is excluded from commits and
from CI, and does not become part of the repository or of the evaluation-evidence record without a
further explicit decision. Only aggregate findings from it may be committed.

**The synthetic set must not be artificially easy** — multiple disciplines, varied roles and
seniority, varied profile content rather than one profile reused, and cases that exercise the
retrieval behaviour this slice exists to evaluate, including at least one where the honest answer
is that the profile does not cover a must-have. Encoded as FR-005a – FR-005d.

**Why the second tier exists at all.** A synthetic posting is cleaner than a real one — better
structured, less redundant, more explicitly enumerated — and both retrieval quality and requirement
coverage could be flattered by that without anyone noticing. The real set answers one question
only: *does the synthetic set overstate the system?* It is a validity check on the benchmark, not a
source of headline numbers.

**Rejected**: a single real set (unreproducible, and one ignore-rule away from publishing a home
address in a public repository); a single synthetic set (no defence against a flattering benchmark).

### D3 — Budget ceiling and case count *(APPROVED 2026-08-29)*

| | |
|---|---|
| **Hard spend ceiling** | **$10** |
| Benchmark size | **12 cases** |
| Full paid regression passes | **1** |
| SC-008 paired static arms | **5** |
| Expected spend | **~$6.11** |
| Conservative estimate | **~$7.03** |

**The $10 is headroom for judge-cost variance, not a budget to consume.** The judge is estimated at
$0.070 per output and is the only figure in the plan with no measurement behind it; if it is off by
50% the recommended tier moves by ~$0.42. **Nothing may be spent beyond $10 without explicit
approval**, and the runner refuses above it before any billable call (FR-008).

**One paid regression pass, not three.** The maximum tier's third pass was the SC-001 noise repeat.
With one pass approved, **run-to-run variation must be established from the free tier** — repeated
fixture runs establish harness determinism, and the noise figure SC-001 requires is reported as
*not measured from paid runs* rather than invented. This is a real reduction in what T057's
comparison can claim, and it is recorded here rather than discovered at T057.

### D4 — T057 is the first controlled regression experiment *(default, approved)*

T057 lands inside this slice as the **first deliberate behaviour change evaluated by it** — after
the baseline is taken, not before. It is the only real, already-scoped, deliberately-deferred
change available, and demonstrating regression measurement on a rehearsal would prove nothing.

### D5 / D6 — Threshold and thinking are parameters to measure, not values to change *(default, approved)*

The Reviewer's confidence threshold, the maximum revision attempts, the escalation point, and the
thinking configuration are treated as **parameters to be measured and evaluated**, never silently
changed. Any change to one is a separate decision taken on evidence, and a change to the
finalisation parameters is a **new `finalisation_rules_version`, never an edit** — editing one
silently reinterprets every historical run.

### D7 — The smallest useful product surface *(default, approved)*

Persisted evaluation runs and results are appropriate. An owner-only, read-only results view is
acceptable **only if the plan shows it is genuinely needed**. A large evaluation product is not
built. The plan must argue the surface it proposes rather than assume `docs/05` §5.7's "results
view" settles it.

### D8 — The smallest defensible human-rating design *(default, approved)*

The plan proposes the **smallest defensible** design and **explicitly distinguishes absolute
ratings from pairwise comparison** — they answer different questions, need different sample sizes,
and produce different agreement statistics. **No sample size is assumed without justification**;
the earlier draft's floor of 15 was a guess and has been removed from SC-007.

### Persistence and migration — decided before implementation, not during

**Migration `0019` is not created yet.** The plan first determines whether this slice genuinely
requires persistent tables. If it does, the plan **specifies the proposed schema and migration and
stops** — ownership of the next migration number has to be resolved against Slice 008, which is in
progress in a parallel worktree and will also want one.

## Out of Scope

- **Changing the ≤2% threshold of SC-008 (006)**, or redefining that criterion.
- **Making `de_emphasise` measurable.** It requires changing the Plan schema and therefore the Plan
  prompt; `docs/05` §7 lists it as a deliberate non-goal.
- **Tuning the Plan or Draft prompts.** Also a stated non-goal *"until there is a distribution to
  judge rather than a handful of samples"* — which is what this slice produces, not what it
  consumes.
- **Automatic retry on a validation failure.** A recovery-behaviour decision, deliberately
  separated from correctness work.
- Company Research (008) and the Career Advisor (009).
- Evaluating the deterministic components. They are measured by the existing gates; there is no
  model output to judge.
- A public or multi-user results surface. The evaluator is the owner.

---

## Assumptions

- **The existing thirteen tailoring runs, eight versions, eight analyses and one submission are
  evidence, not test data.** They cost $3.562567, they are the only evaluation evidence the project
  has, and `HANDOFF.md` §5A forbids modifying or deleting them. Metrics may be computed *over* them
  and MUST NOT be computed by rewriting them.
- **The corpus is fixed during a comparison.** 18 documents / 79 chunks today. A corpus edit
  invalidates a retrieval-quality comparison, which is why FR-007 records corpus identity.
- **The shipping model mix is Sonnet per node with Opus for the Reviewer and escalated revisions.**
  FR-010 pins the benchmark to it.
- **The judge runs on Opus**, because it is judging quality — and it therefore needs its own
  `llm_model_<task>` entry. A task with no entry silently falls back to Opus anyway, which would be
  right here by accident and is not a reason to omit it.
- **Local and production embed with different models today** (MiniLM locally, `bge-small` in the
  image). Every measurement in this slice is assumed to be taken **locally, on one embedding
  model**, and a run must record which — a cross-model comparison of retrieval quality would be
  meaningless.
- **Pricing is read from the gateway's own table**, never written down in the harness, following
  the precedent slice 006 set.
- No paid model call has been made in producing this specification.

## Dependencies

- Slice 005 (the tailoring workflow and its audit records) and slice 006 (retrieval, the corpus,
  and the measurement-script precedent) are complete and deployed.
- The structured completion seam, the fixture gateway, and `plan_adherence.py` exist and are used
  as-is; this slice adds no new provider path.
