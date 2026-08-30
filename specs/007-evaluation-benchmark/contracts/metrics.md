# Contract: Metric Definitions

**A metric is a named, versioned function from persisted records to a number plus its `n`.** Every
one obeys the same four rules, and the rules are the contract:

1. **It returns `n` with the value, always.** A metric with no cases returns *not measured*, never
   `0` (FR-020). `plan_adherence.emphasis_adherence` already returns `None` rather than `0.0` for
   exactly this reason, and a posting with no requirements is already *"nothing to score against,
   not a zero"*.
2. **It reads only persisted records** (FR-021). No metric may be computed from a value the system
   did not store, because a figure that cannot be recomputed later is an anecdote.
3. **It is versioned.** Changing how a number is computed is a **new metric version, never an
   edit** — otherwise every historical result is silently reinterpreted. The same rule the match
   criteria and finalisation rules follow.
4. **It refuses rather than guesses.** Given a run that used canned responses, fell back to static
   guidance when retrieval was configured, or ran an off-mix model set, it raises and names which
   (FR-030).

`application/evaluation/` imports no provider SDK, so the existing import-graph gate covers it.

---

## Grounding accuracy — `grounding`

**Question**: what proportion of what the agent proposed traces to the profile?

| | |
|---|---|
| Reads | `reviewer_findings` (kind `ungrounded`), `resume_version_items.source_item_id`, the master profile |
| Returns | proportion traceable; count of `ungrounded`; **and `persisted_ungrounded`, which must be 0** |
| Costs | nothing |

**`persisted_ungrounded` is the Principle III release-blocker check** (SC-006). The severity split
in the use case discards an `ungrounded` proposal *before any row is written*, so the correct value
is always 0 — and a metric that reports it is the thing that would notice if that stopped. **It is
asserted, not merely reported.**

**Drill**: flatten the severity split so an `ungrounded` proposal persists; the metric must name it.

---

## Requirement coverage — `coverage`

**Question**: how much of the posting's requirement list does the résumé address?

**Two numbers, always reported together, never collapsed** (research R3):

| | Reviewer-reported | Independently judged |
|---|---|---|
| Reads | `uncovered` findings against `match_requirements` | the judge, on the composed résumé |
| Costs | nothing | a judge call |
| Weakness | measures the Reviewer's opinion; cannot detect the Reviewer being wrong | costs money; needs the judge validated |

**Must-have coverage is reported separately from overall** (FR-016). A résumé addressing every
"nice to have" and no "must have" is not 50% good.

**Their divergence is itself the metric worth watching** — it is the only check this project has on
its own Reviewer, which has been wrong about coverage before: on Zipher it reported eight
requirements "never addressed" against bullets sitting untouched in the résumé.

**Drill**: return an empty requirement list; the metric must report *not measured*, not 100%.

---

## Retrieval quality — `retrieval_quality`

**Question**: is the guidance retrieved for this posting actually relevant to it?

| | |
|---|---|
| Reads | `guidelines_used`, or a retrieval performed directly against a posting |
| Returns | **selected-rule relevance** and **pinned proportion**, as two figures |
| Costs | **nothing to retrieve.** A rating pass costs the rater's time or one judge call |

**The two figures must not be one.** The returned set contains 15 always-pinned integrity rules that
appear regardless of the query. They are relevant by construction; rating the whole set would report
a floor as an achievement.

**No tailoring run is required.** Retrieval is a local embedding plus a pgvector scan, so a
retrieval-quality study over ≥10 postings across ≥3 disciplines is free — which is also SC-001 (006),
unperformed in slice 006 and discharged here.

**Runs must be filtered on `status`, never on the presence of `guidelines_used`** — slice 006 wrote
that rule down because a failed run can carry guidance it never used.

**Drill**: rate a set retrieved for a different posting; relevance must drop.

---

## Plan adherence — `adherence`

**Reused as written.** `application/plan_adherence.py::emphasis_adherence`, unchanged. Reported as a
**distribution**, which is what it was built to make possible: *"so that when slice 007 can judge it
there is a distribution to judge rather than an anecdote."*

**`de_emphasise` stays unmeasured**, and the reason is recorded rather than rediscovered: it holds
free text with no ids, so making it computable means changing the Plan schema and therefore the Plan
prompt — a deliberate non-goal.

---

## Match-score calibration — `calibration`

**Question**: do higher match scores correspond to better-rated résumés?

Reads `match_analyses.score` and its stored criteria version, paired with ratings. **The criteria
version must match across the sample**, since a score computed under different weights is a
different number wearing the same name.

**Reports its sample size rather than implying one.** With the sample sizes this slice can afford,
the honest output is a direction and an `n`, not a coefficient presented as established.

---

## Cost and latency — `cost`, `latency`

Read `tailoring_run_calls`. **Per-node latency requires `duration_ms`**, which does not exist yet
(data-model §1.1) — until it does, `latency` returns *not measured* rather than a throughput
estimate. That refusal is the point: M-001 was carried forward precisely because the estimate was
being mistaken for a measurement.

**Retrieval overhead** is reported per research R7: numerator from paired `tailor_plan` deltas,
denominator as a distribution over the benchmark's own runs with its revision rate stated, result as
an **interval** against a named denominator. **Straddling 2% is reported as *unresolved*.**

**It never restates SC-008 (006), which stands at MISSED — 3.22% against ≤2%.**

---

## Regression comparison — `compare`

Takes two results. Returns per metric: before, after, delta, and whether the delta exceeds the
measured run-to-run variation.

**Refuses, or names every difference**, when the two fingerprints differ in more than the dimension
under test (FR-031) — model mix, finalisation rules version, benchmark set version, corpus identity,
embedding model, pricing basis. A clean delta across a corpus edit or a pricing change is a lie with
a number attached, and slice 006 already had to write a clause against the pricing version of it.

**Drill**: compare two runs on different benchmark set versions; the comparison must refuse.
