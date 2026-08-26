# HANDOFF

**Last updated:** 2026-08-26 (§5B investigation recorded) · **Commit:** `e8075b3` · **Branch:** `005-resume-tailoring` (this file's update uncommitted)

> **Slice 005 — Resume Tailoring is 92 of 97, and the whole flow works end to end on real data.**
> Two real jobs have been tailored and approved, and a third real job scored **84/100 Strong**.
>
> **The five open tasks are all deployment and measurement** (T085–T089), not features. See §5A.
>
> **The next phase is deliberately not more prompt work.** Plan-to-draft adherence measured 0.5 and
> 0.167 across the only two successful runs, and two samples cannot justify tuning a prompt. §5B is
> a parallel-agent investigation of tailoring quality *before* any further agent change.
>
> **§5B ran on 2026-08-26.** Four parallel read-only investigators; findings recorded in §2a.
> Headlines: one **confirmed defect** — a revision silently erases the draft's decisions (§2
> concern 7) — and a prime suspect for the output-token overrun: adaptive thinking on
> unparameterised gateway calls. The proposed next phase is in §5 B: instrument, fix, then measure.
>
> **Phase 7 (T092-T094) is merged; T085 ran; the corrected plan-execution measurement is built and
> UNCOMMITTED.** See §5 F for the exact next decision. No paid run is pending.
>
> Measured this session: **468 backend tests** (83.86% coverage), **162 frontend**, ruff, mypy,
> oxlint, tsc and `next build` all clean.
>
> **17 commits unpushed on this branch; 7 on local `main`.** Nothing is at risk — see §5D.

This file is the volatile half of the project's memory: what is true *right now* and what to do
next. `CLAUDE.md` is the durable half — conventions, gotchas, and how the project works. When those
two disagree about status, **this file wins**.

---

## 1. Core goal

CareerHQ is an AI-powered career intelligence platform. A user imports a CV, tracks applications,
and an agent tailors the resume to a specific job description — **with the user's approval on
every change**.

Built solo as a course project on a four-to-six-week budget. Two things are graded requirements and
are not optional: **deployment** (slice 002, done) and the **evaluation harness** (slice 007, not
started).

The seven non-negotiable principles are in `.specify/memory/constitution.md`. Violations of II–IV
are release blockers.

### The roadmap was renumbered on 2026-08-22

Build order now matches slice numbers.

| | Slice | State |
|---|---|---|
| 005 | **Resume Tailoring** | **92/97 — built and exercised on real jobs; undeployed** |
| 006 | Document & Retrieval — RAG over guidelines, PDF export, submit-and-lock | Not started |
| 007 | Evaluation & Benchmark | Not started. **Graded** |
| 008 | Company Research | Droppable (`docs/08` §11) |
| 009 | Career Advisor | Droppable |

**Evaluation has been deferred twice and two slices stand in front of it.** If the budget runs
short, 008 and 009 are what get dropped. Recorded in `docs/05` §5.7 in those words.

**The 005/006 boundary is structural and must stay that way.** RAG is an *input enhancement* via
the `GuidelineSource` port, not a redesign of the tailoring workflow. Slice 006 swaps
`StaticGuidelines` for a retrieval implementation and changes nothing else — no node, no state key,
no finalisation rule. `application/guidelines.py`'s docstring is the argument; it also explains why
the port deliberately has no `top_k`, no scores and no embedding parameters.

---

## 2. Current implementation status

**Measured 2026-08-26, not copied:**

| Gate | Result |
|---|---|
| Backend suite | **468 passed**, 83.86% coverage (gate 80%) |
| Frontend suite | **162 passed** (12 files) |
| ruff format / check | clean |
| mypy strict | clean, 60 source files |
| oxlint / tsc / next build | clean |

| Slice | Tasks | State |
|---|---|---|
| 001 — Platform Foundation | 69 / 69 | Complete |
| 002 — Deployment | 52 / 52 | Complete |
| 003 — Data Foundation | 98 / 109 | US1, US2 done. **US3 blocked on a JobTracker CSV** |
| 004 — Match Analysis | 89 / 89 | Complete, verified in production |
| **005 — Resume Tailoring** | **92 / 97** | **Built and working on real data. See §5A** |

### Live system

**https://frontend-production-02ac.up.railway.app** — readiness reads
`database ok · cache not_configured · object_storage ok · ai_provider ok`.

**Nothing from slice 005 is deployed.** It lives on this branch.

### Real evaluation evidence — measured 2026-08-26

**`specs/005-resume-tailoring/research.md` R5 is authoritative** for the tailoring numbers and
labels which parts are measured and which are one reader's interpretation. This is the summary.

**Tailoring runs — four real ones, two successful:**

| Job | Run | Status | Rev | In | Out | Cost | Elapsed | Proposals | Findings |
|---|---|---|---|---|---|---|---|---|---|
| Cellebrite | `a76bd349` | failed | 0 | 0 | 0 | $0 | 4m00s | — | — |
| Cellebrite | `cd27b092` | failed | 0 | 30,028 | 21,641 | $0.361819 | 3m29s | — | — |
| Cellebrite | `2615363e` | **succeeded** | 0 | 34,888 | 15,512 | **$0.295450** | 2m50s | **4** | 7 |
| Zipher | `6356fb4e` | **succeeded** | **1** | 41,621 | 23,908 | **$0.464942** | 4m20s | **1** | 12 |

The two failures were the `source_item_id` defects; the first predates usage accounting, which is
why it records `$0` for calls it made.

**Against the targets — recorded, not adjusted:**

