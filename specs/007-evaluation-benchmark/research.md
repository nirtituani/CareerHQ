# Research: Evaluation & Benchmark (Phase 0)

**Every figure labelled *measured* was read on 2026-08-29 from the local database by a read-only
query. Every figure labelled *estimated* is arithmetic on top of those, and says so. No paid call
was made.** Measured facts and their interpretation are kept in separate sentences throughout, as
this project's testing philosophy requires.

---

## R1 — What already exists to measure with *(measured)*

Read from `tailoring_run_calls` and `tailoring_runs`, non-fixture rows only.

| task | model | n | avg input | avg output | avg cost |
|---|---|---|---|---|---|
| `tailor_plan` | Sonnet 5 | 7 | 7,830 | 2,757 | $0.043233 |
| `tailor_draft` | Sonnet 5 | 7 | 8,511 | 10,386 | $0.120885 |
| `tailor_review` | Opus 5 | 9 | 7,958 | 2,016 | $0.090196 |
| `tailor_revise` | Sonnet 5 | 2 | 8,109 | 3,617 | $0.052382 |
| `tailor_revise_escalated` | Opus 5 | 1 | 8,652 | 897 | $0.065685 |

Runs: **8 succeeded** (min $0.206268, mean $0.343304, max $0.547891; **3 of 8 revised**), 5 failed.
Reviewer findings: **79 — 64 `uncovered`, 13 `overstated`, 2 `ungrounded`**.

**Interpretation, kept separate.** Three things follow and each shapes the design:

1. **`tailor_draft` is the expensive node** — $0.120885, 47% of a non-revising run — and it is
   expensive because of **output**: 10,386 tokens against 2,757 for Plan. That is the "return only
   what you changed" contract doing its job imperfectly, and it is why cost work belongs to output
   rather than input.
2. **`uncovered` is 81% of all findings.** Whether that is the Reviewer working correctly or a
   prompt weakness is **not decidable from 79 findings across 13 runs** — but it is the first thing
   the benchmark will have a distribution for, and it is the reason requirement coverage is a
   headline metric rather than a footnote.
3. **Two `ungrounded` findings exist**, which means the Principle III path has actually fired on
   real output rather than being theoretical. SC-006 has something to be a regression test *of*.

---

## R2 — Where each metric's input comes from, and what it costs *(design)*

The decisive question for the budget is which metrics need a model at all.

| Metric | Input | Model needed? |
|---|---|---|
| **Grounding accuracy** | `reviewer_findings` (`ungrounded` count), `resume_version_items.source_item_id`, the master profile | **No.** The Reviewer already made the judgement; the metric counts it and verifies none reached persistence |
| **Requirement coverage** | `match_requirements` rows, the composed résumé, `uncovered` findings | **No** for the finding-based figure. **Yes** if coverage is re-judged independently of the Reviewer — see R3 |
| **Retrieval quality** | `guidelines_used`, the posting, the corpus | **No** to retrieve. **A human or a judge** to rate relevance — see R4 |
| **Plan adherence** | `tailoring_runs.plan`, version items | **No.** `plan_adherence.py` already computes it |
| **Match calibration** | `match_analyses.score`, human or judge ratings of the résumés | Needs the ratings, not new analyses |
| **Cost / latency** | `tailoring_run_calls` | **No** to compute; yes to generate new observations |
| **LLM-as-judge** | the composed résumé, the posting, the rubric | **Yes.** It *is* the model |

**Only two rows in that table cost money**, and one of them is the benchmark passes that every
other row also reads. This is the structural reason the free tier goes as far as it does.

---

## R3 — Should requirement coverage trust the Reviewer, or re-judge independently?

**Decision: report both, and never collapse them.**

The Reviewer already emits `uncovered` findings, so a coverage figure is free. But the Reviewer is
*part of the system under test* — a coverage metric read only from its findings cannot detect the
Reviewer becoming wrong, which is precisely the failure slice 005 already hit once: on Zipher it
reported eight requirements "never addressed" against bullets sitting untouched in the résumé,
because it had been shown the diff rather than the document.

