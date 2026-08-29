# Tasks: Evaluation & Benchmark

**Feature**: `007-evaluation-benchmark` | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

> ## Four standing rules for this slice
>
> 1. **No paid call before Phase 7.** Phases 1–6 are free and must be complete and green first.
>    Phase 7 opens with an explicit approval gate. The runner refuses above the ceiling regardless.
> 2. **The $10 ceiling is a hard stop, not a budget to consume.** Projected total is **$7.97
>    expected / $9.13 conservative**. Every paid task records actual spend in the ledger at T042
>    before the next one starts.
> 3. **SC-008 (006) is `MISSED — 3.22% against ≤2%` in every artifact this slice writes.** This
>    slice's SC-008 is a *different criterion* and is labelled as one everywhere. T004 is the gate.
> 4. **Drill every gate.** A gate nobody has watched fail is not a gate, and a gate with nothing to
>    examine passes forever — this project has shipped four of those. **Assert the count of what you
>    examined**, and read the `N deselected` line.

**Approved budget (D3, 2026-08-29)**: $10 hard ceiling · 12 cases · 1 full paid pass · 5 SC-008
paired static arms · ~$6.11 expected / ~$7.03 conservative for the pass, plus ~$1.86/$2.10 for the
T057 arm.

---

## Phase 1 — Setup

- [x] **T001** Add the slice's configuration to `backend/src/careerhq/config.py`:
      `llm_model_eval_judge` (**Opus, set explicitly**), `eval_spend_ceiling_usd` (default **10.00**),
      and the active benchmark set version.
      *`model_for_task` falls back to `llm_provider_model`, which is also Opus — so omitting the
      judge entry would be **right by accident and wrong by process**, and the fallback is silent.
      A task with no entry is exactly how a node silently runs at 2.5× price elsewhere.*
- [x] **T002** [P] Add `benchmark-real/` to `.gitignore`, and **verify with `git check-ignore -v`**
      rather than by reading the file.
      *The mandatory pre-`add` check. This repository is public and has had two near-misses: real
      CVs in `testing files/` and 13 screenshots carrying real given names, both untracked and one
      `git add -A` from permanent publication.*
- [x] **T003** [P] Create `backend/benchmark/v1/` with a README stating the set version rule —
      **editing a case is a new version, never an edit in place** (FR-002).

---

## Phase 2 — Foundational *(blocking: every user story depends on these)*

- [x] **T004** **The SC-008 confusion gate.** Add `tests/unit/test_sc008_is_not_relabelled.py`:
      every file under `specs/007-evaluation-benchmark/` that mentions SC-008 (006) states it as
      **MISSED at 3.22% against ≤2%** and nothing else; every file mentioning both criteria labels
      them distinctly. **Assert the count of files examined** — a scan finding zero files passes
      forever.
      ***Drill**: change one file to say 1.68%, or to drop the `(006)` label from a heading. The
      test must name the file and the offending value.*
      *This exists because the project has a documented habit of a number quietly improving in a
      later document, and because 1.68% is a real, arithmetically-derivable, flattering figure that
      T052 explicitly declined to record. D1.*
- [x] **T005** Cost projection and the ceiling, in `backend/src/careerhq/application/evaluation/budget.py`.
      Projects from the **measured** per-task figures (research R1), reports the projection before
      any billable work, and **refuses above `eval_spend_ceiling_usd`** (FR-008, SC-011).
      *Free. No model call anywhere in this task.*
- [x] **T006** **Evidence separation.** Add `tests/integration/test_benchmark_touches_no_evidence.py`:
      after a fixture benchmark run, every pre-existing `tailoring_runs`, `resume_versions`,
      `match_analyses`, `exported_documents` and `submitted_resumes` row is byte-identical, and the
      run targeted the **synthetic** profile.
      ***Drill**: have the runner update an existing run's status. The test must name the table and
      the row.*
      *`HANDOFF.md` §5A: 8 versions, 13 runs, 8 analyses, 1 submission, **$3.562567**, and it is the
      project's only evaluation evidence. A test seeded against the real profile has already merged
      a fictional CV into it once.*
