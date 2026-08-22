# Resume Tailoring — design

**Date**: 2026-08-22
**Status**: approved, not yet implemented
**Slice**: 005 (the flagship; see *Sequencing* for why it is 005 and not evaluation)

---

## 1. What this is

The agent that takes a recorded job and adapts the user's resume to it: choosing what to
show, ordering it by relevance, rewriting how it reads — and never inventing anything.

It answers **"given that this job is worth applying to, how should my resume read?"**, which
is the question that follows the one Match Analysis already answers.

It is the first thing in CareerHQ that **loops**. Every prior AI call is one structured
completion in and one validated object out. This one drafts, criticises its own draft, and
revises — bounded, and with a human gate before anything is kept.

### Sequencing — why this is 005 and evaluation is 006

`docs/05` §5.5 assigns evaluation to slice 005 and `docs/07` §3.3 assigns the Reviewer to
"004 (the loop), 005 (the metrics)". Both predate the **split of slice 004**, which shipped
match analysis alone and deferred the tailoring agent. The Reviewer loop went with it.

Evaluation was reconsidered for this position and moved behind tailoring. Of the seven
metrics `docs/05` §5.5 lists, four measure the tailoring agent — requirement coverage of a
tailored resume, retrieval quality of the RAG step, LLM-as-judge of tailored output, and
grounding accuracy of generated claims. Building the harness first means building a
measuring instrument for something that does not exist and extending it later anyway, which
is most of the argument for building it first.

**Evaluation remains non-optional.** It is an explicit project requirement, it is the
difference between "I built an agent" and "I know how well it works", and this slice is
what gives it something to measure.

### Scope

**In**: the workflow, the Reviewer, Resume Versions with lineage, item-level approval.

**Out, and deliberately** — these become slice 006, "the version becomes a document":

- **Knowledge Context / RAG** — ingestion, chunking, embeddings, retrieval with citations.
  The Draft node consumes a guideline rubric; in this slice that rubric is static application
  code. Swapping its source to retrieval later changes one node's input, not the design.
  This defers the graded RAG requirement by one slice, knowingly.
- **PDF export, the ATS-safe template, `SubmittedResume`, and the `Exported`/`Submitted`
  lifecycle states.**

§5.4 as written is six subsystems. Slice 004 was one structured call and ran 89 tasks; all
six in one slice is how a four-to-six-week budget ends with nothing demonstrable.

---

## 2. The fifteen commitments

Agreed explicitly during design. They are listed here because most of them are invariants a
plausible-looking implementation would violate quietly.

1. Match Analysis is **read-only input**.
2. Tailoring **requires a completed, non-stale** Match Analysis.
3. Plan is a **real LLM judgement step**, not a database read.
4. Plan is a **structured, persisted artifact**.
5. Draft **consumes** the Plan; it does not independently invent the strategy.
6. LangGraph owns **orchestration**, not persistence or business state.
7. Nodes are **state-in / state-out** and do not write to the database.
8. All LLM calls go through **`complete()`**.
9. The CareerHQ database remains the **source of truth**.
10. Reviewer → **bounded** revision loop, at most **2 revisions**.
11. Human approval is a **business state transition**.
12. **Awaiting approval is distinct from Reviewing.**
13. Finalisation enforces grounding and safety rules **before persistence**, in the use case.
14. Model selection stays **task-configured** via `llm_model_<task>`.
15. Match Analysis is **never mutated** by tailoring.

---

## 3. Architecture

### 3.1 Why LangGraph, and how far in

LangGraph orchestrates. It does not own state.

```
api/routes/tailoring.py            HTTP; ownership from the session, never the request
        ↓
application/tailor_resume.py       the use case: transactions, persistence, audit, finalisation
        ↓
application/agents/tailoring/      the graph: nodes, edges, state    ← LangGraph lives here only
        ↓
application/ports.py               complete()  — unchanged; four new call sites, making seven
        ↓
infrastructure/                    the provider
```

**The runtime sits under `application/` so the import-graph guard covers it** — but that
guard does not currently do what commitment 8 needs, and this was checked rather than
assumed.

