# Implementation Plan: Evaluation & Benchmark

**Branch**: `007-evaluation-benchmark` | **Date**: 2026-08-29 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md), with D1 and D2 approved by the author on 2026-08-29 and D3 pending
the cost estimate this plan owes.

> **Every figure in this plan that is called *measured* was read on 2026-08-29 from
> `tailoring_run_calls` and `tailoring_runs` in the local database, by a read-only query.** Every
> figure called *estimated* is arithmetic on top of those, and is labelled. No paid call was made
> to produce this plan.

## Summary

Build the instrument that says how well the tailoring agent works, and prove it on a real change.

**The slice is mostly a reader.** Four earlier slices wrote columns whose stated justification was
this one, so the metric layer is arithmetic over records that already exist — which is the cheapest
possible shape this late in the budget, and is why the free tier of this plan can go a long way
before any money is spent.

**Three things are genuinely new**: a committed synthetic benchmark set, a runner that drives the
shipping path across it, and a judge. Everything else is a definition, a report, or a refusal.

---

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript 7 / Next.js 16 only if D7's results view is
built, which this plan argues should be deferred

**Primary Dependencies**: no new runtime dependency. The judge is a task name on the existing
structured completion seam; the metrics are pure functions over SQLAlchemy models; the benchmark
set is version-controlled files loaded the way `backend/corpus/` already is

**Storage**: PostgreSQL 18 + pgvector, unchanged. **Two nullable columns proposed, no new tables** —
see *Persistence* below. Benchmark cases and results are **version-controlled files**, deliberately
not database rows

**Testing**: pytest (≥80% gate). `ScriptedSeam` for deterministic metric tests, `FixtureGateway`
for end-to-end harness plumbing — both free

**Target Platform**: Linux containers. **This slice runs locally, not in production** — the
evaluation evidence and the corpus embedding model both live locally

**Project Type**: Web application — `backend/` + `frontend/`

**Performance Goals**: none. Nothing here is on a user's path

**Constraints**: no paid call without a projection and an approved ceiling (FR-008); no metric
reported from a canned, fallen-back or off-mix run (FR-030); every benchmark input in the
repository free of real personal data (FR-039)

**Scale/Scope**: benchmark size is **D3, pending**. This plan supplies the arithmetic; the author
supplies the numbers

---

## What this slice reuses, and what it actually adds

### Reused unchanged — no new code, no new schema

| What already exists | What this slice does with it |
|---|---|
| `tailoring_runs.plan` | Plan-adherence input |
| `tailoring_runs.guidelines_used` — every guideline with source and content hash | Retrieval-quality input. Slice 005 wrote it for exactly this |
| `tailoring_runs.review_confidences` — every pass | Confidence-threshold calibration input (measured, not changed — D5) |
| `tailoring_runs.model_config_used`, `finalisation_rules_version` | The comparability fingerprint FR-031 refuses on |
| `tailoring_run_calls` — per call task, model, tokens, cost | Cost attribution, and the SC-008 numerator. **This is why `tailor_plan` is a clean control** |
| `reviewer_findings` — `ungrounded` / `overstated` / `uncovered`, each quoting its object | Grounding accuracy and requirement coverage |
| `resume_version_items` with `source_item_id` | Which proposals trace to which profile facts |
| `match_requirements` as rows, with `importance` and a verdict | Requirement coverage and match calibration |
| `application/plan_adherence.py` | Used as written. It was built for this slice by name |
| `complete(task, schema, prompt)` | The judge is a task name, not a new provider path |
| `FixtureGateway`, `ScriptedSeam` | The whole free tier |
| `build_guideline_source()` — the single `if` selecting static or retrieval | **The paired SC-008 arms already exist.** Nothing new is needed to produce them |
| `scripts/measure_retrieval_cost.py` | The pattern, not the code: paid `run` split from free `report` |
| `create_pending_version` / `run_tailoring` | The benchmark drives the shipping path. A parallel path would measure a system nobody deploys |

**The single most important reuse is the last one.** A benchmark that reimplements the pipeline
measures the reimplementation. Every case goes through the same use case a user's click goes
through, with the same model mix (FR-010).

### Genuinely added