- [x] **T007** Create `backend/src/careerhq/application/evaluation/` and confirm
      `tests/unit/test_architecture.py::test_the_application_layer_imports_no_provider_sdk` now
      examines it. **Assert the module count it walked went up.**

---

## Phase 3 — User Story 1: a benchmark that runs the same way twice (P1)

**Goal**: one command, a fixed set, comparable numbers, and a harness that refuses to lie.

**Independent test**: two fixture runs produce identical case sets; every metric names its `n`;
asking for agent-quality metrics from a fixture run is **refused by name**.

### Refusal tests first — each one is written, watched failing, then satisfied

- [x] **T008** [P] [US1] `tests/unit/test_metric_reports_n.py` — a metric over zero cases returns
      *not measured*, never `0` (FR-020).
      ***Drill**: return `0.0`. The test must distinguish it from a genuine zero.*
      *`plan_adherence.emphasis_adherence` already returns `None` for this reason; the same
      distinction, enforced for every metric.*
- [x] **T009** [P] [US1] `tests/unit/test_harness_refuses_fixture_runs.py` — agent-quality metrics
      from a run whose calls came from `FixtureGateway` are **refused, naming the fixture gateway**
      (FR-030).
      ***Drill**: report anyway. The test must fail on the absence of the refusal, not on the value.*
- [x] **T010** [P] [US1] `tests/unit/test_harness_refuses_static_fallback.py` — a run configured for
      retrieval that fell back to the static rubric is refused, naming the fallback (FR-030).
      ***Drill**: empty the corpus and run. Retrieval falls back by design and records that it did —
      the harness must notice.*
- [x] **T011** [P] [US1] `tests/unit/test_harness_refuses_off_mix.py` — a run whose
      `model_config_used` differs from the shipping mix is refused, naming the differing task
      (FR-010, FR-030).
- [x] **T012** [P] [US1] `tests/unit/test_ceiling_refuses.py` — a run projected above the ceiling
      refuses **before any billable call** (FR-008).
      ***Drill**: set the ceiling below one run's projection and confirm zero calls were attempted,
      not merely that an error was raised.*
- [x] **T013** [P] [US1] `tests/integration/test_benchmark_refuses_real_profile.py` — a case pointed
      at anything but the synthetic benchmark profile is refused (FR-013).

### The benchmark set

- [x] **T014** [US1] Benchmark case loader and set versioning in
      `backend/src/careerhq/application/evaluation/benchmark_set.py`, per
      [data-model.md](data-model.md) §2.1–2.2. A missing or edited case is a **refusal**, not a
      warning.
- [x] **T015** [US1] Author the **12 synthetic cases** in `backend/benchmark/v1/` — **4 disciplines ×
      3 profile states** (FR-003, FR-005a, FR-005b). Fully synthetic; **no real personal data**
      (FR-039).
      *Precedent: `backend/tests/fixtures`, whose subject is fictional precisely so it can be
      committed.*
- [x] **T016** [US1] **Make the set hard enough to measure anything**, per research R8: vary the
      profile across cases rather than reusing one; include **at least one case where the profile
      genuinely does not cover a must-have**; include at least one case whose guidance needs differ
      sharply from the rest.
      *A benchmark on which the agent cannot fail measures nothing — and AI-008 has nothing to be
      tested against where there is no gap, because the temptation to fabricate only exists there.
      T013 (006) measured 13 rules for a backend posting and 12 for a nursing one with **1 in
      common**; twelve backend roles would never exercise that.*

### The runner

- [x] **T017** [US1] The runner in `backend/scripts/run_benchmark.py`, per
      [contracts/benchmark-run.md](contracts/benchmark-run.md): resolve set version → fingerprint
      the configuration → project and report cost → refuse above ceiling → **run each case through
      `create_pending_version` and `run_tailoring`** → record outcomes including failures.
      ***The shipping path, not a reimplementation.*** *A benchmark that reimplements the pipeline
      measures the reimplementation.*
      ***`run` (paid) is split from `report` (free)*** — the pattern
      `scripts/measure_retrieval_cost.py` established, so arithmetic can be re-checked and drilled
      without paying again (FR-032).