`tests/unit/test_architecture.py::test_the_application_layer_imports_no_provider_sdk`
forbids exactly one package: `litellm`. A node importing `anthropic` or
`langchain_anthropic.ChatAnthropic` would pass the suite today. **Widening that forbidden
tuple to cover the provider SDKs and LangChain's model classes is a task in this slice**, and
it is what makes commitment 8 structural rather than a convention someone remembers. Adding
LangGraph as a dependency is precisely the change that makes those imports reachable, so the
guard and the dependency must land together.

`ports.py` needs no change, and its docstring already reserved this slice: *"Multi-step
orchestration, tool use, retries with feedback and self-critique are slice 004. A caller
that needs the model to react to its own previous output belongs in the agent runtime, not
here."* This slice builds that runtime. The seam is the boundary it sits on, not a thing it
modifies.

**There is no executable guard asserting that no call site loops** — that boundary lives only
in the docstring quoted above, and `CLAUDE.md` describes it as "the line the guard actually
protects", which overstates what is enforced. Nothing needs widening there; the docstring
needs updating so it does not contradict the runtime this slice introduces. The real guard is
the import-graph one, and it is the one to strengthen.

### 3.2 Why not LangGraph's checkpointer

Rejected for this slice, not rejected in principle.

Adopting it would create two persistent representations of one workflow — the CareerHQ
tables and the checkpointer — and therefore an unanswerable question about which is the
source of truth for a run's current state. CareerHQ must persist business state, versions,
approvals, audit and AI metadata regardless. A second mechanism needs a concrete requirement
behind it, and durable pause/resume is not one this slice has: **approval starts no further
graph execution.**

If a later slice needs genuine pause/resume semantics that CareerHQ-owned state cannot
express cleanly, the checkpointer returns as an option. Nothing here forecloses it.

### 3.3 Nodes are thin

A node builds a prompt, awaits `complete()`, and folds the result into state. It holds no
session, performs no write, and calls no provider class directly.

```python
async def draft(state: TailoringState) -> TailoringState:
    result = await seam.complete(
        task="tailor_draft",
        schema=TailoredDraft,
        prompt=build_draft_prompt(state),
    )
    return replace(state, draft=result.value, usage=[*state.usage, result.usage])
```

This is what makes every node testable against a fake seam with no provider and no database,
and it is why the graph can return final state and write nothing.

---

## 4. The graph

Four nodes, one conditional edge, bounded at two revisions.

```
POST /api/applications/{id}/tailor
        │  refuses without a fresh Match Analysis (§6.1)
        │  creates tailoring_run + resume_version (Draft → Tailoring) synchronously
        │  202 + version id;  BackgroundTasks → run_tailoring(version_id)
        ▼
┌────────────────────────── LangGraph ──────────────────────────┐
│                                                               │
│   [plan] ──► [draft] ──► [review] ──►◆ cleared threshold?     │
│                  ▲                    │                       │
│                  │                    │ no, attempts remain   │
│                  └──── [revise] ◄─────┘                       │
│                                                               │
│                  attempts exhausted, or cleared ──► END       │
└───────────────────────────────┬───────────────────────────────┘
                                ▼
        run_tailoring: finalisation rules (§7), then persistence,
        in one transaction — version, items, findings, usage
                                ▼
                  resume_versions.status = Awaiting approval
```

| Node | Task name | Model | Produces |
|---|---|---|---|
| `plan` | `tailor_plan` | Sonnet | The Tailoring Plan (§5) |
| `draft` | `tailor_draft` | Sonnet | Item selection, ordering, and rewrites |
| `review` | `tailor_review` | **Opus** | Findings per item, and a confidence score |
| `revise` | `tailor_revise` → `tailor_revise_escalated` | Sonnet → **Opus** | A corrected draft |

**Escalation is a task-name swap, not a branch.** `docs/08` §3.2.3 fixes Revise on Sonnet
for the first attempt and Opus for the second, because a Sonnet revision that has already
failed to clear an Opus reviewer once is unlikely to clear it on a retry with the same
model. `ports.py` was designed so this is configuration: `task` is a name, and model choice
resolves from `llm_model_<task>`.

**Every one of these five task names needs an `llm_model_<task>` entry.** `model_for_task`
falls back to `llm_provider_model`, which is **Opus** — a missing entry runs at 2.5× the
price for no gain, silently. This has already caught CV extraction once.

### 4.1 State

