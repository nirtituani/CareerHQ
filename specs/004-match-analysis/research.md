# Phase 0 — Research: Match Analysis

Eight decisions. Each records what was chosen, why, and what was rejected — so the next person
reads a settled question rather than re-opening it.

R1 is the only one that was not already settled by the approved design; it was found by reading
the code the design describes.

---

## R1 — What to do about `job_description`, which does not hold what its name says

**Finding.** The design's §1 states that one extraction call already produces both the posting and
its requirements, and that the earlier version "simply discarded one of them". Reading
`application/extract_job.py` shows the discard is still in force and is more consequential than a
missing column:

```python
posting = JobPostingExtraction(
    **fields,
    job_description="\n".join(requirements) if requirements else body,
)
```

`requirements` is extracted, joined with newlines, stored as `job_description`, and the posting
body is **dropped**. When the model finds no requirements the body is stored instead. So a single
column holds two different kinds of content, and which one it holds is not recorded anywhere.

The frontend already works around this: `detail-tabs.tsx` renders `job_description` as bullets, and
carries a comment that records saved before requirements extraction "hold paragraphs".

**Decision.**

1. Add a `requirements` column and populate it going forward. `job_description` returns to meaning
   the full posting for every row written from this slice onward.
2. **Do not backfill and do not guess.** Splitting a stored requirements list back into a posting is
   impossible — the posting was never stored — and a heuristic that decides "this looks like
   bullets" would be wrong on exactly the postings that matter.
3. Mark the boundary explicitly rather than inferring it. Rows written before this slice are
   identifiable, and a row whose posting was never captured is **not scored**: it falls into the
   spec's fourth state, *nothing to score against yet*, with an offer to re-add the job to
   repopulate both fields.

**Rationale.** Scoring a legacy row would compare the profile against a requirements list while the
prompt claims to be reading a whole posting. That is precisely the requirements-only scoring the
design reversed, reintroduced silently and impossible to spot in the output — the score would look
entirely normal. The fourth state already exists for jobs with nothing to score; a legacy row is a
true instance of it, not a special case.

**Alternatives rejected.**

- *Backfill by re-fetching each posting's URL.* Postings expire; the fetch is the least reliable
  step in the system; and it would spend real requests on jobs the person may never open.
- *Score legacy rows anyway, treating the requirements list as the posting.* Cheapest, and it
  produces a plausible number with the known-worse methodology behind it. A wrong answer that
  looks right is the worst available outcome here.
- *A heuristic to distinguish bullets from prose.* It would misfire on postings that are genuinely
  terse and on requirement lists that are genuinely long, and its failures would be invisible.

---

## R2 — Scored against the whole posting, not the requirements list

**Decision.** The completion reads the full posting text; requirements are extracted and stored
alongside it for the person to read.

**Rationale.** Requirements-only was tried and reversed. *"Design and operate services handling
millions of requests per day"* appears in no requirements section and is exactly what makes a
production backend history relevant. Requirements-only also discards team size, domain, the stack
mentioned in passing, and how senior the work really is. Cost of the change is about half a cent
per job — the input side is the cheap side.

**Alternative rejected.** Scoring the requirements list, at a saving too small to justify the
known loss of signal.

---

## R3 — One structured call, not an agent

**Decision.** `complete(task="match_analysis", schema=MatchAnalysis, prompt=…)` — the third call
site through the seam.

**Rationale.** This is profile + posting → one structured judgement. There is no loop, no tool, and
nothing to critique. T096's guard, as amended, is that *no call site reacts to its own previous
output*; this one does not, so the guard holds unchanged. An agent runtime would add retries and
state to something that runs once.

**Alternative rejected.** Routing through a workflow engine for consistency with the tailoring
agent. It would make the tailoring agent's design decisions here, before that slice is specified.

---

## R4 — No retrieval, and the reason is the failure mode

**Decision.** The entire profile goes into the prompt. No embeddings, no vector search, no
retrieval step.

**Rationale.** A profile measures ~760 tokens (measured) against a posting's 2,400–4,500. The whole
corpus fits many times over. Decisively: the feature's central question is *which requirements do I
lack*, which can only be answered from the **entire** profile. A retrieval miss on the bullet
mentioning Kubernetes makes the system state confidently that Kubernetes is missing — inventing a
gap, silently, in the one feature where a false negative is the headline output.

