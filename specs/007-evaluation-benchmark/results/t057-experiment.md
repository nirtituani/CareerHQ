# T057 — closed as **measured**, not as a demonstrated improvement

**Executed 2026-08-29 as part of the approved paid pass.** The mechanism is
confirmed; the quality effect is not, and the second half of that sentence is the
result rather than a caveat on it.

---

## The experiment ran backwards from the plan, deliberately

The plan said: take a baseline, land T057, re-run. **T057 had already landed
(T044, earlier in this slice) before the benchmark existed**, so every T040 case
already carried the fuller composition.

| | |
|---|---|
| **T040** | the **post-T057** arm |
| **T045** | the **pre-T057** arm |

Same single variable, same magnitude, labels reversed. The comparison is valid;
only its direction of travel changed.

**The pre-T057 arm was produced by temporarily reverting the four compositions in
`_render_master`, running six cases, and restoring the source in a `finally`.**
The restore was **verified by SHA-256** against the pre-run hash: `f218a263b985`,
match confirmed. No flag was left in production code and no feature toggle was
introduced.

---

## 1. The mechanism is confirmed

**The Education qualification reaches the model and the export.** Read from
`resume_version_items.final_text` on paid runs:

| | |
|---|---|
| **post-T057** | `B.Sc. in Software Engineering · Software Engineering · Ben-Gurion University of the Negev · 2014-2018 · 87` |
| **pre-T057** | `Ben-Gurion University of the Negev` |
| post-T057 (certification) | `Certified Kubernetes Administrator · CNCF · 2022` |
| pre-T057 (certification) | `Certified Kubernetes Administrator` |

This was already established free and deterministically by
`tests/integration/test_master_carries_full_item_text.py`; the paid runs confirm it
on the persisted column the exporter actually renders, which is the claim that
matters.

**One observation, not a defect**: where `qualification` already names the field,
the composition repeats it — `B.Sc. in Software Engineering · Software Engineering`.
Worth tidying; it changes nothing about whether the credential is visible.

---

## 2. The quality effect — measured, and not resolvable

| case | post-T057 coverage | pre-T057 coverage | Δ |
|---|---|---|---|
| `be-01-mid-payments` | 0.67 | 0.50 | **+0.17** |
| `be-02-staff-platform` | 0.00 | 0.00 | 0.00 |
| `be-03-junior-api` | 1.00 | 0.60 | **+0.40** |
| `ds-01-senior-forecasting` | 1.00 | 1.00 | 0.00 |
| `ds-03-analytics-lead` | 0.20 | 0.40 | **−0.20** |

**Mean Δ +0.073, n = 5, range −0.20 to +0.40.**

*(The sixth case, `ds-02-mle-production`, failed on the pre-T057 arm and is
excluded; the comparison states its `n` rather than quietly dropping to five.)*

### What this does and does not establish

| | |
|---|---|
| **No regression observed** | ✅ nothing moved down beyond the spread already present |
| **No improvement demonstrable** | ✅ the spread (−0.20 to +0.40) is wider than the mean (+0.073) |
| **Noise floor** | ❌ **unmeasured** |

**The noise floor is unmeasured because only one paid regression pass was
approved.** SC-001 asks for run-to-run variation on an *unchanged* system, which
was the third pass in the plan's maximum tier; D3 approved one. The free tier
established **harness determinism** — two `validate` runs produced identical case
sets, selections, counts and fingerprints — but that says nothing about *model*
variance, which is what a coverage delta would have to clear.

**So this comparison cannot be judged against zero, and it is not.** What it
delivers is a **bound**: T057 changed no metric by more than the observed spread,
on five cases. That is the claim needed to land a deferred change safely, and it is
the claim being made — no more.

**This outcome was stated in advance**, in `plan.md`, before any of it ran:

> *"The likely result is 'no measurable change', and that is a correct result.
> +16 tokens is far below what a benchmark of this size can resolve on quality, and
> saying so now is the difference between a finding and a disappointment."*

The prediction was written down first precisely so the result could not be shopped
for afterwards.

---

## 3. Status

**T057 is closed as measured.** The mechanism works and is covered by a free,
deterministic test that has been watched failing. The quality question is not
answered and is not claimed to be; answering it needs a measured noise floor,
which needs a paid pass that was not approved and is not requested here.