A frozen dataclass. Not LangChain messages — the state is our vocabulary, and it is what
`run_tailoring` reads to persist.

| Field | Set by | Read by |
|---|---|---|
| `job` | entry | plan, draft, review |
| `master` — profile facts, read once | entry | plan, draft, review |
| `match` — the existing analysis, read-only | entry | plan |
| `plan` | plan | draft, review |
| `selection` — item ids kept, in order | draft, revise | review, finalisation |
| `rewrites` — item id → proposed text | draft, revise | review, finalisation |
| `findings` — item id, kind, severity | review | revise, finalisation |
| `confidence` | review | the conditional edge |
| `attempt` — 0, 1, 2 | revise | the conditional edge, and the task name |
| `usage` — one `Usage` per call | every node | finalisation |

`usage` accumulates in state rather than being logged inside the adapter, because Principle
V requires the audit record to be written in the same transaction as the work it paid for.
That is obligation O4 of the seam, and it survives here unchanged.

---

## 5. Plan and Draft are separate steps

The Plan node was nearly collapsed into a database read of the Match Analysis. That would
have been wrong, and the reasoning is recorded because the shortcut looks like a saving.

**Match Analysis and the Tailoring Plan answer different questions.**

| | asks |
|---|---|
| Match Analysis | *How well does the profile fit this job?* |
| Tailoring Plan | *Given the job, the profile and that fit, how should the resume be tailored?* |

Feeding requirements straight into Draft would make one call choose the strategy **and**
write the prose. That is the shape of the v2 scoring bug: a number computed independently of
the list it summarised, free to disagree with it. Here the disagreement would be silent —
prose that quietly optimises for something other than the plan nobody wrote down.

Keeping the Plan separate also makes it **inspectable, persisted, and evaluable**, which is
what slice 006's harness will need.

### What the Plan contains

- What to **emphasise** — experience, skills, achievements, themes, with the requirement each
  serves
- What to **de-emphasise** — present but not relevant to this posting
- Which **gaps must not be misrepresented** — carried from the Match Analysis's `gap` and
  `unverified` verdicts, and stated as a prohibition the Draft and Reviewer both read

That last item is the plan's most important output. AI-008 is enforced at finalisation as a
rule (§7), but naming the specific gaps up front is what stops a draft drifting toward them
in the first place.

---

## 6. Data

Match Analysis is **read, never written** (commitments 1 and 15). It is append-only by
design and slice 004's calibration is measured over its history; a tailoring run that
touched it would corrupt a measurement nobody would think to check.

### 6.1 Preconditions

Tailoring requires a Match Analysis that is **complete** and **not stale**, and refuses
otherwise with a prompt to re-run it.

Staleness already exists and needs no new machinery: `applications.py` computes
`profile.updated_at > analysis.created_at` at read time and already returns `"stale"` in the
API. `domain/models/match.py` deliberately made this a comparison rather than a column,
because a stored flag is a second source of truth that goes wrong the moment a profile is
edited without every analysis being visited.

**Why refuse rather than fall back to Job + Profile.** A plan built on a fit assessment
computed against an older profile cites evidence that no longer exists, and the Reviewer
then rejects claims that were properly grounded when they were analysed — a failure that is
expensive to debug and reads as the Reviewer malfunctioning. A fallback path is also the
"two code paths, the rarer one undertested" problem, and it would run precisely when
something is already wrong.

The ordering constraint costs nothing in practice: reading the score is how a user decides a
job is worth tailoring for.

### 6.2 Tables

**`resume_versions`** — the document. Status per `docs/03` §10.1, amended per §8.
Records lineage: source `resume_profiles` id and its state at creation (ADR-012 — lineage is
recorded, never inherited). Carries the tailoring workflow reference (`docs/03` line 273).

**`tailoring_runs`** — one row per execution. Holds the Plan, attempts, per-node `Usage`,
model configuration, the finalisation rules version, and the failure reason when there is
one. Referenced **by** the version, not the reverse.

**`resume_version_items`** — one row per included item: source item id, original text,
proposed text, the user's decision (accepted / rejected / edited), and the final text.

**`reviewer_findings`** — item reference, kind, severity, and the Reviewer's own wording.