| New | Why it cannot be reused from something |
|---|---|
| **A synthetic benchmark set** — postings paired with profile states, version-controlled | Nothing fixed exists. The thirteen real runs are thirteen different inputs |
| **A benchmark runner** — iterate cases, drive the shipping path, project cost, refuse above ceiling, record results | New behaviour: FR-006 – FR-013 |
| **Metric definitions** — grounding accuracy, requirement coverage, retrieval quality, match calibration | Arithmetic that does not exist yet, over data that does |
| **A judge** — a rubric, a validated schema, a task name, and a human-rated check | New model use. Needs `llm_model_eval_judge` set explicitly, or it silently falls back to Opus — right here by accident, and still not a reason to omit it |
| **A comparison report** — before, after, delta, versus noise | FR-034 – FR-037 |
| **Per-call duration** | M-001's remaining half. Records carry tokens and cost but **no timing** |
| **Refusals** — canned, fallback, off-mix, corpus drift, pricing drift, ceiling | FR-030 – FR-032, and the reason any of these numbers can be believed |

---

## How SC-008 (006) stays recorded as MISSED at 3.22%

**D1, approved. This section exists so the rule survives contact with implementation.**

1. **No artifact this slice writes may restate SC-008 (006) as anything other than
   `MISSED — 3.22% against ≤2%`.** It is missed; every restatement says so. Not the plan, not the tasks, not the results, not a report, not
   `HANDOFF.md`. The threshold is not touched and the miss is not re-derived.
2. **This slice's own SC-008 is a different criterion and is labelled as one everywhere it
   appears.** Where both are shown together, they are shown as two rows with two questions, never
   as an old figure and a corrected figure.
3. **The purpose is to evaluate the methodology, not the verdict.** What T052 exposed is that a
   fixed numerator over a denominator that swings 2.7× with revision count cannot resolve a 2%
   threshold. This slice measures *that*: the numerator's stability, the denominator's
   distribution, and what interval the pair implies.
4. **A gate enforces it.** `tests/unit/test_sc008_is_not_relabelled.py` asserts that no artifact
   states a value for SC-008 (006) other than the missed 3.22%, that a superseded figure is never
   given without the current one beside it, and that any file mentioning both criteria labels them
   distinctly. This project has a documented habit of a number quietly improving in a later
   document; the gate is cheaper than the habit.

**What the measurement can honestly conclude, stated in advance so the result is not shopped for**:
either the interval sits clearly above 2%, or clearly below, or it straddles. **All three are
publishable results**, and the third is the one the T052 evidence predicts. SC-008 (this slice)
counts *unresolved* as a pass precisely so that nobody is incentivised to find a denominator that
resolves.

---

## How the evaluation avoids paid-call waste

Four tiers, and **only the fourth costs money**. The ordering is the whole cost strategy: each tier
must be exhausted before the next is entered.

### Tier 0 — free, and it is where the metrics are actually developed

- **Thirteen real runs already exist** and are a real distribution to develop against: 8 succeeded
  (3 of them revised), 5 failed, and **79 reviewer findings — 64 `uncovered`, 13 `overstated`, 2
  `ungrounded`** (measured 2026-08-29). Every metric definition is written and drilled against
  these before a benchmark case is billed.
- **`ScriptedSeam`** gives deterministic unit tests of every metric.
- **`FixtureGateway`** exercises the runner end to end — projection, ceiling refusal, result
  recording, report generation — with nothing billed.
- **FR-030 is what makes this safe**: the harness refuses to *report* agent-quality numbers from
  any of it, so a free tier can never be mistaken for evidence.

### Tier 1 — free, and it is where most of the remaining questions are answered

**Retrieval is a local operation.** A query embedding plus a pgvector scan over 79 chunks — no
provider call, measured at p50 12.1 ms. Therefore:

- **Retrieval quality costs nothing.** SC-012's ≥10 postings across ≥3 disciplines can be retrieved
  against and judged for relevance without a single paid call. This also discharges SC-001 (006),
  which no slice-006 task records having performed.
- The same is true of corpus statistics, pinned-versus-selected proportions, and citation
  resolvability.

**This is the largest single saving in the slice** and it falls out of the architecture rather than
from cleverness.

### Tier 2 — free, and it is how prompt changes are costed

**The token delta of a prompt change is measurable offline**, by rendering through the real prompt
builder with no model call. T045 and T052 both did this. Consequently **T057's cost effect needs
zero paid calls** — it is already known to be +16 tokens, 1.07% of the master block. Only its
*quality* effect needs a model.

