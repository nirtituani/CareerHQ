# Research — Slice 009: Career Advisor Agent with Career Memory

Phase 0 output. Every decision below was made against the current codebase on
`009-career-advisor` (cut from `main` @ `c1457e5`), not against an idealised architecture.
Format per plan template: Decision / Rationale / Alternatives considered.

---

## D1 — Run lifecycle: reuse the match-analysis pending-row pattern wholesale

**Decision**: `advisor_runs` mirrors `match_analyses`' lifecycle exactly: a `pending` row
written and committed before any provider call; a background task fills it in
(`ready`/`failed`); a partial unique index enforces at most one `pending` per **user**
(match analysis scopes per application; the advisor is user-scoped); an
`is_abandoned(run)` deadline treats an over-age `pending` row as failed so recovery stays
reachable; the trigger route answers **202** with the pending row and **409** while one is
plausibly in flight.

**Rationale**: the pattern has survived production and three recorded failure modes (stuck
runs needing hand-written SQL, pointer-only-on-success hiding runs, abandoned rows
resurrecting). Every one of those lessons is already encoded in `analyze_match.py` and its
route; inventing a second lifecycle would re-earn them.

**Alternatives**: Celery (constitution lists it, nothing uses it yet — introducing a broker
for one background call is exactly the "placeholder cache" mistake the deployment notes
warn about); synchronous request (a two-minute request against SC-006's visible-progress
requirement, and a timeout loses the cost record).

## D2 — The evidence pack: typed facts with ids, computed in `advisor_evidence.py`

**Decision**: a pure application module computes `EvidenceFact` objects:
`fact_id` (deterministic slug, e.g. `outcome.rejection_rate.global`), `kind`, `scope`,
`numerator`, `denominator`, `value` (str/Decimal rendered), `date_range`, `record_ids`
(UUIDs of the rows counted), `basis` (one sentence naming the computation). The pack is a
function of (user's rows, as-of time, rules version) and nothing else — same inputs, same
facts (FR-006). Percentages and deltas are **precomputed as facts** so the model never has
a reason to do arithmetic.

**Rationale**: FR-005's "the reasoning step receives facts; it MUST NOT be the source of
any number" needs the facts to be individually addressable (the grounding gate checks
claims against *cited* facts, not against the whole pack — assert-an-absence-against-the-
right-scope, testing rule 3). Record ids make SC-001's independent recomputation a test
that can actually run.

**Alternatives**: free-form JSON blob (unauditable, and the gate would have to parse
prose); computing facts inside the prompt template (unreproducible, untestable in
isolation); a SQL-view layer (spreads the logic into migrations for no gain at this scale).

## D3 — Two completions, the first optional: grouping, then reasoning

**Decision**: 
1. **Grouping** (`advisor_grouping` task, Haiku): input is the enumerated distinct job
   titles and, when ≥2 analysed applications exist, the enumerated requirement rows
   (`[id: <uuid>] text`); output is `GroupingProposal` — named groups whose members are
   **ids only**. Skipped entirely when there is nothing to group (no Tier 2 data and
   fewer than 2 distinct titles) — a run must not spend a completion to learn nothing.
2. Deterministic counting runs over the proposed groups, producing more `EvidenceFact`s
   (each carrying its grouping so evidence stays auditable — FR-007).
3. **Reasoning** (`advisor_reason` task, Sonnet): input is the full evidence pack, every
   active memory (with frozen evidence), every dismissed memory (marked
   "dismissed by the user — do not recreate"), and the rules constants; output is
   `AdvisorReasoning` — operations plus a disposition for every active memory id.

**Rationale**: counting must happen **between** grouping and claiming, or the model is the
source of group counts — the one collapse that would break FR-005 while looking helpful.
Haiku for grouping matches the precedent (`llm_model_research_plan_role_queries`); Sonnet
for reasoning matches every judgment task in the system. Two calls keep SC-007 in
match-analysis territory.

**Alternatives**: one combined call (model would emit groups and counts together —
unverifiable); three calls with a separate prioritisation pass (cost without a
distribution to judge; the reasoning schema carries priority instead); LangGraph (see D13).

## D4 — Ids travel in the prompt, `[id: <uuid>]`, exactly like `_render_master`

**Decision**: every enumerable item the model may reference — requirement rows, titles
(keyed by application id), active memories, dismissed memories, evidence facts — is
rendered with an explicit id the schema makes the model echo back.

**Rationale**: "Without ids nothing maps, and a 'successful' run persists a diff with zero
changes" — already paid for once in tailoring. Dispositions keyed by memory id are what
make FR-013's completeness check a set comparison instead of a guess.

**Alternatives**: matching by text (breaks on the first paraphrase); ordinal indexes
(silently wrong after any reordering).

## D5 — The numeral-grounding algorithm (FR-009's teeth)