Business invariants belong in the schema. At minimum: one in-flight run per application, as
a partial unique index rather than an application-level check that a double-click can race —
the same reasoning as `uq_resume_profiles_one_master_per_profile`.

### 6.3 Why the version is created synchronously

`POST /applications/{id}/tailor` creates **both** the run and the version before starting the
graph, and returns the **version id**.

- **The lifecycle says so.** `docs/03` §10.1 starts at `Draft` and makes `Tailoring` a
  transition *out of* it. A version that does not exist until the graph runs has no `Draft`
  to leave. And `Draft` is not an empty placeholder — it is the master's content, every item
  included, master ordering, original wording. A coherent document: *your resume, not yet
  tailored*.
- **It matches the established pattern.** `create_pending_analysis` creates the row
  synchronously, `BackgroundTasks` runs the work, and the 202 carries the id the client
  polls. Reusing that shape inherits its reaper, its in-flight guard, and both bugs it
  already taught (§10).
- **One id for one thing.** Status lives on the version, so the version is what the client
  polls and what the URL is about. Creating the run first would make the client poll a run id
  and switch identifiers partway through.
- **The reference direction confirms it.** `docs/03` line 273 puts the workflow reference on
  the version. Version → run. A run created first would have nothing pointing at it.

**What failure leaves behind**: the version stays in `Draft`, and the run records why. No
`Failed` state is added to the version lifecycle; what remains on disk is an untailored
resume plus an audit row explaining the attempt. A stuck run reaps the same way — run marked
abandoned, version returned to `Draft`. A retry reuses that `Draft` rather than creating a
second one, so abandoned runs do not accumulate versions.

---

## 7. Finalisation

**In `tailor_resume.py`, never in a graph node** (commitment 13). The graph's terminal node
returns final state; the use case applies the rules and writes. This was the one defect in
the first design sketch — a `finalize` node that performed the severity split *and* the
persistence — and it is the easiest thing to reintroduce quietly during implementation.

### The severity split

| Finding kind | What happens |
|---|---|
| **Ungrounded** — a claim traceable to nothing in the profile | The item's rewrite is **discarded before persistence** and the master's original text stands. It never reaches a row, so it can never reach an approve button. |
| **Overstated** — the profile supports it, the wording inflates it | Persisted and shown, flagged, attached to its item. The user decides. |
| **Coverage** — a requirement the draft failed to address | Persisted and shown against the draft as a whole. |

This is where Principles II and III are reconciled rather than traded off. Principle III makes
an ungrounded claim a release blocker, so the system enforces it and the user is never
consulted. Principle II governs everything else, so judgement calls reach the human.

### Versioned, like the scoring criteria

The rules live beside `match_criteria.py` as a **named version**, recorded on every run.
Changing a threshold or reclassifying a finding kind is a **new version, never an edit** —
otherwise every historical run is silently reinterpreted, and slice 006 evaluates this
capability by comparing runs over time.

---

## 8. Lifecycle amendment

`docs/03` §10.1 as written:

```
Draft → Tailoring → Reviewing → Ready → Exported → Submitted
          ▲            │
          └────────────┘  confidence below threshold — internal, no user input
```

**`Reviewing` currently means two different things**: the agent is self-critiquing, and the
agent has finished and it is the user's turn. One is a machine working; the other is a human
queue. A user watching a spinner cannot tell which, and the states have entirely different
expected durations and entirely different next actions.

Amendment: `Reviewing` keeps its agent meaning, and a distinct **`Awaiting approval`** state
sits between it and `Ready`.

```
Draft → Tailoring → Reviewing → Awaiting approval → Ready
          ▲            │                              ↓
          └────────────┘                        (further editing)
```

`Exported` and `Submitted` are slice 006. `Ready` means user-approved and **remains
editable** — approval is not a one-way door until export, which `docs/03` already states and
which matches the per-item editing decided in §9.

`docs/03` §10.1 is updated as part of this slice. A lifecycle described in two places will
disagree.

---

## 9. The human gate

When the version reaches `Awaiting approval`, the user sees a diff: each proposed change with
its original, its replacement, and any Reviewer finding attached to that item.

**Findings are per item, plus one confidence score for the draft.** A finding beside the
bullet it concerns is what turns approval from rubber-stamping into judgement — *"accept or
reject this bullet, which the Reviewer flagged as leaning on a skill your profile mentions
once"*. A guardrail nobody can see is indistinguishable from one that is not running.