- **SC-006 ($0.30)**: met by Cellebrite at $0.2955 (1.5% headroom, on three calls of a possible
  seven); **missed** by Zipher at $0.4649 — **1.55×** — with a single revision.
- **SC-001 (90s typical / 3min full budget)**: **missed by both.** 2m50s and 4m20s.

**Plan execution — corrected 2026-08-26. `research.md` R5's newest subsection is authoritative;
the figures below are its summary.** The old single ratio (D0) counted a proposal *reverted* to the
owner's wording as executed, double-counted a duplicated planned id, scored label-kind targets it
could not measure, and reported a contaminated run's unknowable outcomes as failures. D0 is
preserved for comparison, not withdrawn.

| Job | D0 | D1 — Draft compliance | D3 — Plan effect | State vector |
|---|---|---|---|---|
| Cellebrite | 0.500 | **3/7 = 0.429** | **3/6 = 0.500** | 3 survived · 3 no_evidence · 1 label_kind |
| Harman | 0.286 | **3/7 = 0.429** | **0/5 = 0.000** | 2 reverted · 1 discarded · 2 no_evidence · 2 label_kind |
| Zipher | 0.167 *(historical)* | **not computable** | **not computable** | 1 survived · **5 unknown** |

**The two uncontaminated runs have identical Draft compliance.** The old 0.5-vs-0.167 spread must
**not** be read as evidence that the Draft behaved differently — the difference lies in what
happened after it. Zipher is contaminated by the pre-T094 Revise replacement defect: 1 determinable
of 6. **n = 3 and one is contaminated; this is not a claim about model behaviour in general.**

De-emphases planned → items dropped: Cellebrite 10 → 12 · Zipher 9 → **0** (the T094 defect) ·
Harman 10 → 9.

**Match analyses — 8, all `ready`:** Cognita 54 then 70 · Harman 85 · DriveNets 91 · Cellebrite 69 ·
Zipher 71 · **Voyantis 0 then 84 Strong**. Total match spend **$0.309312**.

### Known quality concerns — open, and deliberately not acted on

1. **Plan-to-draft execution is inconsistent.** 0.5 against 0.167, same profile, same prompts,
   different jobs. Zipher executed **one of six** planned emphases and **none of nine** planned
   de-emphases — so a resume for an autonomous-infrastructure role kept SVN, SqlDbx, PHP and
   Spanish. Whether this is a defect, a prompt weakness or ordinary variance **cannot be decided
   from two samples**.
2. **Output tokens are the cost lever and are larger than designed.** 15,512 and 23,908 across
   3 and 5 calls, far above the diff-shaped output the schemas intend. The run stores totals, not a
   per-call breakdown, so the cause is unknown.
3. **The sample is n=2.** No threshold, gate or prompt change may be justified from it. That is
   what slice 007 is for.
4. **`ReviewerFinding.attempt` is stamped with the run's final attempt**, not the pass that caught
   each finding — `run_tailoring` writes `result["attempt"]` to every row. The data cannot separate
   a first-review concern from a second-review one, and the interface's multi-pass marker therefore
   shows the same label on every finding of a run. Recorded in R5, not acted on.
5. **`de_emphasise` adherence is unmeasurable.** Free text, no ids. Making it measurable changes
   the Plan schema and therefore the Plan prompt.
6. **An in-flight run is invisible to other sessions.** `run_tailoring` flushes `REVIEWING` but the
   commit is at the end, so the interface shows "Writing" for the entire run and
   "Checking its own work" is never reached. FR-040's distinction exists in code and tests but is
   not delivered by the system.
7. **CONFIRMED DEFECT (found by §5B, 2026-08-26) — a revision erases the draft's decisions.**
   `TailoringState.items` has no reducer (`state.py:57`), so the Revise node's returned list
   *replaces* the draft's (`graph.py:94-97`) — while `_REVISE` rule 4 instructs "Return only the
   items you are changing". A delta contract, executed as a replacement. Measured: Zipher's final
   version has 1 proposal, **0 drops, 35/35 included**, while one of its own findings praises a
   "Big Data Concepts" drop that exists nowhere in the persisted version; Cellebrite (no revision)
   dropped 12. Found independently by two of the four investigators. **Still in current code.**
   Consequence: any drop or reorder the Reviser does not re-emit is silently lost — so Zipher's
   "9 planned de-emphases → 0 dropped" and its 0.167 adherence measure the post-revision wreckage,
   not the Draft node. Fix proposed in §5 B, not yet approved or implemented.

### 2a. What the §5B investigation established — 2026-08-26

Four parallel read-only investigators (Claude Code Agent tool, no worktrees needed — read-only),
one per open concern: plan-to-draft adherence, output-token anatomy, Review/Revise dynamics,
instrumentation gaps for slice 007. Constraints held and verified: no provider calls, SELECT-only
SQL, no file writes — `git status` clean at `e8075b3` afterwards. Every number below was measured
by an investigator this session (SQL against the local database, file:line reads, or re-running
`emphasis_adherence()` as a pure function). Full verbatim reports live in the session transcript;
this section is the durable record.

**Adherence (concern 1) — the numbers are right, the samples are not comparable.**

- The plan **does** reach the Draft model in executable form: every emphasis in both persisted
  plans carries a `source_item_id`, serialised into the prompt, with matching `[id: …]` anchors in
  the master (`prompts.py:238-244`, `tailor_resume.py:312-313`). Non-execution is not id plumbing.