### Tier 3 — paid, and only where a model is the instrument

Three things, and nothing else:

1. **The benchmark passes** that produce tailored output.
2. **The judge**, scoring that output.
3. **The extra static arm** of each SC-008 pair.

**Five rules keep this tier small:**

- **One pass feeds every metric.** Grounding, coverage, adherence, latency, cost and judge input all
  read the same runs. No metric ever triggers its own pass.
- **The judge reads persisted output**, never a re-run.
- **A baseline is paid once and compared against many times.**
- **The benchmark's own runs are the SC-008 denominator sample.** Every benchmark run is a cost
  observation, so the denominator distribution is free. **Pairs are needed only to pin the
  numerator**, which is a near-deterministic input-token delta on a perfectly controlled call — so
  a small number of pairs is a design choice, not a corner cut.
- **Only the extra static arm is chargeable to SC-008.** The retrieval arm of a pair *is* an
  ordinary benchmark run, already paid for. A pair therefore costs **+1 run, not 2**.
- **A projection is reported and a ceiling refused before any billable work** (FR-008).

**Not claimed as a saving**: prompt caching. `docs/08` estimates ~20% off input from the stable
prefix a benchmark re-sends across cases, and that is plausible here — but it is unmeasured in this
project, so no figure below assumes it. If it materialises, every number below is an overestimate.

---

## T057 as the first controlled regression experiment

T057 is the only real, already-scoped, deliberately-deferred change available, and it was deferred
for exactly the reason this slice exists: *it changes what the model is sent*, and judging that
needs an evaluation rather than a token count.

**The experiment, in order:**

1. **Baseline pass** on benchmark version 1, retrieval arm, shipping mix. Paid once.
2. **The free half, first.** T057's token delta is rendered offline: +16 tokens, 1.07% of the master
   block. No model call.
3. **The deterministic half, also free — and it is the sharpest evidence.** T057's actual defect is
   that a qualification is *invisible* to the model: the profile holds `B.Sc. in Computer Science`
   and the item text says only `Ben-Gurion University`. So the direct check is a **presence
   assertion**: after T057, does the master block the model is shown contain the qualification for
   every Education item that has one? That is deterministic, free, and it is what proves the fix
   works. **A benchmark is not needed to establish that T057 did what it says.**
4. **T057 lands.**
5. **Re-run** the identical benchmark version, configuration and corpus. Only T057 differs — which
   FR-031's fingerprint check enforces rather than assumes.
6. **Report** before, after, delta, and whether the delta clears the SC-001 noise figure.

**The likely result is "no measurable change", and that is a correct result.** +16 tokens is far
below what a benchmark of this size can resolve on quality, and saying so now is the difference
between a finding and a disappointment. What the experiment then delivers is a **bound**: *T057
changed no metric by more than X*, which is precisely the claim needed to land a deferred change
safely. If instead a metric moves beyond noise, that is a genuine and unexpected finding about how
much the model does with a credential it can finally see.

**The regression capability is what is being demonstrated. T057 is the specimen.**

---

## Persistence: is a migration required?

**Two nullable columns. No new tables. Migration deliberately not created.**

### What genuinely needs schema

| Need | Requirement | Why a column |
|---|---|---|
| **Per-call duration** | FR-029, SC-010, M-001 | `tailoring_run_calls` records task, model, tokens and cost but **no timing**. Per-node latency is currently derivable only from throughput assumptions. Nothing outside the row can supply it |
| **Which benchmark run produced a tailoring run** | FR-011 | Benchmark runs write to `tailoring_runs` like any other. Without a marker, benchmark and user populations contaminate each other's statistics, and the alternative — inferring it from the owning user — is implicit, unenforceable, and breaks the moment someone runs a benchmark under the wrong account |

Proposed, and **not written**: `tailoring_run_calls.duration_ms` (nullable integer) and
`tailoring_runs.benchmark_run_id` (nullable). Both nullable because every existing row predates
them, and **NULL means unknown, never zero** — the same rule `review_confidences` already follows,
for the same reason: backfilling would present inference as record.

### What deliberately does *not* get a table

Benchmark cases, benchmark results, judge scores, human ratings and comparison reports are
**version-controlled files**, not rows.

