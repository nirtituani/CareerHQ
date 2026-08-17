# Match Analysis — design

**Date**: 2026-08-17
**Status**: approved, not yet implemented
**Slice**: 004 (started ahead of slice 003 finishing — see *Sequencing*)

---

## 1. What this is

A score, and its reasoning, for how well the user's Professional Profile fits one
recorded job. It answers **"is this worth applying to, and where am I weak?"** —
read when adding a job, before any resume work.

It appears as a **Match** tab on the application record, second after Details, and
as a percentage in the applications table's Match column.

### It scores against the whole posting, not the requirements list

**Requirements-only was tried first and reversed**, and the reversal is recorded
here so nobody re-derives it. A requirements list omits the signal that decides
most matches: *"design and operate services handling millions of requests per
day"* appears in no requirements section, but it is exactly what makes a
production backend history relevant. Scoring on requirements alone also loses
team size, domain, the stack mentioned in passing, and how senior the work
actually is.

So the extraction stores **both**, and they serve different readers:

| field | holds | read by |
|---|---|---|
| `job_description` | the full posting text | the match analysis, and slice 004's tailoring |
| `requirements` | the extracted list | the person, on the Details tab, as bullets |

One extraction call already produces both — `requirements` is a field on
`JobMetadata` and the full text is what the model was given. The earlier version
simply discarded one of them.

### What it is not

- **Not a tailoring quality metric.** docs/07 §3.2 lists a Match Score among the
  Resume Optimizer's outputs. That is a different measurement — *how well does this
  tailored resume match* — and belongs with tailoring in the Versions tab. The two
  share a schema so their numbers stay comparable, and a later slice can show
  "68% before tailoring → 84% after".
- **Not the user's own rating.** `applications.imported_match_rating` is the 1–5
  judgement carried over from JobTracker. It is never overwritten. What the person
  thought and what the system computed are two facts; one field for both would
  drift, exactly as the source app's `rejected` flag drifted from its status.
- **Not an approval gate.** Principle II governs changes to owned data. This
  observes the profile and writes nothing to it.

---

## 2. Why not an agent, and why not RAG

Both were considered and rejected on the specifics rather than on principle.

**Not an agent.** An agent here means a workflow that reacts to its own output —
the Optimizer's `Analyze → Retrieve → Draft → Self-Critique → Revise`. This is
profile + requirements → one structured judgement. No loop, no tools, nothing to
critique. It goes through the existing `StructuredCompletion` seam: one call in,
one validated object out. An agent runtime would add retries and state to something
that runs once and returns.

**Not RAG, and the reason is the failure mode.** A Professional Profile measures
**760 tokens** (measured, not estimated) and a whole job posting 2,400–4,500.
There is nothing to retrieve *from* — the entire corpus fits in the prompt many
times over, with a 1M context window to spare.

More importantly, the feature's central question is *which requirements do I not
have*, and that can only be answered by seeing the **entire** profile. If retrieval
misses the bullet mentioning Kubernetes, the system states confidently that
Kubernetes is missing — inventing a gap. For a "what's missing" feature a retrieval
miss is the most damaging error available, and it is silent.

RAG belongs in slice 004 where docs/07 §3.2 already puts it: over **resume-writing
guidelines**, an external corpus genuinely too large for context, where a miss costs
a weaker phrasing rather than a false accusation. RAG over external knowledge, never
over the user's own data.

---

## 3. Architecture

`application/analyze_match.py`, calling
`complete(task="match_analysis", schema=MatchAnalysis, prompt=…)`.

Sonnet, per docs/08 §3.2.3's assignment of *analyze* to Sonnet, resolved by task
name so it can move to Haiku without a code change.

This is the slice's **third `complete()` call site**. T096's guard, as amended,
is "no call site reacts to its own previous output" — this one does not.

### Scoring criteria are a named, versioned artifact

The rubric — how must-have weighs against preferred, what makes 80 rather than 60,
when a seniority mismatch caps a score — lives in one place and carries a version,
recorded on every analysis as `criteria_version`.

Without that, tweaking the rubric silently makes every historical score
incomparable, and docs/07 §3.2 says this capability is evaluated on **Match Score
calibration**. A calibration measurement across scores produced by different unnamed
criteria measures nothing.

Two slots exist for guidance the user is supplying separately:

- **Criteria** — weighting and banding rules. Prompt-level, versioned as above.
- **Vocabulary** — a canonical skill list with synonyms, so "K8s", "Kubernetes" and
  "container orchestration" collapse to one requirement. This sits with requirement
  extraction and is the direct fix for noise like `End-to-end Solutions` and
  `High-impact Systems` being counted as skills.

---

## 4. Data model

### `match_analyses` — one row per run, append-only

```
id, application_id
status            pending | ready | failed
error             text, set only when failed
overall_score     0–100
verdict           one-sentence summary
criteria_version
model, input_tokens, output_tokens, cost, is_fixture
created_at, completed_at
```

The row is written **`pending` in the same transaction as the application**, then
filled in by the background task. That is what makes the background run visible
rather than mysterious: the interface has something to show a spinner against, and a
failure has somewhere to record itself instead of leaving a blank forever.

Model metadata is written in the same transaction as the result — Principle V, as
the CV import already does.

Append-only because re-running after a profile edit must not destroy the previous
score. Calibration is measured over history.

### `match_requirements` — one row per requirement

```
id, analysis_id, ordinal
text
kind      must_have | preferred
verdict   met | partial | missing
evidence  quoted from the profile; null when missing
```

**Rows rather than a JSON blob**, because this is precisely what slice 007's Career
Advisor needs — *"count how often each skill is required, separate critical gaps
from nice-to-have"* (docs/07 §3.5). As rows that is a `GROUP BY`; as JSON it is
unqueryable and would have to be re-extracted from analyses already paid for.

`evidence` is the grounding mechanism. A `met` verdict must quote the profile;
`missing` has none by definition. That makes **AI-008 — never invent experience the
profile does not contain** — structural rather than hoped for, and it is what lets a
green chip be clicked to see why.

### The application gains a `requirements` column

A migration adds `requirements` and returns `job_description` to its plain
meaning — the full posting. Existing rows keep whatever they hold; re-adding a
job repopulates both. The Details tab keeps showing requirements as bullets, so
nothing changes on screen, with the full posting behind a disclosure.

### `applications.current_match_analysis_id`

Points at the analysis to display. One join for the table rather than one per row,
history preserved, and the displayed score has a single unambiguous source.

**It advances only when an analysis reaches `ready`.** On a first analysis it is
null and the interface shows `pending`. On a **re-run** it keeps pointing at the
previous `ready` row until the new one succeeds, so the score does not blank out
while re-running and a failed re-run leaves the last good score standing rather
than destroying it.

---

## 5. When it runs

Saving a job returns immediately and hands the analysis to a FastAPI background
task — in-process, fire-and-forget. Not a job queue: Redis is deliberately
unconfigured, and standing one up for a 12-second task is more infrastructure than
the feature warrants.

The score lands in the table roughly 12 seconds after the row does.

### Four states, which the interface must not conflate

| state | meaning | treatment (docs/09 §5) |
|---|---|---|
| `pending` | running | spinner |
| `ready` | scored | the score |
| `failed` | the call errored | solid `--color-failure` rule and the reason |
| *no requirements* | nothing extracted to score against | muted "nothing to score against yet" — **not** an error |

The last is real and has two causes: a job added manually with no description at
all, and a job whose posting yielded no requirements. Neither is broken, and neither
should be scored — an analysis against an empty requirement list would return a
number with nothing behind it, which is worse than no number.

### Re-running

Manual, from the tab. A profile edit makes every score stale, but silently
rescoring a hundred applications because a typo was fixed would be expensive and
surprising. Where `profile.updated_at` is newer than `analysis.created_at`, the tab
offers *"your profile has changed since this was scored — re-run?"*.

---

## 6. Interface

Match is the second tab, after Details:

```
Details │ Match │ Company ◦ │ Interview ◦ │ Versions ◦
```

Contents, in order: the score and one-sentence verdict; **WHY IT FITS** (met
requirements with their evidence); **WHAT'S MISSING** (must-haves first, then
preferred); and the full requirement list as chips with a coverage count (`11 / 38`).

**Missing chips are neutral, not red.** docs/09 §3 reserves red for things that
actually broke, and twenty-seven red chips is the "painting a third of the list red
makes an ordinary week look like a catastrophe" failure that same section warns
about. A missing requirement is ordinary. `✓` green, `≈` amber, `✕` neutral, with
the glyph carrying the meaning so it survives greyscale and colour blindness
(docs/09 §7).