**Rejected: coverage from `uncovered` findings alone.** It measures the Reviewer's opinion of
coverage and would report a Reviewer regression as an agent improvement.

**Rejected: coverage from an independent judge only.** It discards a signal already paid for and
makes every coverage figure cost money.

**Chosen: two numbers, always shown together** — *Reviewer-reported coverage* (free, every run) and
*independently judged coverage* (paid, on the judged subset). **Their divergence is itself a
metric**: it is the closest thing this project has to a check on its own Reviewer.

---

## R4 — Retrieval quality without paying for it

**Decision: rate relevance on retrieved sets produced by retrieval alone, with no tailoring run
behind them.**

Retrieval is a local query embedding plus a pgvector scan over 79 chunks, measured at **p50 12.1 ms**
(SC-007, T044). It needs no provider call. So a retrieval-quality study is: take ≥10 postings across
≥3 disciplines, retrieve for each, and rate the returned rules for relevance.

**Two things must be reported separately or the number is meaningless.** The returned set contains
**15 always-pinned integrity rules** that appear regardless of the query (measured at T014). Those
are relevant by construction. Rating the whole set would report a floor as an achievement. The
metric therefore reports **selected-rule relevance** and **pinned proportion** as two figures.

**This also discharges SC-001 (006)** — ≥10 postings, ≥3 disciplines, reviewer judgement — which no
slice-006 task records having performed, and which `HANDOFF.md`'s criteria table does not list among
the measured criteria. It is being picked up here rather than re-run there.

**Open, and left open honestly**: whether the rater is the author or the judge. The author is free
and slow; the judge is fast, costs ~$0.07 per posting, and needs its own validation against the
author before its ratings mean anything — which is circular unless the author rates first. **The
author rates first, on the minimum tier.**

---

## R5 — The judge: what it is shown, and what it must not be shown

**Decision: the judge scores one output against a versioned rubric, blind to which arm produced it.**

- **Shown**: the job posting, the composed résumé, the rubric.
- **Not shown**: which arm, configuration, version or run produced it; the plan; the Reviewer's
  findings; any other candidate's output. FR-026.
- **Model: Opus**, per `docs/08` — *"it is judging quality"*. This requires `llm_model_eval_judge`
  to be set **explicitly**. `model_for_task` falls back to `llm_provider_model`, which is Opus, so
  omitting it would be right by accident and wrong by process — and the fallback is silent.

**Rejected: showing the judge the profile.** That turns it into a second Reviewer and makes its
score correlate with the Reviewer's by construction, destroying the independence R3 depends on.

**Rejected: pairwise A/B between arms.** It is the more sensitive design and it is the right one
*later*. It is rejected for now because it doubles the judge calls, cannot produce a level for a
single run, and cannot be validated against a human sample without the human also doing pairwise
comparisons — which is D8's question, not a decision to make by implication.

**The rubric is version-controlled and versioned** (FR-023), for the reason the match criteria are:
changing a rubric silently makes every historical score incomparable.

---

## R6 — The judge is a model grading a model, so what makes it evidence?

**Nothing, until agreement with a human is measured.** FR-025 makes that structural: a judge score
carries its agreement figure wherever it appears, and an unvalidated judge produces scores labelled
unvalidated.

**Absolute ratings and pairwise comparisons are different instruments** and D8 requires the choice
to be explicit:

| | Absolute rating | Pairwise comparison |
|---|---|---|
| Human asks | "score this résumé 1–5 against the rubric" | "which of these two is better?" |
| Agreement statistic | correlation, or exact/adjacent agreement | proportion of pairs ordered the same way |
| Sensitivity | lower — humans anchor differently between sittings | higher — a relative judgement is easier and more stable |
| Sample cost | one rating per output | grows with pairs, but pairs can be sampled |
| Suits | reporting a level per run | detecting whether a change helped |

**Proposal, smallest defensible**: **pairwise, on the regression question, plus absolute on a small
anchor set.** The slice's central claim is *did this change help*, which is a relative question, and
pairwise is both the more reliable human task and the one that needs fewer judgements to reach a
stable agreement figure. A handful of absolute ratings is kept only to give the rubric a fixed
anchor so scores do not drift between rubric versions.