Constitution VI independently forbids it: structured operational facts are retrieved relationally;
vector retrieval is for semantic knowledge. The profile is the former.

**Alternative rejected.** Retrieval for symmetry with the tailoring agent, where RAG belongs over
resume-writing guidelines — an external corpus genuinely too large for context, and where a miss
costs a weaker phrasing rather than a false accusation.

---

## R5 — Requirements as rows, not a JSON blob

**Decision.** One table row per requirement, carrying its ordinal, kind, verdict and evidence.

**Rationale.** Slice 007's Career Advisor needs to count how often each skill is required and
separate critical gaps from nice-to-haves. As rows that is a `GROUP BY`. As JSON it is unqueryable
and would have to be re-extracted from analyses already paid for.

**Alternative rejected.** A JSON column, which is less migration work now and a re-extraction bill
later.

---

## R6 — Append-only analyses with a pointer that advances only on success

**Decision.** Every run inserts a new analysis. The application points at the analysis to display,
and that pointer moves only when a run reaches `ready`.

**Rationale.** Re-running after a profile edit must not destroy the previous score — calibration is
measured over history, and Principle IV governs. Advancing only on success is what stops a score
blanking out mid-re-run and stops a failed re-run destroying the last good number. The alternative
— update in place — loses history and makes a failure destructive.

**Alternative rejected.** One mutable analysis row per application, which is simpler until the
first failed re-run erases a good score.

---

## R7 — A background task, not a queue

**Decision.** Saving the job returns immediately; the analysis runs in an in-process background
task. The analysis row is written `pending` **in the same transaction as the application**.

**Rationale.** No queue is deployed, and standing one up for a ~12-second task is more
infrastructure than the feature warrants. Writing the row `pending` first is what makes the
background run visible rather than mysterious: the interface has something to show a spinner
against, and a failure has somewhere to record itself instead of leaving a blank forever.

**Known limitation, accepted.** A process restart mid-analysis leaves a row `pending`
indefinitely. That is visible rather than silent, and a re-run fixes it. A queue is the answer if
this ever becomes common; it is not worth pre-building.

**Alternative rejected.** Scoring synchronously on save, which makes adding a job take 12 seconds —
the single worst place to spend them, since it is the step a person repeats.

---

## R8 — Sonnet, chosen by task name, configured explicitly

**Decision.** `llm_model_match_analysis` ships in the same commit as the use case, set to Sonnet
per docs/08 §3.2.3's assignment of *analyze*.

**Rationale.** `model_for_task` falls back to `llm_provider_model`, which is **Opus** — so a missing
entry runs this at roughly $0.065 per job, 2.5× Sonnet, silently and with no quality gain. This is
not hypothetical; CLAUDE.md records the same fallback catching CV extraction once already.

Costs, reconciled against a real billed call (the Greenhouse extraction: 6,511 in / 131 out,
charged $0.014332, which matches the introductory rate exactly):

| | input | output | today | after 31 Aug 2026 |
|---|---:|---:|---:|---:|
| Typical posting | 3,420 | ~1,500 | **$0.022** | $0.033 |
| Long posting | 5,560 | ~1,500 | **$0.026** | $0.039 |

### Measured (T075) — the estimate was low, and SC-004 is missed

Those were projections made before the feature existed. A real analysis, billed:

| | input | output | charged | after 31 Aug 2026 |
|---|---:|---:|---:|---:|
| 12-requirement posting (1,890-char advert) | 3,700 | 2,811 | **$0.035510** | $0.053265 |
| **8-requirement posting (3,785-char advert)** | 4,437 | **6,263** | **$0.071504** | $0.107271 |

**The second measurement is the alarming one, and it is not the requirement count.** Eight
requirements produced **more than twice** the output of twelve — because the posting was twice as
long, and the model reasons about the whole of it. So output does not scale with the requirement
list, which was the assumption behind both the original estimate and the first measurement. It
scales with how much there is to read.

At **$0.0715**, that single job is 2.4× the SC-004 target on its own, and $7.15 per hundred.

Output is **79%** of the cost — inside the predicted 57–86% band, so that part held. But it is
nearly **double** the 1,500-token estimate, and that is the whole miss. The estimate assumed three
verdicts and neither an `importance` nor a `shortfall` field. v2 has five verdicts, both fields,
and requires evidence on `gap` as well as on the positive verdicts. Every one of those decisions
was right, and each of them costs output.

