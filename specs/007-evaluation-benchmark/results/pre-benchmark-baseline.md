# Metrics over the thirteen runs already paid for *(T032)*

**Measured 2026-08-29. No model call, no new row, $0 spent.**
Produced by `python scripts/run_benchmark.py report-existing`; the machine-readable
form is [`pre-benchmark-baseline.json`](pre-benchmark-baseline.json).

This is the tier that proves the metric definitions before a benchmark case is
billed. A definition that cannot produce a number from thirteen real runs is wrong
before any money is spent on it.

## What the harness did

| | |
|---|---|
| Runs examined | **13** |
| Metrics reported | **8** |
| Metrics **withheld** | **5** — exactly the five that failed |
| Corpus | 18 documents / 79 chunks / embedding model `unknown` (predates migration `0018`) |

**Five of thirteen were refused — the five that failed** — on `status is 'failed'`.
Filter on status, never on the presence of `guidelines_used`, because a failed run
can carry guidance it never used.

**An earlier draft refused eleven of thirteen**, on the grounds that the record
cannot say which guideline *source* a run was configured with. That was the wrong
question: a metric describes what a run was *advised by*, and `guidelines_used`
records that exactly. Reframing recovered **six legitimately reportable runs** and
**eliminated the schema column** the gap appeared to require — see
[data-model.md](../data-model.md) §0.

**The first draft of this command printed every metric beside the refusal**, which
is exactly what FR-030 forbids — and it read convincingly, because a *failed* run
has no `uncovered` findings and so its coverage computed to a confident **1.00**.
Now withheld rather than shown with a caveat: a number next to a caveat is still a
number people quote.

## The release-blocker check, reported for every run regardless

**`persisted_ungrounded = 0` across all 13 runs.** SC-006 holds on real data.

This one is computed even for ineligible runs, deliberately: it is not an
agent-quality metric but the Principle III guarantee, and a run too ineligible to be
*scored* is not too ineligible to have *leaked a fabricated claim*. Withholding it
would be the one refusal that makes the system less safe.

`ungrounded_caught = 2` across the corpus of runs — so the guardrail has fired on
real output rather than only in tests, and SC-006 has something to be a regression
test *of*.

## The eight runs that could be reported

| run | overall coverage | must-have coverage | guidelines | guidance used | cost |
|---|---|---|---|---|---|
| `2615363e` | 0.27 | 0.25 | 12 | static | $0.295450 |
| `6356fb4e` | 0.33 | 0.40 | 12 | static | $0.464900 |
| `60263226` | 0.67 | 0.67 | 12 | static | $0.547891 |
| `ff0e310c` | 0.50 | 1.00 | 12 | static | $0.307100 |
| `e70ecd76` | 0.22 | 0.20 | 12 | static | $0.446391 |
| `7c1d64d4` | 0.33 | 0.60 | 27 | corpus | $0.206268 |
| `aae6f565` | 0.33 | 0.40 | 12 | static | $0.233124 |
| `1070657e` | 0.22 | 0.40 | 27 | corpus | $0.245262 |

**Measured, and kept separate from interpretation.** Coverage is low across the
board — 0.22 to 0.67 overall. Whether
that is the agent under-addressing requirements, the Reviewer over-reporting
`uncovered`, or the crude text-matching in `coverage()` mis-attributing findings is
**not decidable from eight runs** — and that ambiguity is precisely why `coverage()`
reports a Reviewer-derived figure and an independently judged one separately, and
why it reports `unmatched_findings`.

It is consistent with the finding distribution: **64 of 79 reviewer findings across
all runs are `uncovered`**, 13 `overstated`, 2 `ungrounded`.

## The denominator sample, free

| | |
|---|---|
| Completed non-fixture runs | **8** |
| Of which revised | **3** (37.5%) |
| Cost range | **$0.206268 – $0.547891** |

**This is the SC-008 (this slice) denominator, and it cost nothing.** Every completed
run is already an observation of run cost, so the distribution the methodology needs
comes free with the benchmark rather than being bought. Pairs are needed only to pin
the numerator, which is near-deterministic.

**SC-008 (006) is unaffected by any of this and remains MISSED at 3.22% against an
unchanged ≤2% threshold.**