- [x] **T018** [US1] Result file writer.
      ***Built for the free report; the paid-pass writer waits on a pass to write about.***
      `report-existing` writes [`results/pre-benchmark-baseline.json`](results/pre-benchmark-baseline.json)
      and its readable companion, carrying the metric version, corpus identity, per-run outcomes,
      every refusal by name, and the denominator sample.
      Target shape → `specs/007-evaluation-benchmark/results/<run-id>.json`,
      carrying the full configuration fingerprint, per-case outcomes, per-metric values with `n`,
      actual spend, and the projection it was compared against ([data-model.md](data-model.md) §2.3).
- [x] **T019** [US1] The free `report` command: computes every metric from persisted records with
      **no model call**.
- [x] **T020** [US1] `tests/integration/test_benchmark_is_repeatable.py` — two fixture runs produce
      **identical case sets** and identical fingerprints. **Assert the case count examined.**
- [x] **T021** [US1] **Free-tier walkthrough in Docker**, per [quickstart.md](quickstart.md) §4:
      `run --gateway fixture` then `report`, and confirm the report **refuses** rather than
      producing a grounding number. **That refusal is the acceptance test, not a limitation.**
      *Verify in Docker, then read the output by eye. This project's suite has **never once** caught
      a display bug.*

**Checkpoint**: the harness runs, refuses correctly, and has cost nothing.

---

## Phase 4 — User Story 2: metrics, and a judge that is checked (P2)

**Goal**: every metric defined, drilled, and demonstrated over data that already exists.

**Independent test**: grounding, coverage, retrieval quality and adherence all produce numbers from
the **13 existing runs** with no new model call.

- [x] **T022** [P] [US2] `grounding` in `application/evaluation/metrics.py` per
      [contracts/metrics.md](contracts/metrics.md). Returns traceable proportion, `ungrounded` count,
      and **`persisted_ungrounded`, which is asserted to be 0** (FR-014, FR-015, SC-006).
      ***Drill**: flatten the severity split so an `ungrounded` proposal persists. The metric must
      name it.*
      *The Principle III release-blocker, made measurable. Two `ungrounded` findings exist in real
      data, so this has something to be a regression test of.*
- [x] **T023** [P] [US2] `coverage` — **two numbers, always together**: Reviewer-reported (free) and
      independently judged (paid subset), with **must-have coverage separate from overall**
      (FR-016, research R3).
      ***Drill**: an empty requirement list must report *not measured*, not 100%.*
      *Never collapse them. Coverage read only from `uncovered` findings measures the Reviewer's
      opinion and would report a Reviewer regression as an agent improvement — and the Reviewer has
      been wrong about coverage before, on Zipher, against bullets sitting untouched in the résumé.*
- [x] **T024** [P] [US2] `retrieval_quality` — **selected-rule relevance and pinned proportion as two
      figures** (FR-017). Over **≥10 postings across ≥3 disciplines** (SC-012).
      ***Free: no tailoring run and no paid call.*** *Retrieval is a local embedding plus a pgvector
      scan, p50 12.1 ms. The 15 always-pinned integrity rules are relevant by construction; rating
      the whole set would report a floor as an achievement.*
      ***This discharges SC-001 (006)***, which no slice-006 task records having performed.
      ***Filter on run `status`, never on the presence of `guidelines_used`*** — a failed run can
      carry guidance it never used.
- [x] **T025** [P] [US2] `adherence` — **reuse `application/plan_adherence.py` unchanged**, reported
      as a **distribution** (FR-019).
      *`de_emphasise` stays unmeasured: free text with no ids, and making it computable means
      changing the Plan schema and therefore the Plan prompt — a deliberate non-goal.*
- [x] **T026** [P] [US2] `calibration` — score versus rating, **reporting its sample size rather than
      implying one**, and requiring a single criteria version across the sample (FR-018).
- [x] **T027** [US2] Judge rubric **v1**, version-controlled, in `backend/benchmark/rubric/v1.md`
      (FR-023).
      ***It must not tell the judge how to distribute its answers.*** *"Most résumés are mostly
      adequate…" is the exact shape of phrasing that made a model push verdicts down to comply,
      measured in slice 004. Say what each level means; say nothing about how often it should occur.*