The analysis is visibly AI-generated and carries its model and cost.

---

## 7. Testing

- **The seam is overridden**, as everywhere else: no test makes a provider call
  (FR-027).
- **Grounding**: a `met` verdict without `evidence` is a schema violation, asserted
  directly. This is AI-008's enforcement.
- **The four states render distinctly** — component tests, because "not scored yet"
  reading as "failed" is precisely the confusion docs/09 §5 exists to prevent.
- **Requirement rows survive to the API**, in the manner of
  `tests/integration/test_profile_content.py`: read the model's own columns and
  require every stored value to reach the response. That test found a fourth
  display bug on its first run during slice 003.
- **A failed analysis leaves the application usable** — the job is still recorded,
  the score is absent, and the record opens.

---

## 8. Cost

Sonnet 5 is $3 / $15 per MTok, with an **introductory $2 / $10 in force until
31 August 2026**. Both are given below because the difference is material.

The arithmetic is reconciled against a call that was actually billed — the
Greenhouse job extraction, 6,511 in / 131 out, charged **$0.014332**. At the
introductory rate that computes to $0.014332 exactly; at standard it would be
$0.0215. So the rate is confirmed and the token counts below are real.

Per job, scoring the whole posting against a 760-token profile:

| | input | output | today | after 31 Aug |
|---|---:|---:|---:|---:|
| Typical posting | 3,420 | ~1,500 | **$0.022** | $0.033 |
| Long posting | 5,560 | ~1,500 | **$0.026** | $0.039 |

A hundred applications is roughly **$2.20–2.60 today**, $3.30–3.90 after August.
Every job is scored on add, whether or not it is ever opened.

**Output is 57–86% of the cost**, because output tokens bill at 5× input. Two
consequences worth keeping in view:

* Moving from requirements-only to the whole posting — the change §1 records —
  costs about half a cent. The better score is nearly free; the expense is what
  the model *writes back*.
* The dominant output cost is the per-requirement `evidence` strings, quoting
  profile text the database already holds. **The first cost lever, when one is
  wanted, is to return a requirement index and a profile-item reference instead
  of quoting both sides back** — roughly halving output with no information
  lost, since both texts are stored and can be joined at render time.

A quick-score-then-detail split was considered and rejected: both variants read
the same input, so it saves nothing on the expensive half, costs more in total
if the tab is ever opened, and produces two independently generated numbers that
disagree with each other on one screen.

Other levers, none needed now: Haiku 4.5 at $1/$5 (untested here — worth a
measured comparison, not a blind swap), or scoring only on demand. Prompt
caching is **not** one: the profile plus prompt is ~1,060 tokens against Sonnet
5's 1,024-token cacheable minimum, so it barely qualifies, and input is the
minority of the bill regardless.

### `llm_model_match_analysis` must be set explicitly

`model_for_task` falls back to `llm_provider_model`, which is **Opus 5** at
$5/$25. A missing entry therefore runs this at **$0.065 per job — 2.5× Sonnet**,
silently and with no quality gain. This is not hypothetical: CLAUDE.md records
the same fallback catching CV extraction once already. The config line ships in
the same commit as the feature.

## 9. Sequencing

This is slice 004 work started before slice 003 closes. Slice 003 has 19 open
tasks, all of User Story 3 blocked on a JobTracker CSV export that only the author
can produce.

The dependency runs the right way — match analysis needs a profile (User Story 1,
built) and stored requirements (User Story 2, built) — so nothing is being built on
sand. It should be folded into slice 004's Spec-Kit specification rather than
becoming a fourth thing slice 003 quietly grew.

---

## 10. Open questions

- **The scoring criteria themselves** are being supplied separately and are not yet
  written. Until then the rubric is the model's own judgement, which is exactly the
  uncalibrated state §3 warns about. `criteria_version` exists so the first real
  rubric is distinguishable from that.
- **Whether a canonical skill vocabulary is needed for the first version**, or
  whether extracting requirements as written is good enough to start.
- **Whether Haiku 4.5 is good enough for this task.** It is half Sonnet's
  introductory price, and the task is structured and schema-validated — but the
  seam raises rather than accepting partial data, so a weaker model trades cost
  for extraction failures. Decide with a measured comparison once there are real
  analyses to compare, not before.
