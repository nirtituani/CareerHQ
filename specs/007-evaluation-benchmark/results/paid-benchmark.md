# The paid benchmark pass — T040 and T045

**Executed 2026-08-29. Every figure here is measured unless it says otherwise.**
Machine-readable: [`t040-pass.json`](t040-pass.json),
[`t045-pre-t057-arm.json`](t045-pre-t057-arm.json),
[`sc008-007-overhead.json`](sc008-007-overhead.json),
[`all-benchmark-arms.json`](all-benchmark-arms.json).

Corpus 18 documents / 79 chunks, embedded with `all-MiniLM-L6-v2` — the local
corpus, matching every prior local measurement. Shipping mix: Sonnet 5 for plan,
draft and revise; Opus 5 for review and the judge.

---

## 1. Spend — $4.925403 against a $10 hard ceiling

| Component | Amount | Basis |
|---|---|---|
| Benchmark tailoring runs (23) | **$4.335980** | exact, persisted in `tailoring_runs` |
| Judge calls in the main pass (8) | **$0.395800** | exact, itemised in `t040-pass.json` |
| Judge calls in the timeout-interrupted segment (3) | $0.163623 | derived from the guard's cumulative trace |
| **Case 1's failed judge call** | **$0.030000** | **upper-bound estimate — the only unmeasured figure** |
| **Cumulative** | **$4.925403** | **49% of the ceiling; $5.074597 unused** |

**Case 1's judge cost is an agreed upper bound, not a measurement.** That call was
billed and then failed validation, and the harness did not yet record usage carried
on a failed call — the defect §5 describes. It is represented at $0.030 by decision
rather than silently omitted, because a failed call that was billed is not free.

**Every other failed call *is* measured.** Once fixed, the guard charged
`rn-03-theatre-scrub`'s failed judge call at **$0.038020** like any other.

### Per-arm cost

| Arm | Runs | Succeeded | Revised | Spend | Mean |
|---|---|---|---|---|---|
| T040 retrieval | 12 | 12 | 2 | $2.195718 | $0.182977 |
| T040 static (SC-008 pairs) | 5 | 5 | 4 | $0.934839 | $0.186968 |
| T045 pre-T057 | 6 | 5 | 1 | $1.205423 | $0.200904 |

**Runs cost roughly half the planning figure** — $0.183 against $0.308 expected —
because the synthetic profiles are smaller than the real one: 17,706 input tokens
against 26,774 on a comparable real-profile run.

**The judge cost is now calibrated: $0.049475 mean**, range $0.0349–$0.0610. The
plan estimated $0.070 and an offline reconstruction said $0.021; both were wrong,
in opposite directions.

---

## 2. Cases and calls

| | |
|---|---|
| Model calls | **81** |
| T040 retrieval cases | **12 of 12 succeeded** |
| T040 static arms | **5 of 5 succeeded** |
| T045 pre-T057 arms | **5 of 6 succeeded** — `ds-02-mle-production` failed with `ExtractionFailedError` |
| Judge calls | **12 — exactly the approved number** |
| Judged successfully | **9** |
| **Unjudged** | **3** |

**All three judge failures share one cause**: `{"at": "dimensions", "type": "too_long"}`
— the model returned more than the five rubric dimensions `JudgeVerdict` permits.

**Not systematic**: 9 of 12 validated. **The schema was deliberately not relaxed
mid-measurement**, because changing how a score is produced part-way through makes
the scores incomparable — the same rule `criteria_version` and
`finalisation_rules_version` already enforce. Each failure is recorded as an
unjudged case and the pass continued, which is what the judge contract requires.

**Two of the nine successful judge scores are not retained.** They were produced in
the segment a tool timeout killed before its report was written. The calls were
made and billed; the scores are lost. Seven scores survive, in `t040-pass.json`.

---

## 3. SC-006 — the Principle III release-blocker, measured

> ### `persisted_ungrounded = 0` across all 23 paid arms.

Preserved as evidence:

| | |
|---|---|
| Ungrounded claims **caught and discarded before persistence** | **2** |
| Overstated claims **flagged to the owner** | **28** |
| Traceable proportion | **1.0** on every arm |