- [x] **T028** [US2] The judge in `application/eval_judge.py` — a **task name on the existing seam**,
      validated schema, **blind to which arm produced the output** (FR-022, FR-026, FR-040).
      Validation failure ⇒ the case is **unjudged**, the run continues.
      ***Every rule the schema enforces must be visible in the JSON Schema.*** *A
      `model_validator(mode="after")` does not serialise, and the schema is the whole contract the
      gateway sends. This project has shipped the other way round once.*
- [x] **T029** [US2] Judge call auditing — task, model, tokens, cost, on **both** the success and
      failure paths (FR-027, Principle V). *A judge call that failed was still billed.*
- [x] **T030** [US2] **Human-rating design — the smallest defensible one** (D8, research R6).
      Propose it in `specs/007-evaluation-benchmark/rating-protocol.md`: **pairwise for the
      regression question, plus a small absolute anchor set** so scores do not drift across rubric
      versions. **Justify the sample size from the judged-output count; do not assume one.**
      *The rule in place of a guessed number: the sample must be large enough that the agreement
      figure would change if the judge were random, and the figure is always reported with its `n`.*
- [x] **T031** [US2] Agreement statistic and **FR-025 labelling**: every judge score carries its
      agreement figure; an unvalidated judge produces scores labelled **unvalidated**.
      ***Drill**: report a judge score with no agreement measured. The label must appear.*
- [x] **T032** [US2] **Run every free metric over the 13 existing runs** and record the output in
      `results/pre-benchmark-baseline.md`. **Free — no benchmark, no paid call.**
      *8 succeeded (3 revised), 5 failed, 79 findings — 64 `uncovered`, 13 `overstated`, 2
      `ungrounded`. If the definitions cannot produce numbers from this, they are wrong before a
      cent is spent.*

**Checkpoint**: every metric is defined, drilled, and has produced a number. Still $0 spent.

---

## Phase 5 — User Story 3: did the change help (P3)

- [x] **T033** [US3] `compare` — per metric: before, after, delta, and whether the delta exceeds
      measured variation (FR-034). **Refuses, or names every differing dimension**, when
      fingerprints differ in more than the thing under test (FR-031).
      ***Drill**: compare two runs on different benchmark set versions, then two across a corpus
      edit, then two across a pricing change. Each must be named, not averaged over.*
- [x] **T034** [US3] **The noise floor, and its honest limit.** Establish run-to-run variation from
      the **free** tier (repeated fixture runs) and **report it as harness determinism only**
      (SC-001, FR-035).
      ***D3 approved one paid pass, so model variance is not measured.*** *The third pass in the
      plan's maximum tier was exactly this. Every comparison in T046 must state that its noise floor
      is unmeasured rather than compare against zero.*
- [x] **T035** [US3] Metrics-over-time report as a **committed file** (FR-036, FR-037).
      *Done 2026-08-29 — [results/metrics-over-time.md](results/metrics-over-time.md), four entries.
      **No UI built** (D7): every metric requirement is met by committed results plus slice 005's
      `GET /api/versions/{id}/run`, which was built to be read programmatically by this slice.*
      ***No UI in this slice*** (D7). Build the owner-only read-only page only if a later decision
      says the graded demo needs a screen rather than a document — and record that decision here if
      it is taken.

---

## Phase 6 — Persistence: justify, specify, do not implement

- [x] **T036** **Justify whether `tailoring_run_calls.duration_ms` is actually required.**
      *The case for: FR-029 and SC-010 close M-001's remaining half, which slice 006 carried forward
      by name; the row carries tokens and cost but **no timing**, so per-node latency is derivable
      only from a ~92 tok/s throughput assumption that is itself estimated across six runs.
      **The case against: nothing in this slice's success criteria fails without it** except SC-010,
      which exists only because M-001 was inherited.*
      **Record the verdict either way.** If it is required: nullable integer, **NULL means unknown,
      never zero**, no backfill (deriving a duration from a token count presents inference as
      record), written in `_record_usage` on **both** paths.
      *Not a timestamp pair: `func.now()` is transaction-scoped, so every call in one run would
      carry the same instant — the same trap that made `sequence` the ordering column.*