**The argument is not tidiness, it is the project's actual failure mode.** Its entire evaluation
evidence — $3.562567 of it — lives in two local Docker volumes, with a backup that is on the same
machine and already behind. `HANDOFF.md` opens with that as a red-flagged risk. Putting this
slice's results in the same place would reproduce the problem knowingly. Files in git are backed
up by every clone, diffable, reviewable, and survive `docker compose down -v` — and a benchmark
result is a *record of an experiment*, which is exactly the kind of thing that belongs beside the
spec that defines it.

It also keeps FR-005 honest: a benchmark reproducible from version-controlled inputs cannot depend
on rows a person seeded by hand.

### Migration number — stop here

**Migration `0019` is not created.** Slice 008 is in progress in a parallel worktree and will
almost certainly want the next number too; `config.py` at HEAD already carries
`llm_model_research_synthesise_company`, so that slice has begun landing shared surfaces.
**Two slices claiming `0019` produces a merge conflict that is trivial in git and vicious in a
deployed database**, because a down-revision pointer is a chain and not a set.

The schema is specified in [data-model.md](data-model.md) and stops there, pending the author's
resolution of ownership with Slice 008.

### The results view (D7)

**This plan argues it should be deferred, not built now.** Every metric requirement (FR-014 –
FR-021) and every comparison requirement (FR-034 – FR-036) is satisfied by files plus the existing
`GET /api/versions/{id}/run` audit endpoint, which slice 005 built to be *"read programmatically by
slice 007"*. Only FR-037 — *see each metric over time* — argues for a page, and a committed report
with a table per run satisfies the course's *"metrics + analytics of success"* on its own.

**Recommendation**: keep FR-037 as a P3 story that is genuinely droppable, and build the owner-only
read-only page **only if** the graded demo needs a screen rather than a document. That decision can
be taken after the metrics exist, which is the point at which it is answerable.

---

## Estimated spend

**Measured inputs**, read from `tailoring_run_calls` where `is_fixture = false`, 2026-08-29:

| task | model | n | avg input | avg output | avg cost |
|---|---|---|---|---|---|
| `tailor_plan` | Sonnet 5 | 7 | 7,830 | 2,757 | **$0.043233** |
| `tailor_draft` | Sonnet 5 | 7 | 8,511 | 10,386 | **$0.120885** |
| `tailor_review` | Opus 5 | 9 | 7,958 | 2,016 | **$0.090196** |
| `tailor_revise` | Sonnet 5 | 2 | 8,109 | 3,617 | $0.052382 |
| `tailor_revise_escalated` | Opus 5 | 1 | 8,652 | 897 | $0.065685 |

**Measured run distribution** (`tailoring_runs`, succeeded, non-fixture): **n = 8, min $0.206268,
mean $0.343304, max $0.547891, and 3 of 8 revised — 37.5%**.

**Derived planning figures** (arithmetic on the above, not separately measured):

| | |
|---|---|
| Non-revising run — plan + draft + review | **$0.254314** |
| Revising run — + revise + a second review | **$0.396892** |
| Expected run at the measured 37.5% revision rate | **$0.307781** |
| **Planning figure used below** | **$0.31 expected / $0.35 conservative** (the measured mean) |

**Judge cost — estimated, not measured.** Modelled on `tailor_review`, which sees the same shape of
input (posting plus composed résumé) on the same model, with a smaller output because a rubric
score with brief justifications is shorter than a findings list: ~7,950 input at Opus $5.00/MTok
plus ~1,200 output at $25.00/MTok = **$0.070 expected / $0.090 conservative**. **This is the least
certain number in the plan** and the first thing the minimum run should true up.

### The three tiers

Case counts here are **illustrative shapes for the arithmetic, not a proposal** — D3 is the
author's. Each tier includes the paired observations the SC-008 methodology needs, priced at
**+1 run per pair**, since the retrieval arm is an ordinary benchmark run already counted.

| | Minimum viable | Recommended | Maximum regression pass |
|---|---|---|---|
| What it establishes | Every metric produces a defensible number once; the judge cost is trued up | The criteria as written, with a denominator sample worth reporting a variance over | A complete before/after cycle including T057 and the SC-001 noise figure |
| Benchmark cases | 6 — 3 disciplines × 2 seniority | 12 — 4 disciplines × 3 profile states | 12 |
| Paid tailoring passes | 1 | 1 | 3 — baseline, T057, noise repeat |
| Runs from passes | 6 | 12 | 36 |
| SC-008 extra static arms | 3 | 5 | 5 (once, not per pass) |
| Judged outputs | 6 | 12 | 24 — baseline and T057 |
| Retrieval-quality postings | 10 — **free** | 10 — **free** | 10 — **free** |
| **Expected spend** | **$3.21** | **$6.11** | **$14.39** |
| **Conservative spend** | **$3.69** | **$7.03** | **$16.51** |