**Decision**: `advisor_grounding.py` extracts every numeral token from a proposed claim
(digits, including decimals and percentages; the prompt instructs digits-only for
quantities) and requires each to appear in the **cited** facts' rendered values
(numerator, denominator, value, date-range years). Additionally: cited fact ids must
exist in this run's pack; a claim with zero cited facts is refused; forbidden-causality
is enforced by a small phrase list (`because`, `causes`, `leads to`, `due to` in the
claim sentence) — crude on purpose, versioned in `advisor_rules.py`, and the prompt
carries the same rule so the gate is the backstop, not the teacher.

Every discard is recorded: logger with `extra={run_id, reason, claim, cited}` (Railway
blanks `message`; fields survive), and counted on the run row —
`ops_discarded` / `ops_applied` — so *discarded-everything* and *found-nothing* are
different, queryable outcomes (FR-009).

**Rationale**: this is `finalisation_rules.py`'s discard-before-persistence applied to
statistics; the phrase list is the same shape as the floor — a versioned first guess that
can be recalibrated honestly. Log-by-fields is the §4 lesson about production logs.

**Alternatives**: trusting schema descriptions alone (a validator's rules must be visible
in the schema, but a schema cannot check numbers against a pack); an LLM verifier pass
(a model auditing a model is spend without ground truth — the pack *is* ground truth).

## D6 — Dispositions are an append-only log table, not columns on the memory

**Decision**: `memory_dispositions`: `(run_id, memory_id, action
[created|confirmed|superseded|retired|left_open], reason, evidence_delta JSONB)`. A
confirmation writes a log row (with the fresh figures as `evidence_delta`) and advances
`last_confirmed_at` on the memory; the memory's frozen `evidence` is never touched.

**Rationale**: FR-013 says an unaccounted-for active memory is a run defect — that is a
**per-run** completeness assertion: `set(active before run) == set(dispositioned by run)`,
which needs disposition rows keyed by run. It also gives SC-002 its evidence and the UI
its "since the last analysis" story without JSONB-append mutations on an insert-only row.

**Alternatives**: JSONB `confirmations` array on the memory (mutates an insert-only row's
payload; unqueryable per run); no log, derive from statuses (cannot represent `confirmed`
or `left_open` at all — exactly the two that prove retrieval happened).

## D7 — Memory lifecycle columns: forward-only status + immutable content

**Decision**: `career_memories.status ∈ {active, tentative, superseded, retired}`;
`supersedes_id` self-FK set at insert, never after; `retired_reason` (required when
retired — `user_dismissed` is one value of it, so dismissal is a retirement with a
distinguished reason, per spec); `claim`, `kind`, `scope_kind`, `scope_value`,
`evidence` JSONB, `priority` (smallint, NULL for non-actionable), `advisor_run_id`,
`created_at`, `last_confirmed_at`. Content columns are immutable after insert (guarded by
an immutability test in the `application/immutability.py` style); `status` moves only
forward: `tentative→active` (evidence reaches the floor), `active|tentative →
superseded|retired`. `tentative` counts toward reasoning input and the cap; only
`active`+`tentative` are "the current understanding" (FR-014).