**Rejecting keeps the original wording, and the text stays editable.** No agent round trip;
the version simply keeps what the master said, and a plain text field allows a correction by
hand. This is a text field per item, **not an editor** — a full WYSIWYG resume editor is an
explicit non-goal. Hand edits are marked as user-authored, the way profile corrections
already carry `user_corrected`.

**Default follows the import-review precedent**: an untouched review accepts everything not
rejected; explicitly accepting any item narrows it to those. A second interaction pattern for
the same idea costs an affordance every time — grouping skills proved that during slice 003,
where Edit, then Add, then Remove each went missing from the second render path.

`POST approve` transitions the version to `Ready`. **It starts nothing.** No further AI work
follows approval in this slice, which is precisely why the checkpointer is unnecessary
(§3.2).

---

## 10. Failure modes, mostly already paid for

Slice 004 bought these lessons at full price. They apply here unchanged.

- **`==`, never `is`, on a status read from the database.** These are `String(16)` columns; a
  row loaded in a fresh session returns a plain `str`, so an `is` comparison silently never
  matches. `run_analysis` guarded that way and returned immediately on every real call while
  270 tests stayed green. **Every status path here must be exercised through a second
  session**, because a test that reuses the creating session holds the enum member in its
  identity map and cannot see the bug.
- **Assign relationships at construction.** Serialising a freshly added object that lazily
  loads a collection raises `MissingGreenlet` as a 500. The version's items and findings are
  exactly this shape.
- **Reap abandoned runs.** A `pending` match analysis older than an hour is reaped because
  three stuck runs each needed SQL by hand — the in-flight guard answered 409 to the one
  action that would have recovered it. A tailoring run is longer and costlier; the same reaper
  is required from the start, not added after it bites.
- **Estimates of output tokens are unreliable.** R8 projected ~1,500 and measured 2,811.
  `docs/08`'s ~$0.17 per run predates this loop's shape and is **unverified**. Worst case here
  is seven calls, three of them Opus reviews, and the Opus reviews will dominate. Measure it on
  the first real run rather than carrying the estimate forward as a fact.
- **Never ask the model to retype text it was given.** Output is the slow half and 57–86% of
  the cost; a posting retyped once took 52 seconds and timed out the frontend proxy. Draft and
  Revise must return item ids with changed text, never the whole resume re-emitted.
- **Undefined CSS custom properties fail silently and differently per property.**
  `tokens.test.ts` scans for this; new components are covered by it automatically.
- **A CSS reveal must land on the finished state when the animation is removed**, because
  reduced motion collapses animations to 0.01ms. The tailoring progress indicator is the next
  thing in this project likely to get this wrong.

---

## 11. Testing

- **Nodes against a fake seam.** No provider, no database. Each node is a pure function of
  state, which is the point of §3.3.
- **Finalisation rules as pure unit tests**, including the case that matters: an ungrounded
  finding must leave no proposed text in any row.
- **Status transitions through a second session**, per §10.
- **An absence test must be watched failing.** `conftest.py` drops the schema before creating
  because `create_all` does not reconcile an existing table — T067 passed against a
  deliberately added column until it did. Any assertion here that something is *not* persisted
  inherits that requirement.
- **One integration test through the real stack**, in Docker.
- **One real run, on a real posting, read by a person.** Every display bug in this project was
  found this way and none were found by the suite. A fixture contains only the fields whoever
  wrote it thought to include.

---

## 12. Open questions

- **The confidence threshold has no calibrated value.** It is a constant in the finalisation
  rules version, and its first value is a guess. Slice 006 is what turns it into a measurement;
  until then, changing it is a new rules version like any other constant.
- **Re-tailoring after approval.** A `Ready` version remains editable, but whether a second
  tailoring run against the same application produces a new version or replaces the draft is
  not decided here. It is not needed for the first implementation and is easier to answer with
  one real run to look at.
- **`docs/07` §3.3 and `docs/05` §5.5 both need updating** for the split — the Reviewer's loop
  is 005, its metrics are 006. Deferred to the spec, so the slice's own artifacts do not
  disagree with the plan while it is being written.