Expected arithmetic: minimum `6×0.31 + 3×0.31 + 6×0.07`; recommended `12×0.31 + 5×0.31 + 12×0.07`;
maximum `36×0.31 + 5×0.31 + 24×0.07`. Conservative substitutes $0.35 and $0.09.

**Against the priors**: `docs/08` budgeted ~$26 for this slice (~$18 benchmark and regression, ~$8
judging); spend to date is **$3.562567**. The maximum tier lands at **roughly 55–63% of that prior**
and takes the project total to about **$18–20**. The prior is not a budget, and this plan does not
treat it as an approval.

### What D3 approved, and the one conflict it exposes *(2026-08-29)*

**Approved: a $10 hard ceiling, 12 cases, 1 full paid regression pass, 5 SC-008 pairs — expected
$6.11, conservative $7.03.** That is the *Recommended* column above, exactly.

**The conflict: a before/after needs two passes, and D3 approved one.** T057's evaluation is a
comparison, so at 12 cases both arms it would cost `24×0.31 + 5×0.31 + 24×0.07 = $10.67` expected —
**above the ceiling before conservative assumptions are applied at all.** This is a real arithmetic
collision between two approved items and it is recorded here rather than discovered at T057.

**Resolution, which costs nothing to state and would cost money to get wrong:**

1. **The T057 arm is a partial pass over the affected subset, not a second full pass.** T057 changes
   Education and Language item text, so it can only matter for cases whose profile state carries
   that content. Six cases.
2. **The T057 arm needs no judge calls.** T057's primary evidence is the **free deterministic
   presence assertion** — does the master block now contain the qualification. The benchmark's job
   is only to show it did not *hurt* grounding, coverage and adherence, and all three are computed
   free from records the run already writes.
3. **Phase C is projected from Phase B's actuals, not from these estimates.** After the baseline
   pass the real per-run cost is known; the T057 arm is sized against that number, and shrinks if
   the baseline overran.

| | Expected | Conservative |
|---|---|---|
| Phase B — baseline pass (12), SC-008 arms (5), judge (12) | $6.11 | $7.03 |
| Phase C — T057 arm (6 runs, no judge) | $1.86 | $2.10 |
| **Total** | **$7.97** | **$9.13** |
| Ceiling | $10.00 | $10.00 |
| Headroom | $2.03 | $0.87 |

**Judging the T057 arm is deliberately excluded** — it would add $0.42–0.54 and push conservative
headroom under $0.50. If it turns out to be wanted, it is a separate approval, not a judgement call
made mid-run.

**And one thing the single approved pass costs us, stated plainly**: SC-001 asks for run-to-run
variation measured on an unchanged system, which is a third paid pass. With one pass approved, the
noise figure is established from the **free** tier — repeated fixture runs prove harness
determinism, but they say nothing about model variance. **T057's comparison is therefore bounded by
an unmeasured noise floor**, and its report must say so rather than compare against zero.

**Three things would move these numbers**, stated so a surprise is not a shock:

- **A higher revision rate than 37.5%.** Every run that revises costs $0.396892 instead of
  $0.254314. If all 41 runs of the maximum tier revised it would come to **$17.95**, not $14.39 —
  a 25% overrun, and the single largest source of variance in the estimate.
- **The judge estimate being wrong.** It is the one figure with no measurement behind it. The
  minimum tier trues it up on 6 calls, at a cost of being wrong about ~$0.42.
- **Prompt caching**, which would push all of it down and is not assumed anywhere above.

**Nothing paid runs before D3 is approved.**

---

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design.*

