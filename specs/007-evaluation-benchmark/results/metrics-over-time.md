# Metrics over time *(T035, FR-036, FR-037)*

**A committed file, not a page.** D7 asked for the smallest useful product surface,
and every metric requirement is satisfied by version-controlled results plus the
existing `GET /api/versions/{id}/run` audit endpoint — which slice 005 built to be
*"read programmatically by slice 007"*. **No UI was built.** If a graded demo later
needs a screen rather than a document, that is a separate decision with the metrics
already in place to render.

**Results live in git rather than in a Docker volume, deliberately.** The project's
existing evaluation evidence sits in two local volumes with a same-machine backup
that was already stale; putting this slice's results there would reproduce a known
risk knowingly.

---

## The series so far

| # | Date | What changed | Arms | Metrics reported | Spend |
|---|---|---|---|---|---|
| 1 | 2026-08-29 | *(none — free baseline over runs already paid for)* | 13 historical | 8 of 13 reportable, 5 withheld | **$0** |
| 2 | 2026-08-29 | *(none — free end-to-end validation)* | 12 cases, no model calls | structure + retrieval only | **$0** |
| 3 | 2026-08-29 | **first paid pass** — T040 | 12 retrieval + 5 static | full | **$3.72** |
| 4 | 2026-08-29 | **T057 reverted** — T045 pre-T057 arm | 6 | coverage + grounding | **$1.21** |

Sources: [`pre-benchmark-baseline.md`](pre-benchmark-baseline.md),
[`validation.md`](validation.md), [`paid-benchmark.md`](paid-benchmark.md),
[`t057-experiment.md`](t057-experiment.md).

## What moved, and what a later run should compare against

| Metric | Value | Comparable across runs? |
|---|---|---|
| `persisted_ungrounded` | **0** on all 23 paid arms | ✅ absolute; any non-zero is a release blocker |
| `traceable` | **1.0** on all arms | ✅ |
| ungrounded caught / overstated flagged | 2 / 28 | ⚠️ scales with case count |
| coverage (overall) | 0.00 – 1.00, mostly 0.20 | ⚠️ only within one benchmark set version |
| judge `overall` | 2 – 4, n = 7 | ⚠️ only within one rubric version, and **unvalidated** — no human sample yet |
| retrieval overhead numerator | 3,376.6 ± 225.8 tokens | ✅ stable; the tightest figure the slice produced |
| run cost | mean $0.183, range $0.105 – $0.404 | ⚠️ **only within one pricing window** |

**Two comparability rules the harness enforces rather than trusts.** `assert_comparable`
refuses any comparison whose fingerprint differs in more than the dimension under
test — benchmark set version, metric version, finalisation rules version, corpus
identity, embedding model, pricing basis, model mix. Both a corpus edit and a
pricing change are named rather than averaged over, which is the trap SC-008 (006)
already had to write a clause against.

**The judge scores carry an unvalidated label and must keep it.** FR-025: agreement
with a human-rated sample has not been measured, so no conclusion in this slice
rests on a judge score.

## The gap a later run must close first

**There is no measured noise floor.** D3 approved one paid pass; SC-001's
run-to-run repeat on an unchanged system was the third. Harness determinism is
established — two `validate` runs produced identical case sets, selections, counts
and fingerprints — but that is not model variance. **Until a repeat pass exists,
every delta in this series is a bound, not a movement**, and the T057 comparison
says so explicitly.
