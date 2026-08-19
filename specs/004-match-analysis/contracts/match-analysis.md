# Contract: the match analysis completion

Written to be implemented against without re-reading the plan. Inherits
[the structured completion seam](../../003-data-foundation/contracts/extraction-seam.md) unchanged
— this is a **caller**, not a new seam.

Required by FR-001, FR-002, FR-008 to FR-011, FR-017 to FR-020, and Constitution Principles III,
V and VI.

---

## The call

```python
completion.complete(
    task="match_analysis",          # NOT a model name — O3
    schema=MatchAnalysis,           # required — O1
    prompt=render(profile, posting),
)  -> Completion[MatchAnalysis]
```

One call. No loop, no tools, no self-critique, no reaction to its own output — which is what keeps
T096's amended guard intact at the third call site.

`task="match_analysis"` resolves through `Settings.model_for_task`. **`llm_model_match_analysis`
must exist**; the fallback is Opus at 2.5× the cost with no quality gain (R8).

---

## The schema

```
MatchAnalysis
    direct:         int          # 0..100 — the four rated dimensions
    transferable:   int          # 0..100
    adjacent:       int          # 0..100
    impact:         int          # 0..100
    verdict:        str          # one sentence
    requirements:   list[MatchRequirementResult]   # may be empty

MatchRequirementResult
    text:       str              # the requirement as the posting worded it
    kind:       "must_have" | "preferred"
    verdict:    "confirmed" | "partial" | "transferable" | "gap" | "unverified"
    shortfall:  "wording" | "evidence" | "capability" | None
    evidence:   str | None       # quoted from the profile
```

**`overall_score` is not returned by the model — it is computed.** See *The rubric* below. Asking
the model for both the parts and the total invites them to disagree, and the total is the one a
person acts on.

### The grounding rule is a validator, not a convention

```
confirmed     → evidence MUST be a non-empty string
partial       → evidence MUST be a non-empty string
transferable  → evidence MUST be a non-empty string
gap           → evidence MUST be a non-empty string   ← quote the shortfall
unverified    → evidence MUST be None

shortfall is None  ⟺  verdict == "confirmed"
```

**Negative verdicts are grounded too, and that is the point.** A `gap` asserts the person falls
short, which is a claim about them; it must quote the profile text that shows it — three years
where five were asked. A model that cannot quote anything does not get to call it a gap. The
honest verdict is then `unverified`, which is the only evidence-free option precisely because it
asserts nothing.

An earlier draft of this contract made the negative verdict evidence-free, which let a silent
profile become a confident *you do not have this*. AI-008 forbids inventing experience the profile
lacks; inventing its absence is the same fabrication pointed the other way.

Violation raises, and by the seam's obligation **O2 a validation failure is an extraction
failure** — never partially accepted, never repaired by hand, never shown as though understood.
The analysis is recorded `failed`.

This is AI-008 — *never invent experience the profile does not contain* — made structural.
A model that claims a match it cannot quote has told you it was guessing. The same rule is
repeated as a database constraint (see [data-model.md](../data-model.md)) because the schema
protects one path and the constraint protects the table.

**`evidence` must be quoted from the profile, not composed.** The prompt says so; the schema cannot
enforce it. What the schema *can* enforce, and what a test must assert, is that a met verdict
carries something. Whether that something appears in the profile is checked by an integration test
against a known fixture profile, not hoped for.

---

## The rubric — `criteria_version: v1-weighted`

Adapted from `varunr89/resume-tailoring-skill` (MIT). Its dimensions were designed to score one
experience against one template slot; the unit here is a whole profile against a whole posting, so
the weights are carried over and the band thresholds are ours.

**The model rates four dimensions; the application computes the score.**

| dimension | weight | what it rates |
|---|---:|---|
| `direct` | 40% | The profile shows the same capability, in the same domain, at comparable scale |
| `transferable` | 30% | The same capability in a different context — leadership elsewhere, the same problem in another stack |
| `adjacent` | 20% | Touched as a secondary responsibility, related tooling, a supporting role nearby |
| `impact` | 10% | The kind of outcome the posting values — metrics, team results, scale, invention |

```
overall_score = round(direct*0.4 + transferable*0.3 + adjacent*0.2 + impact*0.1)
```