- `emphasis_adherence()` re-run on the persisted plans reproduces 0.5 and 0.167 exactly — but the
  metric counts only *text rewrites of the exact planned item id*. Drops, reorders, and content
  absorbed into another item do not count. Cellebrite's 4/8 **double-counts a duplicate directive**
  (two emphases share id `cd5f3821`): distinct-item execution is 3/7 ≈ 0.43.
- **Both drafts absorbed unexecuted emphasis content into the summary rewrite** — Zipher's single
  proposal contains near-verbatim content of all five unexecuted emphases; Cellebrite's absorbs 3
  of 4. Exactly one emphasis in either run was ignored outright (Cellebrite's "C++ and Python as
  OOP languages", `13fc719c`).
- **Both runs predate `f1f5c7b`** (the diff-only-review fix) — Zipher finished 26 minutes before
  it was committed. Combined with concern 7, the 0.5-vs-0.167 comparison sets runs produced under
  different effective conditions against each other. **No post-fix run exists anywhere.**

**Output tokens (concern 2) — 86-88% of billed output is unaccounted for; prime suspect named.**

- Persisted model text ≈ 2,132 of 15,512 tokens (Cellebrite) and ≈ 2,804 of 23,908 (Zipher),
  chars÷4 estimate. Reconstructing full JSON with generous structural overhead still leaves a
  4-6× gap. The failed run `cd27b092` billed 21,641 output tokens and persisted **zero** model text.
- The gateway sends bare completions — no `max_tokens`, no `thinking`, no `effort`
  (`litellm_gateway.py`). Current API documentation: omitting `thinking` runs **adaptive thinking
  at default high effort, billed inside output tokens, never returned in content**.
- A cost-feasibility decomposition (Sonnet provably billed below list rate; solving the price
  constraint) localises ~12-14K of Cellebrite's 15.5K output on the **Sonnet plan/draft calls**.
- **Interpretation, medium-high confidence:** the unaccounted output is adaptive-thinking tokens,
  mostly on Sonnet. **Cannot be confirmed from persisted data** — no per-call usage survives
  (`UsageRecorder.calls` is summed and discarded, `tailor_resume.py:444-459`), and a ScriptedSeam
  replay cannot settle it. The T085 full-budget run can, if per-call usage is persisted first.
- Also billed and discarded: every `DraftedItem.reason` (schema-required, no column stores it),
  Zipher's entire draft output (concern 7), and all of a failed run's output.

**Review/Revise (concerns 4, and the revision's real story).**

- Zipher's 8 `uncovered` findings, cross-referenced item-by-item against the persisted 35 rows:
  **3 outright artifacts** of the diff-only bug (they name bullets "omitted entirely" that sat
  untouched in the resume), **4 genuine profile gaps** (Kubernetes/Spark/MLOps/FinOps/IDF — no
  master row supports them), **1 mixed**. Roughly half the uncovered volume was legitimate signal.
- The revision fired on **first-pass confidence < 70**, not on `ungrounded` — zero `ungrounded`
  rows exist in the entire table, and only ungrounded-or-confidence blocks (`finalisation_rules.py`).
  The first-pass confidence value is **permanently unrecoverable**: `state.confidence` has no
  reducer, only the final 76 persisted, and the backend container was recreated after the runs.
- The revision **did** its wording job: all three overstated claims it was told to fix were
  softened exactly as directed (verified quote-by-quote against the final text).
- Pass attribution: `reviewer_findings` has **no timestamp column**; ids are random; ctid preserves
  insertion order but not the pass boundary. Content constraints prove findings 1-3 are pass-1;
  placing findings 8-11 is **undeterminable** — including the case that all 12 came from pass 1.

**Instrumentation gaps (slice 007 readiness), the short map:**

- **Per-call usage:** capture-side complete (`UsageRecorder.calls` holds per-call model/tokens/
  cost), storage-side absent — summed then discarded. `Usage` also has no task label, so even
  persisting it as-is could not name the node except by model inference.
- **Per-pass findings and confidence:** destroyed *upstream* of persistence — the state schema has
  no attempt field and `confidence` is overwritten per pass. A write-time fix alone cannot work.
- **Observability:** `run_tailoring` contains zero commits; the only commits are in the API layer
  before and after the run. `REVIEWING` is never observable (concern 6 confirmed at file level);
  Plan/Draft/Revise phases are not in the status vocabulary at all.
- **Prompts are entirely unversioned and unpersisted** — zero version constants in `prompts.py`;
  no run column stores a template version. The biggest regression-attribution gap for slice 007:
  after any prompt edit, historical runs are indistinguishable from current-prompt runs. Contrast
  the exercised precedents: `match_analyses.criteria_version` (data shows `v2-importance` →
  `v3-earned`) and `finalisation_rules_version` per run.
- **Metric readiness:** grounding accuracy best-served (structural `source_item_id` traceability +
  per-item text snapshots); requirement coverage computable only by judgement, not join (every
  requirement↔content link is free text); calibration has no human-rating store and n≈1 approval
  data; **regression delta most blocked** (prompt identity, per-call models, and run-time input
  snapshots all missing — posting and profile are read live and mutable).
- Smaller absences, recorded: job-URL extraction usage persisted nowhere; retry deletes the prior
  attempt's item rows; failed runs persist only totals plus an exception class name.

**Permanently unanswerable for the existing four runs** (information destroyed in state before
persistence): Zipher's first-pass confidence, the pass attribution of its findings beyond 1-3, and
what its Draft node actually returned.

### What is NOT built

- **Slice 005 is not deployed** (T088, T089).
- **The full-revision-budget path has never run** — seven calls, three Opus reviews. It is the path
  SC-006 is most likely to be broken by, and T085 asks for both paths.
- **FR-017 has no test that answers it** — whether a tailored resume claims anything the owner did
  not do is a judgement a person has to make (T087).
- **An approved version is not rendered as a document.** Deliberate: slice 006. See CLAUDE.md
  → *Deliberate non-goals*.

---

## 3. Files modified

Slice 005 spans `f414caf..db89a26`. Regenerate with:

```bash
git diff --name-status f414caf~1..HEAD -- backend/src frontend/src
```

### Read these first

| File | Why |
|---|---|
| `specs/005-resume-tailoring/contracts/tailoring-workflow.md` | O1–O8. The LangGraph/CareerHQ boundary, and the test of it |
| `backend/src/careerhq/application/tailor_resume.py` | The use case: preconditions, execution, finalisation, persistence, the reaper |
| `backend/src/careerhq/application/finalisation_rules.py` | The severity split, versioned. Where Principles II and III are reconciled |
| `backend/src/careerhq/application/guidelines.py` | **The 005/006 boundary.** Read before touching slice 006 |
| `frontend/src/components/applications/tailor-tab.tsx` | The five states, and why each is distinct |
| `backend/src/careerhq/application/scoreability.py` | The single answer to "is there a posting to read", used by Match **and** Tailor |
| `backend/src/careerhq/application/agents/tailoring/prompts.py` | `compose_resume()` and the four prompts. Read before touching any of them |
| `specs/005-resume-tailoring/research.md` §R5 | **All the real measurements**, with measured facts and interpretation kept apart |

### Backend source

```
NEW  api/routes/tailoring.py                (the six routes)
NEW  application/tailor_resume.py           application/finalisation_rules.py
NEW  application/guidelines.py              (GuidelineSource port + static rubric)
NEW  application/agents/tailoring/{graph,state,prompts,__init__}.py
NEW  domain/models/tailoring.py             domain/schemas/tailoring.py
MOD  config.py                              (five llm_model_tailor_* entries)
MOD  ports.py                               (T081 — the docstring was describing slice 004)
MOD  main.py                                (router registration)
MIG  0010_resume_versions · 0011_version_items_and_findings
NEW  application/scoreability.py            (scoreable_posting — Match + Tailor)
NEW  application/plan_adherence.py          (emphasis_adherence — measurement, no gate)
MOD  application/ports.py                   (UsageRecorder, safe_validation_errors)
MOD  application/analyze_match.py           (scoreability guard + prompt agree)
MOD  api/routes/applications.py             (is_scoreable, _latest_analysis, _state_of)
```

### Frontend source

```
NEW  components/applications/tailor-tab.tsx        tailor-diff-item.tsx
MOD  lib/api.ts                     (six calls; ApiError now carries the unflattened detail)
MOD  components/applications/detail-tabs.tsx       (the Tailor tab)
MOD  app/applications/[id]/page.tsx (removed the stale disabled "Tailor CV" button)
MOD  app/globals.css                (**the shadcn token bridge — see §4**)
```

### Tests

```
NEW  backend/tests/support/{scripted_seam,tailoring_fixtures,__init__}.py
NEW  backend/tests/integration/test_tailoring_api.py         (25)
NEW  backend/tests/integration/test_tailoring_ownership.py   (10)
NEW  backend/tests/integration/test_tailoring_workflow.py    (15)
NEW  backend/tests/integration/test_tailoring_{preconditions,reaper,schema,concurrency}.py
NEW  backend/tests/integration/test_{owner_data_untouched,version_immutability,version_status_transitions}.py
NEW  frontend/src/components/__tests__/tailor.test.tsx       (30)
NEW  frontend/src/components/__tests__/tailor-findings.test.tsx (7)
MOD  backend/tests/integration/test_auth.py  (**the enumeration was checking zero routes**)
MOD  frontend/src/components/__tests__/tokens.test.ts (a Tailwind theme-colour gate)
```

---

## 4. What failed

The expensive part of this project's memory. **Append-only — never delete an entry.** Each of these
was tried and did **not** work; re-attempting any of them costs real time.

### Gates that were not gates (slice 005 — three of them, all shipping green)

- **`app.routes` stopped containing included routers.** FastAPI 0.141 wraps them as
  `_IncludedRouter` objects with no `path` attribute at all. `test_every_non_public_route_requires_a_session`
  walked `app.routes` and skipped any path containing `{`, so it matched only `/api/docs` and
  `/api/openapi.json` — both public, both skipped. **The gate was examining zero routes and
  passing**, and had been since slice 003 added the first parameterised route. Enumerate from
  `app.openapi()["paths"]`, which is what a client can actually reach, **and assert how many you
  examined** — the count is the only part that would have caught either failure.
- **An undeclared Tailwind theme colour generates no rule and no warning.** `src/components/ui/` is
  shadcn, written against `bg-primary`, `bg-accent`, `border-input`, `ring-ring`. None were declared
  in `@theme`, so `bg-primary` computed to `rgba(0, 0, 0, 0)` and **all twenty default `<Button>`s
  in the application rendered as bare text**, for three slices. It survived a passing build, tsc,
  lint, 130 tests and the existing `var(--token)` scan, because none of them ask whether a class
  name *resolves*. It survived human use because `outline` and `ghost` are *meant* to be
  transparent — two variants of three looked perfect. Found by opening the Tailor tab in a browser.
  `@theme inline` is required, not `@theme`, or the values freeze at compile time and dark mode
  never applies.
- **A `-k` selector that matches nothing reports a cheerful pass.** Drilling the disclosure gate
  with `-k leak` selected **zero** tests and printed no failure; it read as "the drill did not
  fire". The test name did not contain "leak" — a fixture argument did. **Read the
  `N deselected` count**, always.

### Slice 005 — the two paid failures, and what each cost

Both were the **same field** and **different root causes**, one below the other. Re-reading them in
order is the cheapest way to understand why the id plumbing looks the way it does.

- **Fixing a contract's *visibility* when the value never existed.** The first failure was
  `ReviewFinding` requiring `source_item_id` while the JSON Schema advertised it optional — real,
  and fixed by putting the rule in `Field(description=...)`. The second failure was the same
  field: the ids **never entered the prompt chain at all**. `_render_master` returned `(text,
  items)` and only `text` reached the state, so Draft was told to return items "by id" while being
  shown 2,801 characters of profile and zero ids. Cost: **$0.361819** for the second failure alone.
  The quieter consequence was worse — with no ids nothing maps back, so a run that *passed* review
  would have persisted a diff with **zero proposed changes**.
- **Believing a fix was complete because the layer I could see was fixed.** The lesson is not
  "check the prompt"; it is that a diagnosis which explains the symptom is not necessarily the
  bottom of the stack.
- **Showing the Reviewer the diff and asking a document-level question.** `uncovered` asks what the
  *resume* fails to address; it was handed only the changed items. On Zipher it reported eight
  requirements "never addressed" against bullets sitting untouched in the resume, naming the exact
  ids it believed had been omitted. That is what drove the run into a revision, and to $0.46.
- **Two of my own tests were wrong, both caught only by drilling.** One demanded a rewritten item's
  *original* wording, which another test correctly forbade. The other searched the whole prompt for
  text the master also contains, so it passed with the fix reverted.
- **Collapsing two questions into one guard.** Making `scoreable_posting` the sole gate for Match
  broke FR-006: a description with an empty requirement list became scoreable. "Is scoring
  meaningful" and "is there anything to send" are different questions. The existing suite caught it.
- **Asserting an equivalence where only an implication holds.** Content is *necessary* for an
  analysis to be reserved, not *sufficient*. Asserting `==` hid the FR-006 break for one commit.

### Slice 005 — the agent runtime

- **Assuming a LangGraph state key accumulates.** It does not. A key with no reducer is
  **overwritten**, measured against the installed 1.2.11. Applied to `usage` that keeps **one**
  record out of seven — an incomplete audit under Principle V, a cost figure wrong by up to 7×, and
  *nothing raises*. `Annotated[list, operator.add]` is required.
- **Believing the import guard covered the application layer.** It forbade exactly one package,
  `litellm`. Adding LangGraph made it actively worse: `langchain-core` arrives transitively, so
  `langchain_anthropic` became one install away, and the idiomatic LangGraph example binds a model
  *inside the node*. Now six packages.
- **Believing anything asserted "no call site loops".** Nothing executable ever did, and as of this
  slice the claim is **false** — the graph loops by design. Corrected in `ports.py` and `CLAUDE.md`
  (T081, T082). The real guard is the import-graph test.
- **Thinking the checkpointer could be avoided.** `langgraph-checkpoint` is a hard transitive
  dependency. What is declined is `langgraph-checkpoint-postgres`, a **separate** package.
- **`dataclasses.replace()` on a Pydantic model.** `DraftedItem` is a `BaseModel`; use
  `model_copy(update=...)`.
- **A table-driven loop over `(model, kind, accessor)` tuples** in `_render_master`. Three lines
  shorter and completely untypeable. Written out explicitly.
- **`TailoringRun.__new__()` to build an unsaved instance.** Bypasses SQLAlchemy's instrumentation;
  the first `setattr` fails with `'NoneType' object has no attribute 'set'`.
- **A module-level `pytest.mark.asyncio`** in a file that is half pure functions. It fails the sync
  tests outright — and warns rather than fails when the function is `async def` but not awaited.
- **`session.expire_all()` before re-reading.** The next attribute access does IO synchronously,
  which async SQLAlchemy answers with `MissingGreenlet`. Use an awaited `session.refresh(obj)`.
- **`json.load` in strict mode against the GitHub Actions API.** Control characters in commit
  messages break it. `strict=False`.
- **A delta contract executed as a replacement** (found by §5B, 2026-08-26). `_REVISE` instructs
  "Return only the items you are changing"; `state.items` has no reducer, so the Reviser's partial
  return *replaced* the draft's list and silently erased its drops — see §2 concern 7. The same
  reducer lesson as `usage` above, missed on a second key: any LangGraph state key a later node
  returns *partially* must either carry a merge reducer or be proven whole.

### Slice 005 — the routes and the interface

- **`is` against a `String`-column enum, again.** `approve_version` compared
  `item.decision is ProposalDecision.PENDING`. Items loaded by a route come from a session that did
  not write them, so `decision` is a plain `str` and the branch never fired: **approval silently
  accepted nothing.** This is the identical defect slice 004 shipped in `run_analysis`, invisible
  for the identical reason — the existing tests hold the session that created the row. Use `==`,
  and exercise the path through a second session.
- **Returning the stringified exception to the client.** `run_tailoring` wrote
  `f"{type(exc).__name__}: {exc}"` into two columns that two endpoints return verbatim and the
  interface renders in an alert, while logging only the class. **The detail went to the browser and
  the type went to the operator** — inverted from the T068 rule in `health.py`. A
  `psycopg.OperationalError` stringifies to the internal IP, port and database user. Found by T090.
- **A data-modifying CTE's INSERT is invisible to an UPDATE in the same statement.** Linking a
  freshly-inserted `tailoring_run` back to its `resume_version` inside one `WITH` chain matched
  **zero rows** and reported success — the UPDATE's targets come from the snapshot taken before the
  statement ran. Two statements.
- **Drilling a test can hit a database constraint before the assertion.** T064's first drill —
  misattributing a finding to an arbitrary row — was refused by
  `ck_reviewer_findings_uncovered_has_no_item`. A stronger answer than the test was asking for, but
  it does not drill the test. Flattening the attachment to `None` is the realistic regression.
- **A Python replace-script that asserts before writing drops *all* edits when one string does not
  match.** The `tasks.md` ticks for T083/T084/T090 were silently lost while the code commit went
  through, because a single em-dash phrase differed. Write each edit independently, or verify the
  file afterwards.
- **A stale "not built yet" marker is worse than a missing one.** The detail header carried a
  disabled `Tailor CV` button titled "arrives in the next release", directly above the working tab.
  The original reasoning — a button that looks live and does nothing is worse than one admitting it
  is not ready — was right while it was true.

### Slice 005 — assumptions about existing code that were wrong

- **`MatchAnalysis` has a `profile_id`.** It does not; only `application_id`.
- **`Application.current_analysis_id`.** It is `current_match_analysis_id`.
- **`MatchRequirement.text`.** The column is `text`, the Python attribute is **`text_`**.
- **A new `ItemDecision` enum.** `provenance.ItemDecision` already exists for the import reviewer.
  The tailoring one is `ProposalDecision`, and the vocabularies differ for a real reason: import
  review *discards*, tailoring *rejects* (the owner's wording stands).
- **`api/routes/__init__.py` is where routers are registered.** It is empty; every router is
  included in `main.py`'s `create_app`.

### Slice 004 — match analysis (every one passed a green suite)

- **`is` against an enum on a value read from the database.** See above; it recurred this slice.
- **A lazy relationship on a freshly added object** raises `MissingGreenlet` as a 500 when
  serialised. Assign collections at construction; the routes need `selectinload`.
- **Demanding a `shortfall` on `unverified`.** A real completion failed validation and the model was
  right: the profile's silence gives no basis for choosing one. The same trap was avoided in advance
  in slice 005 — an `uncovered` finding carries no item reference, enforced by a check constraint.
- **Reporting a cap that did not bite.** `capped_by` named a requirement whenever one *could* cap.
- **`var(--fg)` where the token is `--foreground`.** An undefined custom property fails silently and
  differently per property; three uses were `color:` and looked right by accident, the fourth was
  `fill:` and rendered black on a dark ground.
- **Building a CSS reveal the natural way round.** Reduced motion collapses animations to 0.01ms, so
  a base of "empty" plus an animation that fills it shows **zero** to everyone who reduces motion.
  **Slice 005 needed the rule the opposite way round**: the tailoring spinner has no value yet, so a
  full ring resting still would read as a finished run and an empty one as a failure. It rests on a
  quarter arc and the step name carries the meaning.
- **Trusting `drop_all` against an existing test database.** It emits from the *metadata*, not the
  database. `conftest.py` drops the schema. A `use_alter` constraint must also be **named**.
- **Assuming a stuck run could be recovered.** The in-flight guard answered 409 to the one action
  that recovers it. Hit three times, each needing SQL by hand.
- **Estimating output tokens.** R8 projected ~1,500 and measured **2,811** — 87% low.
- **A score computed independently of the thing it summarises.** v2 asked for four abstract
  dimensions; a real job returned eight requirements addressed and a score of 48 against an honest
  84.
- **Telling a model how to distribute its answers.** *"Most real profiles are mostly `partial`…"*
  made the model push verdicts down to comply.

### Testing (all slices)

- **Trusting the suite to catch display bugs. It never once has.** Contact fields, bullet
  attribution, skill categories, project URLs, and now every button in the application — all found
  by a person looking at real data.
- **`create_all` against an existing test database.** It does not reconcile an existing table.
  `conftest.py` drops the schema first. **Any test that asserts an absence must be watched failing.**
- **Asserting an absence against the wrong scope.** "No rejected toggle on the form" passed against
  a form that had one, because Radix renders dialogs into a portal and `container` was empty.
- **A test double that repeats its last answer.** Would make an unbounded loop look convergent.
  `ScriptedSeam` raises instead.
- **A guard with nothing to examine.** `test_task_model_config.py`'s first AST walk found **zero**
  call sites. Without its own `assert used`, it would have passed forever while checking nothing.
  Three more instances of this class shipped in slice 005 — see the top of this section.
- **Running a test against the real profile.** It merged a fictional CV into it and replaced the
  contact block. **Always use a scratch user**, seeded `@example.com` — pydantic's `EmailStr`
  rejects `.test`/`.invalid` and the 500 reads as a white-screen app bug.

### Deployment

- **`railway deployment redeploy` as a rollback.** It redeploys the *latest* deployment. A rollback
  also creates a **new** id carrying the **old** commit, so read which version is live from the
  commit.
- **Reading Railway logs for a message string.** Railway **blanks the `message` field** of parsed
  JSON logs. Put anything needed to debug production in `extra={…}` fields. This is why T090's fix
  puts `str(exc)` in `extra`, not in the message.
- **`nc -z` to test whether the database was exposed.** The shared proxy edge accepts connections
  regardless. Speak the protocol and include a control.
- **Trusting a green health check to mean the proxy works.** The frontend's check probes `/`, which
  never traverses `/api/*`. **Three separate proxy misconfigurations all deployed green.**
- **Secret-scanning logs for a low-entropy password.** `careerhq` collides with the project name in
  2000 log lines.

### Reading job postings

- **Returning early on schema.org `JobPosting` metadata.** Wrong twice: 1,591 characters of company
  blurb against 9,447 on the page including the requirements.
- **Asking the model to retype the description.** 52 seconds and a proxy timeout, against 5.4s for
  metadata only. **Never ask a model to echo back text you already have.**
- **Reading a page that ships its own template.** Client-rendered boards serve `{{position.name}}`.
  Refuse, do not read.
- **A generic fetch for Comeet.** Needed a vendor adapter.
- **Assuming LinkedIn needs special handling — wrong, repeatedly.** A plain fetch returns 200.

### Product decisions tried the other way first

- **A `rejected` boolean beside the status.** There is no `rejected` column and its absence is a
  release blocker.
- **One overwritten date field.** `date_added` and `date_applied` are separate.
- **Labelling `EXTRACTED` provenance.** Every fact carries it, so the label said nothing. **The same
  reasoning governs the finding-attempt marker in slice 005**: it appears only when an item was
  flagged in more than one review pass.
- **A second render path for grouped skills.** It cost an affordance every time — Edit, then Add,
  then Remove each went missing. **This is why T077 was amended**: Edit is a peer of Accept and
  Reject rather than a field revealed by rejection, so there is one render path.

---

## 5. Exact next steps

### A — Deploy and finish the measurement · **owner: the author** · T085–T089

The remaining five tasks. **T085 is half done**: the first-pass-clear path is measured (Cellebrite,
$0.2955) and the **full-revision-budget path — seven calls, three Opus reviews — has never run**.
That is the path SC-006 is most likely to be broken by; Zipher already missed it at 1.55× with one
revision.

T086 is bookkeeping on numbers already in R5. **If a target is missed, mark it missed in `spec.md`**
rather than adjusting it — slice 004 did exactly this with SC-004. T087 is not automatable: read a
tailored resume as a person and ask whether it claims anything the owner did not do.

T088/T089 deploy and verify on Railway. The `PGHOST=localhost PGPORT=5432` override is **not
optional** — see CLAUDE.md.

### B — §5B investigation **done 2026-08-26**. Proposed next phase: instrument, fix, then measure

> **Delivered.** Steps 1-3 (T092-T094) are merged and step 4 (T085) has run. **See §5 F** for
> current state and the live decision; this section is kept as the record of what was proposed.

The investigation ran as four parallel read-only agents; findings are §2a, and the Revise
overwrite is now §2 concern 7 — a confirmed defect. **The proposed phase below is recorded, not
approved; nothing has been implemented.**

The order is load-bearing: instrumentation lands first so the already-required T085 run doubles as
the confirmation experiment for the thinking-token hypothesis, instead of needing a second paid run.

1. **Persist per-call usage with a task label.** `UsageRecorder.calls` already holds per-call
   model/tokens/cost and is summed then discarded (`tailor_resume.py:444-459`); `Usage` needs a
   task-name label or the node cannot be identified. Additive migration. Unblocks concern 2 and
   slice 007's regression cost attribution.
2. **Stamp findings with the pass that raised them, and keep each pass's confidence.** Attach at
   the graph node when appending to `state.findings` — not in the model-facing schema, which the
   provider fills. Closes concern 4 and the first-pass-confidence loss for all future runs (the
   existing runs stay unanswerable — §2a).
3. **Fix the Revise overwrite (concern 7).** Failing test first: a revision must preserve draft
   decisions for items the Reviser did not re-return. The only *behaviour* change in the phase.
4. **Then run T085's full-revision-budget measurement** with 1–3 in place. One run settles the
   thinking-token question (per-call output vs persisted text, per node), yields the first clean
   post-`f1f5c7b` adherence sample, and completes the half-done T085.
5. T086–T089 as already written in §5A.

**Deliberately still excluded from this phase:**

- **Any change to `_PLAN`/`_DRAFT` wording.** The two adherence samples are now known to be
  non-comparable (§2a), so there is *less* justification for prompt tuning than before, not more.
- **Any gateway `thinking`/`effort` parameter.** Changing it before step 4's data exists would
  destroy the measurement that decides whether it should change.

If approved, steps 1–3 enter `specs/005-resume-tailoring/tasks.md` as new tasks (T092+) through
the normal specify/analyze flow before any code is written.

### C — Slice 003 User Story 3 · **still blocked on the author** · 11 tasks

A JobTracker export at `backend/tests/fixtures/jobtracker_export.csv`. **Checked 2026-08-26: the
file has not arrived.**

### D — Push · **unblocked, the author's call**

**17 commits on this branch, 7 on local `main`**, none pushed. Nothing is at risk — the main
commits are contained in this branch — but neither is on GitHub.

```bash
git log origin/005-resume-tailoring..HEAD --oneline    # verify first
git push origin 005-resume-tailoring
```

Then the PR: `https://github.com/nirtituani/CareerHQ/pull/new/005-resume-tailoring`

### E — Housekeeping · **unblocked**

- **Rotate the database password** and restart `pgvector`.
- **Rotate the logo.dev token** hardcoded in public source at `ApplicationTable.jsx:4` in
  `nirtituani/job-tracker-web`.
- Decide the open question in `spec.md` § Open Decisions: does `user_corrected` constrain what
  tailoring may rewrite? **Worth settling before slice 006.**

---

### F — Commit the measurement work, then decide on the Plan contract · **the live decision**

**State as of 2026-08-26, in order of what happened:**

1. **Phase 7 (T092, T093, T094) is merged** into `005-resume-tailoring` — three merge commits over
   the agents' own commits, migrations `0012`/`0013` chained linear, upgrade/downgrade drilled
   against a scratch database. HEAD was `bf1e638`.
2. **T085 ran** — Harman, run `60263226`, the first full-revision-budget path: seven calls, the
   Opus escalation firing, three review passes, **$0.547891 / 4m01s**. Both SC targets missed and
   recorded as missed. **T085/T086 are still open**: those figures are *not* yet in `research.md`,
   and T087's human review has been produced but not recorded.
3. **The corrected plan-execution measurement is built and passing** — `plan_execution` beside the
   preserved `emphasis_adherence`, exposed on `GET /versions/{id}/run`, 9 new tests, all four D0
   defects drilled. **It is UNCOMMITTED.**

**What is uncommitted right now** (`git status`): `backend/src/careerhq/application/plan_adherence.py`,
`backend/src/careerhq/api/routes/tailoring.py`, the new `backend/tests/unit/test_plan_execution.py`,
and `.gitignore`.

**Nothing about the agent has been changed to produce any of this.** No prompt, no schema, no model
or thinking/effort configuration, no threshold, no gate, no new instrumentation beyond what T092/
T093 already added, and no provider call since the single T085 run.

**The next decision, and it is the author's:**

- **First**, commit the measurement work and tick a Phase 7 task for it — a measurement that only
  exists in a working tree is one nobody else can reproduce.
- **Then**, and separately, decide whether **the Plan contract itself** warrants investigation. The
  §5B evidence is that `EmphasisDirective` is the only model-facing schema in the system that makes
  claims about the profile with **no quote requirement and no validator**, and that the Harman
  fabrication originated in the Plan rather than the Draft. That is a *contract* question, and
  changing it would touch a model-facing schema and the Plan prompt — which every step so far has
  deliberately refused to do. **It has not been decided, and no evidence yet says it must be.**

**The measurement code is not deployed.** The container runs the baked image; deploying it is a
separate step nobody has asked for.

## 5A. Real data that must not be deleted or modified

This is the project's only evaluation evidence. It was paid for.

| Record | Why it must survive |
|---|---|
| Version `a8f1e4b7` + runs `a76bd349`, `cd27b092`, `2615363e` | Cellebrite. Two failures and the first successful run, on one reused draft — also the evidence the retry-reuse fix works |
| Version `c582d938` + run `6356fb4e` | Zipher. The only run with a revision, and the 0.167 adherence sample |
| Match `ad25de2c` (Voyantis, 0/100, **0 requirement rows**) | The historical invalid analysis. **Deliberately not deleted.** It is rendered as `nothing_to_score` rather than a verdict, which is the spec's own edge case finally implemented — so it also proves that fix |
| Match `1285d10a` (Voyantis, **84 Strong**) | The scoreability fix working on real data |
| All 8 match analyses | $0.309312 of real measurement |

**Total real spend to date: roughly $1.43** — $1.12 tailoring, $0.31 match.

Two rules that have already been broken once each and cost real data:

- **Never run a test against the real profile.** A test run merged a fictional CV into it and
  replaced the contact block. Use a scratch user seeded `@example.com`.
- **Delete anything seeded by hand.** Several versions and a scratch application were created
  during browser walkthroughs and removed afterwards. The current counts are the truth.

## 6. Process reminders

- **Spec-Driven Development** via Spec-Kit: `specify → plan → tasks → analyze → implement →
  verify`. **Do not skip `analyze`** — it found the two invariant tests this slice, and all three
  documentation corrections (T080–T082).
- **Tests first**, and the failure message matters. `ModuleNotFoundError` because the module does
  not exist yet is a valid red.
- **Any test asserting an absence or an invariant must be watched failing** — and check the
  `deselected` count, because a `-k` filter that matches nothing looks exactly like a pass.
- **When implementation predates a test** (US1 built most of US2 and US3), ticking the task on
  inspection is a lie. Break the implementation, watch the test name it, restore.
- **Verify in Docker, then in a browser** on `localhost` — not `127.0.0.1`, which 403s its own
  chunks in Next.js dev with no console error. **Every display bug in this project was found by a
  person looking at real data, including all twenty invisible buttons.**
- **Seed test data against a scratch user, and delete anything fabricated afterwards.** Two hand-
  seeded versions were used for the browser walkthroughs this session and removed; the local count
  is back to zero.
- **Backend gates run on the host, never in the container.** `backend/.dockerignore` excludes
  `tests/`, so an in-container pytest collects nothing and looks like a pass.
- **`docker compose build backend && docker compose up -d backend`** after backend code changes.
  `up -d` alone recreates the container from the same baked image. The frontend hot-reloads.
- **Update `tasks.md` as you go**, and amend a task's text when the implementation deviates. Four
  were amended this slice — T054, T056, T072 and T077 — and each amendment records why.
- **Drill the old behaviour, and count what you examined.** A gate nobody has watched fail is not a
  gate, and a gate with nothing to examine passes forever — that has now shipped four times. Read
  the `N deselected` count; a `-k` selector matching nothing prints a cheerful pass.
- **Distinguish a test double from a model.** Fixtures are written by someone who read the code.
  Where a model must read something out of a prompt, make the double read it out of the prompt too.
- **Keep measured facts separate from interpretation** in tests, commits and `research.md`.
- **`/handoff` before `/clear`.** It does not run automatically.