- [x] **T037** **Justify whether `tailoring_runs.benchmark_run_id` is actually required.**
      *The case for: FR-011 — 12 benchmark runs would swamp the 8 real ones in every statistic
      computed afterwards. **The case against: results are files, and a file already lists its
      cases** — so the id may be recoverable without a column.*
      *Rejected alternatives, recorded: inferring benchmark runs from the owning user (implicit,
      unenforceable, wrong the first time someone runs under the wrong account); a boolean
      `is_benchmark` (answers *whether* but not *which*, so two benchmark runs cannot be told apart
      — and telling them apart **is** the regression capability).*
      If required: nullable UUID, indexed, **referencing no table**, with a test asserting every
      non-NULL value has a matching result file — the constraint expressed where the data is.
- [x] **T038** **Specify migration `0019` and stop.** Write the intended schema into
      [data-model.md](data-model.md); **do not create the file**.
      ***`0019` is tentatively Slice 007's and `0020` is Slice 008's*** (author, 2026-08-29), so the
      two form a **chain from `0018` rather than two branches**. **Slice 008 must not create `0019`
      independently.** Ownership is confirmed in the implementation phase.
      *Two slices branching from `0018` is trivial in git and vicious in a deployed database:
      `down_revision` is a chain, not a set, and whichever merges second points at a revision that
      is no longer the head — surfacing at `alembic upgrade head` during a **pre-deploy**.*

---

## Phase 7 — Paid execution *(GATED — nothing here runs until T039 passes)*

- [x] **T039** **THE GATE.** Confirm, in writing, before any billable call:
      | Condition | |
      |---|---|
      | Phases 1–6 complete and green | ☐ |
      | Every drill in T004, T008–T013, T022–T024, T031, T033 **watched failing** | ☐ |
      | Free-tier walkthrough (T021) done in Docker | ☐ |
      | Free metrics produced numbers over the 13 existing runs (T032) | ☐ |
      | `eval_spend_ceiling_usd = 10.00` and T012 drilled | ☐ |
      | **Author's explicit go-ahead** | ☐ |
- [x] **T040** **Phase B — the one approved paid pass.** 12 cases, retrieval arm, shipping mix, plus
      **5 paired static arms**, plus 12 judged outputs. **Expected $6.11 / conservative $7.03.**
      Record the projection before, the actual after.
      *A pair costs **+1 run, not 2**: the retrieval arm is an ordinary benchmark run already
      counted.*
- [x] **T041** **The revised retrieval-overhead methodology** (FR-028, SC-008 *this slice*), per
      research R7.
      ***Module built, tested and drilled 2026-08-29 (`application/evaluation/overhead.py`, 12
      tests). The measurement is what remains, and it is the paid half.***
      ***A drill found a real error in it before any money was spent.*** The first implementation
      used only the `tailor_plan` delta as the numerator — the *clean control* — which **halves the
      overhead** and turned an unresolved measurement into a confident "below 2%". Retrieval
      replaces the guidance block in the **Draft** prompt too, and that call is billed for it just
      as Plan is; T045 and T052 both summed the two (+4,727 and +3,754, *of which* `tailor_plan`
      was +2,371 and +1,715). Corrected: `plan_share` now reports Plan's share so a diverging Draft
      is visible, and a pair with no Draft observation is flagged a **lower bound**.
      ***Verified against the real figures***: numerator 3,754 tokens over the measured
      $0.206268–$0.547891 denominator gives the interval **[1.37%, 3.64%]**, which straddles 2% —
      **`unresolved`**, exactly as the T052 evidence predicts.
      Report:
      - the **numerator** from the 5 paired `tailor_plan` input-token deltas, with its spread —
        near-deterministic, which is why 5 pairs is a design choice and not a corner cut;
      - the **denominator** as a distribution over the pass's 12 runs, **with its revision rate**;
      - the result as an **interval against a named denominator**.
      ***Straddling 2% is reported as *unresolved*, and that is a pass of this criterion*** — written
      that way so nobody is rewarded for hunting a denominator that resolves.
      ***`tailor_draft` corroborates and is not a second measurement***: it agreed with `tailor_plan`
      to 0.6% in the T045 pair and 18.9% in the T052 pair, because it also carries a differing plan.
      ***SC-008 (006) is restated nowhere except as MISSED at 3.22%.*** T004 enforces it.