**SC-004 asks for $0.03 per job and $3 per hundred. Measured: $0.0355 and $0.0715 on two real
jobs — 18% and 138% over.** After 31 August the same two calls cost $0.053 and $0.107.

Recorded rather than adjusted. Three ways out, in the order worth trying:

1. **Return references instead of quoting both sides** — the lever §R8 already names. Evidence
   strings are the bulk of the output and both texts are stored, so they can be joined at render
   time: roughly half the output at no information loss. **It weakens the grounding check**, which
   is why it was deferred, so it needs design rather than a flag.
2. **Measure Haiku 4.5** at half the price. The task is schema-validated, so a weaker model fails
   loudly rather than silently — but five verdicts is a harder task than three, which is an
   argument for measuring rather than assuming.
3. **Revise SC-004.** $0.0355 for a grounded, per-requirement analysis of a whole posting may
   simply be what this costs. The target came from a projection that no longer describes the
   feature, and saying so is better than meeting it by making the analysis worse.

**Output is 57–86% of the cost**, because output bills at 5× input. The dominant output cost is
per-requirement evidence quoting profile text the database already holds.

**Alternatives rejected for now.**

- *Haiku 4.5* at half the price — plausible, and untested here. The seam raises rather than
  accepting partial data, so a weaker model trades cost for extraction failures. Decide with a
  measured comparison once real analyses exist, not by a blind swap.
- *Returning a requirement index and profile reference instead of quoting both sides* — roughly
  halves output at no information loss, since both texts are stored. Rejected **for this slice**
  because the quoted evidence is what makes the grounding check structural; the lever is recorded
  for when cost actually bites.
- *Prompt caching* — the profile plus prompt is ~1,060 tokens against a 1,024-token cacheable
  minimum, so it barely qualifies, and input is the minority of the bill regardless.
- *A quick-score-then-detail split* — both variants read the same input, so it saves nothing on the
  expensive half, costs more in total if the tab is ever opened, and produces two independently
  generated numbers that can disagree on one screen.

---

## R9 — The rubric, from two sources that disagreed