| Principle | Assessment |
|---|---|
| **I — Profile is the single source of truth** | ✅ The benchmark uses synthetic profile states owned by a scratch user (FR-013). The owner's live profile is neither read nor written. A test seeded against the real profile has already merged a fictional CV into it once |
| **II — Human-in-the-loop** | ✅ The harness reads and reports; it applies nothing. Benchmark runs produce proposals and **never approve them** — every metric is computable from the composed résumé at review time, so no approval step is needed or taken |
| **III — Explainable and honest AI** | ✅ **Strengthened.** SC-006 turns the release-blocker into a measured fact: 0 `ungrounded` claims reaching a persisted proposal, across the whole benchmark. The severity split already enforces it; this is the measurement that would notice it stopping |
| **IV — Immutable history** | ✅ FR-012: the harness adds rows only. No existing run, version, analysis, export or submission is modified or deleted — including the $3.56 of evidence `HANDOFF.md` §5A protects |
| **V — AI is a platform capability** | ✅ The judge goes through `complete()` like everything else (FR-040), so `test_the_application_layer_imports_no_provider_sdk` continues to hold. Judge usage is audited (FR-027), and `llm_model_eval_judge` is set explicitly rather than left to fall back |
| **VI — Structured data first** | ✅ The judge's output is validated against a schema before use. Metrics are computed relationally from structured records, never parsed out of text |
| **VII — Test-first quality** | ✅ FR-033 requires every metric definition to be exercised by a test **that has been watched failing**. This is the load-bearing gate of the slice — see below |

**No violations requiring justification.** Complexity Tracking is omitted.

### The circularity problem, and the one thing that answers it

**Most of this slice's criteria grade the harness, and the harness grades itself.** SC-002 – SC-006
are absolutes about the harness's own behaviour, asserted by tests the same author writes.

This project has shipped **four** gates that examined nothing and passed cheerfully: a route
enumeration walking zero routes, a Tailwind scan of a theme that never existed, an AST walk finding
zero call sites, and a `-k` selector matching no tests. A measurement harness is the most dangerous
possible place for a fifth, because its output is a number people then believe.

**FR-033 is the answer and it is not optional**: every metric definition and every refusal is
drilled — break it, watch the test name the exact violation, restore. Concretely, the drills are:
report a metric with `n = 0`; hand the harness a fixture run and ask for grounding accuracy; point
a benchmark at the real profile; compare two runs with different finalisation rules versions;
compare across a corpus edit; start a run projected above the ceiling. **Each must fail loudly
before its task is ticked**, and each assertion must state the count of what it examined.

---

## Project Structure

### Documentation (this feature)

```text
specs/007-evaluation-benchmark/
├── spec.md              # Approved D1/D2; D3 pending
├── plan.md              # This file
├── research.md          # Phase 0 — metric definitions and the cost arithmetic
├── data-model.md        # Phase 1 — the two proposed columns, and the file formats
├── contracts/           # Phase 1 — metric, judge and benchmark-case contracts
├── quickstart.md        # Phase 1 — how to run the free tier without spending anything
├── results/             # Committed benchmark results — the evidence, in git
└── tasks.md             # Phase 2 — NOT created by /speckit-plan
```

### Source code

```text
backend/
├── benchmark/                          # NEW — the committed synthetic set (as backend/corpus/ is)
│   └── v1/                             #   versioned, because FR-002 makes an edit a new version
├── src/careerhq/application/
│   ├── evaluation/                     # NEW — metric definitions, pure functions, no provider import
│   ├── eval_judge.py                   # NEW — the judge, through the seam
│   └── plan_adherence.py               # REUSED as written
├── scripts/
│   └── run_benchmark.py                # NEW — paid `run` split from free `report`
└── alembic/versions/                   # NOT TOUCHED — migration number pending Slice 008

benchmark-real/                         # NEW, GITIGNORED — the D2 sanity-check set, never committed
frontend/                               # UNTOUCHED unless D7's view is approved later
```

**`application/evaluation/` must import no provider SDK**, so the existing import-graph test covers
it automatically the moment it exists.

---

## Phase status

| Phase | State |
|---|---|
| Phase 0 — research | [research.md](research.md) |
| Phase 1 — design | [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md) |
| Phase 2 — tasks | Not created. `/speckit-tasks` |
| **Blocked on** | **D3** — the ceiling and the case counts. Nothing paid, and no migration, before that |

## Post-design Constitution re-check

Re-evaluated after Phase 1. **No change**: the design adds no provider path, no new write surface on
user-owned data, and no table. The two proposed columns are additive, nullable and unbackfilled. The
one risk the design carries is the circularity above, and FR-033 is the control on it.