- [x] **T042** **Spend ledger.** Record actual spend against projection in
      `results/spend-ledger.md`, and **true up the judge estimate** — $0.070 per output was modelled
      on `tailor_review` and is the only figure in the plan with no measurement behind it.
      **Phase C is projected from these actuals, not from the estimates.**

---

## Phase 8 — T057: the first controlled regression experiment

- [x] **T043** **The free, deterministic half — do it first.** Assert that after T057 the master
      block the model is shown contains the qualification for every Education item that has one.
      ***This is the sharpest evidence T057 works, it costs nothing, and it needs no benchmark.***
      *T057's defect is that the credential is **invisible** to the model: the profile holds
      `B.Sc. in Computer Science` and the item text says only `Ben-Gurion University`.*
      *The token delta is likewise free — rendered offline through the real prompt builder: **+16
      tokens, 1.07%** of the master block.*
- [x] **T044** **Implement T057** in `_render_master` and the export composition — Education and
      Language items carry their full stored content. *The richer composition already exists at
      `analyze_match.py:218`. No migration. Projects and Certifications have zero rows.*
- [x] **T045** **Phase C — the T057 arm.** Re-run the **6 affected cases** (those whose profile state
      carries Education or Language content) at the identical set version, configuration and corpus.
      **Expected $1.86 / conservative $2.10. No judge calls.**
      *A second full 12-case pass with judging would cost $10.67 expected — **above the ceiling
      before conservative assumptions**. That collision is recorded in [plan.md](plan.md); this is
      its resolution, not an economy.*
- [x] **T046** **The T057 comparison.** Before, after, delta, per metric — grounding, coverage and
      adherence, all free.
      ***State the expected result in advance so it is not shopped for***: +16 tokens is very likely
      below what 6 cases can resolve, so *"no measurable change"* is the probable and **correct**
      outcome. What the experiment delivers is a **bound** — *T057 changed no metric by more than X*
      — which is exactly the claim needed to land a deferred change safely.
      ***And it must say its noise floor is unmeasured*** (T034), never compare against zero.

---

## Phase 9 — Polish and cross-cutting

- [~] **T047** [P] The **gitignored real sanity set** (D2). Build `benchmark-real/`, run the same
      metrics, and **commit only the aggregate comparison**, labelled as coming from an
      unreproducible source (FR-005c, FR-005d).
      ***Built and provably isolated; deliberately unpopulated.*** `load_real_set()` loads it
      through the same code path as the committed set, `REAL_SET_DEFAULT_ROOT` puts it
      **outside the repository** (`~/CareerHQ-benchmark-real/`), `benchmark-real/` is gitignored as
      defence in depth — verified by `git check-ignore -v`, not by reading `.gitignore` — and
      `tests/unit/test_no_committed_pii.py` scans every committed benchmark file, asserting the
      count it examined.
      ***The remaining half is the author's, on the author's data.*** Populating it means copying a
      real CV — a home address, a phone number, an employment history — onto disk. Nothing in the
      non-paid phases needs it, and the comparison it enables spends no money.
      *It answers one question: **does the synthetic set overstate the system?** If synthetic scores
      materially better, the benchmark is flattering and T016's cases need hardening.*
      ***Re-verify with `git check-ignore -v` before any `git add`.***
- [x] **T048** [P] Full gates **on the host**: `ruff format`, `ruff check`, `mypy src`, `pytest` ≥80%,
      frontend `lint`/`typecheck`/`test`/`build`.
      *Backend gates never run in the container: `backend/.dockerignore` excludes `tests/`, so an
      in-container pytest collects nothing and looks like a pass.*