Computed in the application layer, never by the model (see the schema note above).

**Bands**, which are what the person is shown:

| score | band |
|---:|---|
| 75–100 | `strong` |
| 55–74 | `moderate` |
| 35–54 | `stretch` |
| 0–34 | `low_probability` |

**A must-have at `gap` caps the band at `stretch`**, whatever the arithmetic says. A profile
scoring 80 on everything else while failing a stated must-have is not a strong match, and a
weighted average will happily hide that.

Both the weights and the thresholds are part of `v1-weighted`. Changing either is a **new criteria
version**, never an edit — FR-018, and the reason the band is stored rather than recomputed.

## The prompt's obligations

Not the wording — the wording will be tuned. These are the properties the wording must preserve.

**P1 — Both sides are given in full.** The entire profile and the entire posting go in. Nothing is
retrieved, sampled, or summarised first (R4). If the posting exceeds the input budget it is
truncated **at the end with the truncation recorded**, never silently dropped from the middle —
requirements cluster in the second half.

**P2 — Requirements are copied, not composed.** Each `text` is worded as the posting worded it.
A model that paraphrases requirements makes the coverage count incomparable between runs and makes
slice 007's frequency counting meaningless.

**P3 — Score the whole posting.** Signals stated outside a requirements section still count — the
reversal recorded in R2 is a property of the prompt, and a wording change that quietly narrows it
back to the requirements list is a regression with no failing test to catch it.

**P4 — Silence is `unverified`, never `gap`.** A requirement the profile does not address at all
is `unverified`. The model may neither reason that the person "probably" has it, nor that they
lack it. `gap` is reserved for a shortfall the profile actually demonstrates, and the evidence
requirement enforces this — there is nothing to quote for a requirement the profile never mentions.

**P5 — All five verdicts are available and must be used.** Without explicit instruction models
collapse to a met/missing binary, which simultaneously inflates the score and manufactures gaps.
`partial` and `transferable` are the two that get dropped first, and they are where most real
profiles actually live.

**P7 — `transferable` is never dressed as `confirmed`.** The evidence for a transferable match
must make the transfer visible rather than implying direct experience.

**P6 — The criteria are the model's own judgement, and this is stated.** Until a rubric exists,
the prompt does not pretend to one. The version recorded alongside says the same thing.

---

## What is recorded, and when

| | written | where |
|---|---|---|
| Analysis row, `pending` | in the same transaction as the application | `match_analyses` |
| `overall_score`, `verdict`, requirement rows | in one transaction on success | `match_analyses`, `match_requirements` |
| `model`, `input_tokens`, `output_tokens`, `cost`, `is_fixture` | **the same transaction as the result** | `match_analyses` |
| `criteria_version` | at insert, non-null | `match_analyses` |
| `error` | on failure, with the row moved to `failed` | `match_analyses` |

Usage is returned by the seam and written by the application layer — obligation O4. Infrastructure
stays dumb and the audit trail lands where the data does.

**The pointer moves last.** `applications.current_match_analysis_id` advances only after the
analysis is `ready`, in the same transaction. A failed run never touches it.

---

## Testing obligations

| | Obligation |
|---|---|
| **T1** | No test makes a live provider call. The fixture adapter supplies completions (FR-027). |
| **T2** | A completion returning `confirmed`, `partial`, `transferable` or `gap` with no evidence is **rejected**. Assert the raise, and watch it fail before the validator exists. |
| **T3** | A completion returning `unverified` **with** evidence is rejected — the rule is an equivalence, not an implication. |
| **T3a** | Given a profile silent on a named requirement, the verdict is `unverified` and **not** `gap`. This is the defect the five-verdict taxonomy exists to prevent; it needs a test or it will regress. |
| **T3b** | `overall_score` equals the weighted sum of the four dimensions, and a must-have `gap` caps the band at `stretch` regardless of arithmetic. |
| **T4** | The failure path writes `failed` with an error and leaves the application usable (FR-026). |
| **T5** | Every stored analysis and requirement value reaches the API — read the model's own columns, in the manner of slice 003's `test_profile_content.py`, which found a fourth dropped field on its first run. |
| **T6** | `task="match_analysis"` resolves to a configured model, not the Opus fallback. |
| **T7** | A profile is unchanged across a run (I6). |