**Sources.** [`varunr89/resume-tailoring-skill`](https://github.com/varunr89/resume-tailoring-skill)
(MIT) and [`shahar84/shahar-polaks-career-studio`](https://github.com/shahar84/shahar-polaks-career-studio),
both supplied after the spec was drafted. The second is licensed for personal use and forbids
derivative works and redistribution; **that concern was raised and the author elected to proceed
with both.** Recorded here as a fact about provenance, not re-argued.

They conflict. One supplies a weighted percentage rubric; the other states plainly *"do not use
pseudo-scientific fit percentages"* and prescribes qualitative bands. Resolving that produced three
decisions.

### D1 — Five verdicts, not three. This fixed a real defect.

The taxonomy separates *transferable* from *confirmed*, and *unverified* from *gap*.

The second separation matters most, and it exposed a hole in the original specification. That
draft had a single `missing` verdict carrying no evidence — which let the system turn *"your
profile does not mention Kubernetes"* into *"you do not have Kubernetes"*. That is a negative claim
about the person which the profile does not support.

**This is AI-008 violated in the direction nobody was watching.** The whole grounding apparatus was
built to stop the model inventing experience the profile lacks, and it left the model free to
invent absences. The spec, the data model and the contract all shipped that hole; a supplied
taxonomy caught it before implementation did.

The fix makes the constraint stronger rather than more complicated:

```sql
CHECK ((verdict = 'unverified') = (evidence IS NULL))
```

Every verdict is now grounded, including the negative ones — a `gap` must quote the shortfall.
`unverified` is the sole evidence-free verdict, precisely because it is the one that asserts
nothing.

### D2 — Store a number, show a band

Both sources are right about different things. A bare *84%* claims a precision the method does not
have. But something must be sortable across forty jobs and comparable across time, because
docs/07 §3.2 evaluates this capability on **Match Score calibration**, and there is nothing to
calibrate if no number is retained.

**Decision**: compute and store `overall_score`; display `strong` / `moderate` / `stretch` /
`low_probability`. The band is stored too, not computed at render — re-banding a historical
analysis under new thresholds would silently rewrite what the person was once told.

*Alternatives rejected*: showing the percentage, which the second source warns against directly;
and dropping the number, which forfeits sorting and calibration in exchange for a scruple already
satisfied by not displaying it.

### D3 — Gaps are classified wording / evidence / capability

Because the action differs: rephrase what is already there, supply proof, or acknowledge it. A gap
list that does not say which is a list of problems with no next step.

### What was adapted rather than adopted

The weighted dimensions were designed to score **one experience against one template slot**. Here
the unit is a whole profile against a whole posting. The weights (40/30/20/10) carry over; the band
thresholds and the must-have cap are ours. `v1-weighted` records that it is an adaptation.

**The must-have cap is not in either source.** A profile scoring 80 on everything while failing a
stated must-have is not a strong match, and a weighted average hides that cheerfully. So a
must-have at `gap` caps the band at `stretch` whatever the arithmetic says.

---

## R10 — Weighing silence, and judging importance rather than trusting the heading

Both decided by the author after R9 shipped, and both reverse something R9 settled. `v1-weighted`
scores exist, so this is `v2-importance` rather than an edit (FR-018).

### D1 — `unverified` is weighed like a gap

R9 capped only on `gap`, on the reasoning that silence is not proof of absence. That is right about
the **claim** and wrong about the **score**.

The score answers *is this worth my evening*. A recruiter reads exactly the profile the model
reads and draws the same conclusion from silence — so a requirement the CV does not evidence is a
risk to the application whether or not the shortfall is provable. Treating "your CV does not show
this" as costless models a reader who does not exist.

Nothing about AI-008 changes, because the two were never the same question. The grounding rule
governs what the system **asserts**: `gap` still requires quoted evidence, `unverified` still
forbids it, and the system still never says *you do not have this* about a silent profile. Only
the weighing changed.

**And the loop is already built.** A person who sees `unverified` on something they can do adds it
to their profile; the analysis goes stale and offers a re-run (US3). `unverified` is recoverable
in a way `gap` is not — which is a reason to show them differently, not a reason to make one free.

### D2 — Importance is judged per requirement

The obvious way to stop the cap over-firing is a proportional rule — cap when more than some
fraction of must-haves are unmet. Rejected: it treats every must-have alike, which is the same
flaw one level up.

Instead the model rates each requirement's `importance` 0–100 and the cap fires at **70**. The
prompt tells it not to read importance off the heading, and gives it the signals that actually
carry it: requirements stated **earlier** matter more, because recruiters lead with what they care
about and pad the end; so does anything repeated across sections, named in the job title, or tied
to what the team actually does. It anchors the scale (80–100 the role *is* this, down to 0–39
boilerplate) and warns that most postings have only two to five above 80.

`kind` is kept beside it. It is the employer's own words, and the split mirrors `status` against
`normalized_status`: the source is preserved, the value the system reasons over is derived, and
neither can be quietly lost. A `preferred` requirement judged critical caps; a `must_have` judged
incidental does not.

**Cost**: one integer per requirement, roughly 150–200 output tokens on a 38-requirement posting —
about 10% more per analysis. Folded into T075's re-measurement.

**Alternative rejected**: deriving importance from `ordinal` alone in application code. Position is
real signal and is already stored, but it is not sufficient — "familiarity with Jira" is filler
wherever it appears, and a model reading the whole posting knows that where a rank does not.

### The `is` → `==` fix that shipped with it

`band_for` compared verdicts with `is`. Correct while the values came straight from a completion as
enum members — and silently wrong for anything read back from the database, since these are
`String(16)` columns that return plain `str`. Nothing would have raised; the cap would simply have
stopped firing, with every band still looking plausible. There is now a test that passes strings.

---

## Deferred by design, with the mechanism that makes deferral safe

| Question | State | Why it is safe to start without it |
|---|---|---|
| **The scoring rubric** | **Resolved by R9, revised by R10** — ships as `v2-importance` | The planned uncalibrated `v0` was never entered. FR-018 still governs: a v2 must stay distinguishable. |
| **A canonical skill vocabulary** | Not built | Requirements are scored as written. Whether collapsing "K8s"/"Kubernetes"/"container orchestration" is needed becomes visible from real analyses. |
| **Whether Haiku suffices** | Untested | R8. Decided by measurement once there are analyses to compare. The five-verdict taxonomy is a harder task than three, which is an argument for measuring rather than assuming. |