- [x] **T049** Update `CLAUDE.md` (durable gotchas only) and `HANDOFF.md` (status, spend, evidence).
      ***`CLAUDE.md` done, and T004 caught a live error in it.*** It recorded SC-008 (006) as
      **missed at 2.12%** — the pre-T052 figure, stale since the re-measurement. Corrected to
      **3.22%**, with the `SC-008 (006)` disambiguation rule added beside it.
      ***`HANDOFF.md` done at closure, by adoption rather than by editing in place.*** This
      worktree's committed copy was the older pre-deployment version (`298a45f`), so updating it
      would have produced a document that *looked* current while describing a superseded state.
      The primary worktree's uncommitted rewrite was copied in and then extended with §4A, the
      slice-007 state. **Nothing was written to the primary worktree**, so no Slice 008 work was
      disturbed — but **its copy still holds an independent uncommitted version, and the two need
      reconciling**. `HANDOFF.md` stays in the gate's `DISAMBIGUATION_DEFERRED` set for that
      reason: its many pre-007 mentions of SC-008 predate the second criterion.
      **Re-run T004 afterwards** — `HANDOFF.md` is outside `specs/` and is the most likely place for
      SC-008 (006) to be quietly restated. Extend T004's scan to cover it.
- [x] **T050** Read the first real benchmark report **by eye**, against real output.
      *This project's suite has **never once** caught a display bug — contact fields, bullet
      attribution, skill categories, project URLs and all twenty invisible buttons were each found
      by a person looking at real data.*

---

## Dependencies

```
Phase 1 (Setup) → Phase 2 (Foundational) ─┬→ Phase 3 (US1, P1) → Phase 4 (US2, P2) → Phase 5 (US3, P3)
                                          └→ Phase 6 (Persistence: justify only)

Phases 1–6 ALL GREEN ──→ T039 GATE ──→ Phase 7 (paid) ──→ Phase 8 (T057) ──→ Phase 9
```

- **Phase 2 blocks everything.** T004 in particular, because every later artifact could restate
  SC-008 (006).
- **US2 depends on US1** for the runner, but **T022–T026 and T032 do not** — they run over the 13
  existing runs and can start as soon as Phase 2 is green.
- **US3 depends on US2** for something to compare.
- **Phase 6 is independent** of the user stories and can run in parallel with Phase 3.
- **Phase 8 depends on Phase 7** for a baseline to compare against.

## Parallel opportunities

- **Phase 1**: T002, T003.
- **Phase 3**: T008–T013 — six independent refusal tests, six different files.
- **Phase 4**: T022–T026 — five metrics, five independent definitions.
- **Phase 6**: T036, T037 can be argued in parallel; T038 needs both.
- **Phase 9**: T047, T048.

## Implementation strategy

**MVP is User Story 1 plus T032** — a harness that runs, refuses correctly, and has already produced
metric values over 13 real runs, for **$0**. That alone satisfies *"metrics + analytics of success"*
and would be defensible if the budget vanished tomorrow.

**Then Phase 4**, still free. **Then, and only then, the gate.**

**Everything paid is 6 tasks out of 50.** That ratio is the design, not an accident: retrieval
quality is free, prompt-token deltas are free, every metric over existing runs is free, and the
harness itself is exercised on canned responses. The money buys exactly two things — output for the
judge to score, and the paired arms that pin the SC-008 numerator.

## Budget ledger

| | Expected | Conservative | Cumulative (cons.) |
|---|---|---|---|
| Phases 1–6 | $0.00 | $0.00 | $0.00 |
| T040 — 12 runs + 5 static arms + 12 judged | $6.11 | $7.03 | $7.03 |
| T045 — 6-case T057 arm, no judge | $1.86 | $2.10 | $9.13 |
| **Total** | **$7.97** | **$9.13** | |
| **Ceiling** | | | **$10.00** |
| **Headroom** | | | **$0.87** |

**$0.87 of conservative headroom is thin, and that is deliberate rather than overlooked.** Judging
the T057 arm would add $0.42–0.54 and take it under $0.50; it is excluded, and adding it is a
**separate approval**, never a judgement call made mid-run. If T040's actuals overrun, **T045
shrinks** — that is what T042 exists to decide.