**Rationale**: mirrors resume-version immutability ("the lock is about content, not the
row"). Dismissal-as-retirement-reason keeps one lifecycle instead of two.

**Alternatives**: separate `dismissals` table (a second lifecycle to keep consistent);
mutable claims with history table (edits are the thing FR-012 exists to forbid).

## D8 — Dismissal "materially differs" test (FR-021's deterministic layer)

**Decision**: a proposed `create` whose `(kind, scope_kind, scope_value)` equals a
`retired_reason = user_dismissed` memory's is refused **unless** the set of
`(fact_id, numerator, denominator)` tuples in its cited evidence differs from the tuples
frozen in the dismissed memory's evidence. On legitimate recreation, the new memory row
carries `recreates_dismissed_id` so the history is visible (spec: "dismissal history
preserved").

**Rationale**: value-tuple comparison is deterministic, cheap, and matches what
"materially changed" means here — the numbers moved. Fact-id-only comparison would pass
when nothing changed but the as-of date.

**Alternatives**: text similarity on claims (fuzzy, untestable); permanent block
(rejected in clarification Q4).

## D9 — Cap enforcement (FR-016a) is a use-case invariant with a drilled test

**Decision**: after applying operations, the use case asserts
`count(active+tentative) ≤ ACTIVE_MEMORY_CAP` **before commit**; if the reasoning output
would exceed it, creates are applied in priority order and the remainder discarded-with-
record (same observability channel as D5). The prompt states the cap and the
must-retire-to-create rule; the gate is the backstop.

**Rationale**: a COUNT-based invariant cannot live in the schema (no such constraint in
PostgreSQL without triggers, and business invariants this project puts in the schema are
UNIQUE/CHECK-shaped). The one-pending-run index closes the race that matters — two
concurrent runs — so the in-transaction count is safe.

**Alternatives**: DB trigger (first trigger in the codebase, for an invariant a
single-writer use case already holds); refusing the whole run at the cap (turns a
prioritisation duty into an outage).

## D10 — Tier 1 fact families shipped in v1 of the pack

**Decision** (each family versioned under `ADVISOR_RULES_VERSION`; all read-time, none
stored): status distribution and rejection rate (global and per role-family group once
grouping exists); application volume by month; time-in-status (`date_added` →
`date_applied` gap; `status_history` transitions where present); `imported_match_rating`
distribution (labelled self-assessment); match-analysis coverage (analysed vs not — this
is the denominator honesty fact FR-011 renders); per-verdict requirement frequencies over
analysed applications (Tier 2, via grouping); match `overall_score` per band and per
role-family group (Tier 2).

**Rationale**: every family is computable from columns that exist today and was named in
the approved analysis; coverage-as-a-fact is what lets the insufficient-data answer cite
its own denominator ("1 of 97 analysed").

**Alternatives**: interview-feedback families (entity does not exist — out of scope);
correlation facts (gap × rejection) — deliberately **excluded** from v1: at current N
they invite the causal phrasing FR-010 forbids; revisit when Tier 2 accumulates.

## D11 — Scope representation: `scope_kind` + `scope_value` strings

**Decision**: `scope_kind ∈ {global, role_family, skill, status, source}` (String, not a
DB enum — open like `kind`), `scope_value` free text (`NULL` for `global`). The
contradiction gate (FR-016) and dismissal gate (D8) key on `(kind, scope_kind,
scope_value)`.

**Rationale**: enough structure for the gates to compare on, no JSONB indirection for a
two-field concept.

**Alternatives**: JSONB scope (unqueryable equality semantics); FK to a role-family table
(there is no such table; groupings are per-run evidence, not entities — making them
entities is exactly the duplicated-source-of-truth Principle I forbids).

## D12 — Task/model configuration

**Decision**: `llm_model_advisor_grouping = "anthropic/claude-haiku-4-5-20251001"`,
`llm_model_advisor_reason = "anthropic/claude-sonnet-5"` in `config.py`, with the
standard comment naming the Opus fallback trap. Both calls run through `complete()`
wrapped in `UsageRecorder`; a failed run records `ExtractionFailedError.usage`
(the graph-that-raises-does-not-return lesson).

**Rationale**: matches the fixed model-per-node table in docs/08 §3.2.3 and the existing
Haiku precedent for classification-shaped work.

**Alternatives**: Sonnet for grouping (2× spend for id-bucketing); Opus for reasoning
(SC-007 budget gone for no measured gain — tuning waits for a distribution, per the
non-goals).

## D13 — No LangGraph

**Decision**: `advise_career.py` is a plain use case: evidence → (grouping?) → counting →
reasoning → grounding gate → persist, linearly.

**Rationale**: the project's own test for LangGraph is "deleting it must change nothing" —
here there is no conditional edge, no revision loop, no state to merge (and the
no-reducer-overwrite gotcha is a standing tax on every LangGraph state key). A failed
validation ends the run (the no-automatic-retry non-goal), so there is no branch to
orchestrate.

**Alternatives**: LangGraph for uniformity with tailoring (uniformity with the wrong
shape; tailoring has a loop, this does not — and if a revision loop is ever added, the
seam-call sites are the same either way).

## D14 — No `AdvisorProvider` port

**Decision**: the use case calls `complete()` directly, like match analysis and tailoring.

**Rationale**: ports here mark seams where a second implementation plausibly arrives
(`GuidelineSource`, `ResearchProvider` — both swapped or dual). There is no second
implementation of "reason over my own evidence pack"; a port would be ceremony. The
provider-agnosticism Principle V requires is already delivered by the completion seam.

**Alternatives**: a port for symmetry (symmetry with seams that earn their keep).

## D15 — Failure and abandonment semantics

**Decision**: `run_advisor` never raises (the `run_analysis` contract): any failure marks
the run `failed` with a user-safe `error` (kind, not detail — detail to the log), records
usage spent so far, and **touches no memory row** (the whole operation set applies in one
transaction after the gate, so a failed run cannot half-apply — SC-005's byte-for-byte
requirement). Abandonment deadline: 10 minutes (constant beside the others), after which
a `pending` run reads as failed and a new one may start; the deadline is generous because
a run is two completions, and an abandoned-toohastily row would let two real runs race.

**Rationale**: each clause is a §4 lesson (never-raises, cost-on-failure, stuck-run
recoverability, last-success-preserved).

**Alternatives**: partial application of valid ops before a later failure (breaks SC-005
and makes "what did this run do" unanswerable); no abandonment (hand-written SQL, three
times, already).

---

*All Technical Context fields in plan.md are resolved; no NEEDS CLARIFICATION remains.*