**No sample size is proposed here.** It follows from the number of judged outputs, which follows
from D3. The tasks phase computes it from the approved case count, and the rule is stated instead:
**the sample must be large enough that the agreement figure would change if the judge were random**,
and the harness reports the figure with its sample size attached either way.

---

## R7 — The SC-008 (006) methodology, restated as a measurement design

**SC-008 (006) is unchanged and remains MISSED at 3.22% against ≤2%.** This section is about
what a sound measurement of the same underlying quantity looks like, which is the question T052
left open.

**The quantity has two parts with completely different statistical behaviour.**

| | Numerator — retrieval's added input tokens | Denominator — total run cost |
|---|---|---|
| Behaviour | near-deterministic; a token-count difference on a controlled prompt | a step function; 2.7× swing on whether the Reviewer revised |
| Measured | +4,727 (T045) then +3,754 (T052) after the citation fix | $0.206268 – $0.547891 across 8 runs |
| What more samples buy | very little — the quantity barely varies | a distribution, which is the entire missing piece |

**Therefore the design is asymmetric, and that is the finding.** Pairs are needed only to pin the
numerator, so a small number suffices. The denominator needs a *sample*, and **every benchmark run
is already one** — so it is free.

**`tailor_plan` remains the clean control.** Between a static and a retrieval arm on the same case,
only the guidance block differs, so its input-token delta *is* the guidance delta. `tailor_draft`
corroborates it but also carries a differing plan: it agreed to within 0.6% in the T045 pair and
18.9% in the T052 pair, so it is corroboration and not a second measurement.

**What this slice reports**: the numerator with its spread across pairs; the denominator as a
distribution with its revision rate; and the implied ratio as an **interval**, stated against a
named denominator. **If the interval straddles 2%, the result is *unresolved*** — which
**SC-008 (this slice)** counts as a pass, specifically so that no one is rewarded for hunting a
denominator that resolves. It leaves **SC-008 (006)** exactly where T052 left it: **MISSED at
3.22%**.

**Rejected: reporting the ratio against the cheapest or the most expensive measured run.** Both are
denominator selection. T052 already declined the flattering one and recorded why.

---

## R8 — Why the benchmark must not be easy, and how to tell whether it is *(D2)*

A synthetic posting is cleaner than a real one — better structured, less redundant, requirements
actually enumerated. Both retrieval quality and requirement coverage would be flattered by that,
and nothing in the harness would notice.

**Three construction rules**, encoded as FR-005b:

1. **Vary the profile, not just the posting.** Reusing one profile across every case makes coverage
   a property of that profile.
2. **Include cases the agent should partly fail.** At least one where the honest answer is that the
   profile does not cover a must-have. A benchmark on which the agent cannot fail measures nothing,
   and it would also give AI-008 nothing to be tested against — the temptation to fabricate only
   exists where there is a gap.
3. **Include a case whose guidance needs differ sharply** from the others, so retrieval has
   something to get wrong. T013 measured 13 rules for a backend posting and 12 for a nursing one
   with **1 in common**; a benchmark of six backend roles would never exercise that.

**And one measurement rule**: the gitignored real set (D2) exists to answer one question —
*does the synthetic set overstate the system?* Run both, compare the metric levels, and **commit the
comparison, not the data**. If the synthetic set scores materially better, the benchmark is
flattering and the cases need hardening.

---

## R9 — What is deliberately not researched here

- **Whether the agent is good.** No floor is set on grounding, coverage or judge score. There is no
  prior distribution to set one against — 13 runs — and `plan_adherence.py` already refuses to do
  this for the same reason. A floor becomes possible once this slice has produced a distribution.
- **Whether to change the confidence threshold, attempts, escalation or thinking** (D5/D6). All are
  measured; none are changed.
- **`de_emphasise` adherence.** Free text with no ids; making it computable means changing the Plan
  schema and therefore the Plan prompt, which `docs/05` §7 lists as a deliberate non-goal.
- **Prompt caching's real effect.** Plausible at ~20% off input and assumed nowhere in the estimate.