The severity split discards an `ungrounded` proposal *before any row is written*,
so a fabricated claim has no persisted representation and can never reach an
approve button. **That guarantee is now measured on paid output rather than
assumed**, and the two caught claims mean the guardrail has fired on real model
output rather than only in tests.

---

## 4. SC-008 (007) — **unresolved**, and that is a valid outcome

> **This is SC-008 *(007)*. It is a different criterion from SC-008 (006), which
> remains MISSED at 3.22% against an unchanged ≤2% threshold and is not restated,
> reinterpreted or superseded by anything here.**

| | |
|---|---|
| Paired observations | **n = 5** |
| Numerator | **3,376.6 ± 225.8 tokens** (6.7% relative spread) |
| Control (`tailor_plan` alone) | 1,694.8 tokens |
| `plan_share` per pair | 0.454 – 0.555 |
| Denominator | **n = 18**, mean $0.184185, range $0.104822 – $0.404111 |
| Denominator revision rate | **33.3%** |
| Ratio at the mean | 3.67% |
| **Interval** | **[1.67%, 6.44%]** |
| **Verdict** | **`unresolved`** |

**`unresolved` is a valid outcome of this criterion, not a pass/fail claim about
retrieval.** SC-008 (007) asks whether the measurement can place the overhead on
one side of a stated position; the interval straddles it, so the honest answer is
that it cannot. The criterion is written to accept that **specifically so nobody is
rewarded for hunting a denominator that resolves** — the same numerator over a
flattering denominator was available to T052 and declined.

**What is now well established is the numerator.** 6.7% relative spread across five
pairs, and `plan_share` between 0.45 and 0.55 on every one — Plan and Draft each
carry about half the guidance delta, which is far tighter corroboration than the
T052 pair's 18.9% divergence.

**The uncertainty is entirely in the denominator, and the live data shows why.**
**Static arms revised 4 of 5; retrieval arms revised 2 of 12.** A total-cost
comparison would have credited retrieval with that difference and reported a
revision-behaviour artefact as a cost finding — which is precisely the failure
T052 diagnosed and this methodology exists to avoid.

### Pricing window — the result does not generalize past it

> **This result holds for the Sonnet 5 input rate of $2.00/MTok, valid through
> 2026-08-31.** That is the rate LiteLLM's own table carries and the rate the
> gateway actually billed at.
>
> **At the post-2026-08-31 rate of $3.00/MTok the interval becomes [2.51%, 9.66%]
> and resolves *above* the 2% position.** The verdict is therefore sensitive to a
> price change two days out, and **must not be quoted without its pricing window.**

An earlier computation in this session used $3.00 and reported `above`; it was
corrected to the rate actually billed. Both figures are recorded here rather than
one being quietly replaced.

---

## 5. Two defects the paid pass found

Both in the harness, both fixed, both now covered by tests.

1. **The guard did not charge for billed failures.** `ExtractionFailedError`
   carries the usage the provider billed. `GuardedCompletion` recorded only
   successes, so a failing call read as free — **a hole in the ceiling**, since
   enough of them would spend past it while the guard reported $0. Fixed by
   duck-typing on `.usage`, the pattern `UsageRecorder` already uses and documents,
   so no layering boundary is crossed.
2. **A failed judge killed the pass.** The judge contract says a validation failure
   leaves the case *unjudged* and the run *continues*. `ExtractionFailedError` is
   neither `ValueError` nor `JudgeUnavailableError`, so it escaped the handler and
   ended the pass **after the tailoring run had already been paid for**.

Found by the calibration gate, which is what the gate was for.

---

## 6. Operational notes

- **A tool timeout killed the pass mid-`ds-02`**, leaving one `running` row at
  $0.000000. That single benchmark user was deleted and the case re-run; no paid
  work was lost or double-counted, and the guard's cumulative was carried forward
  explicitly with `--already-spent`.
- **Timestamps are UTC.** A filter written in host-local time matched zero rows —
  the offset `CLAUDE.md` already records for `docker compose logs --since`.
