# Data Model: Evaluation & Benchmark (Phase 1)

**No new tables, and — after §0 — no migration either.** The plan proposed two
columns; building the harness eliminated both. One optional column remains, serving
only an inherited criterion. Nothing is written.

---

## 0. The verdicts, after building the slice *(T036, T037, T038)*

> ### Bottom line: **migration `0019` is not required, and is not created.**
> The plan proposed two columns. Building the harness and running it against the
> thirteen real runs **eliminated both**, and the one that looked most necessary
> turned out to rest on the wrong question.

| Proposed | Verdict | Why |
|---|---|---|
| `tailoring_runs.guideline_source` | **NOT required — the record already answers it** | See below. This is the one that changed twice. |
| `tailoring_runs.benchmark_run_id` | **NOT required — withdrawn** | The result artifact lists its cases and the run id each produced, so case → run needs no column, and the reverse is a scan of result files. A column referencing no table, justified only by convenience, is not worth a migration. |
| `tailoring_run_calls.duration_ms` | **Not required by this slice; the only thing that would need it is inherited** | Below. |

### `guideline_source`: the wrong question, asked twice

**First draft** inferred provenance from the absence of content hashes and called a
hash-less snapshot "retrieval that fell back". That would have refused **every
legitimately static run** — including the static baseline arm that the retrieval
cost measurement rests on — for a fault it did not have. (That measurement is
SC-008 *this slice*; **SC-008 (006) is untouched by any of this and remains MISSED
at 3.22% against an unchanged ≤2% threshold**.)

**Second draft** returned `indeterminate` and refused, on the grounds that the
record cannot say what a run was *configured* with. Honest, but it cost 11 of 13
real runs their eligibility, and it concluded a schema column was needed.

**Both were answering the wrong question.** A metric describes what a run *was
advised by*, not what someone intended it to be advised by. A run whose guidance
came from the static rubric cannot support a retrieval claim **whatever it was
configured with** — so "what was configured" is not a question any metric asks.

And *what was used* the record answers exactly. `citation_snapshot` writes the
corpus citation (`slug · locator · hash`) for a retrieved rule and
`StaticGuidelines`' constant `"CareerHQ house rubric v1"` for a static one.
**Measured across all ten real runs carrying a snapshot: seven record the rubric
constant, three record citations. No third shape, no overlap, no ambiguity.**

**Fallback detection survives intact and still needs no column.** It is
*intent versus outcome*: the benchmark runner knows what it pointed a run at and
records that in the result artifact; `guidance_used()` reads what the run actually
consumed. **The two disagreeing is the fallback**, and both halves already exist —
one in a file this slice writes, one in a column slice 005 already wrote.

**Result of the reframing, measured:** reportable runs went from **2 of 13 to 8 of
13** — the five withheld are exactly the five that failed. Six legitimately
reportable runs were being refused by an inference that should never have been made.

### `duration_ms`: no alternative source, but nothing here needs it

Per-node latency is genuinely underivable: `tailoring_run_calls` carries task,
model, tokens and cost and **no timing**, and the run's own `started_at`/`finished_at`
bracket the whole graph. The only alternative is the ~92 tok/s throughput assumption
M-001 was raised against.

**But no slice-007 criterion fails without it except SC-010, which exists only
because M-001 was inherited from slice 006.** Every metric this slice actually
computes — grounding, coverage, retrieval quality, adherence, calibration, cost
overhead — is complete without it.

**Recommendation: drop SC-010 from this slice, or land the single column with Slice
008 when migration ownership is settled.** It is one nullable integer and it closes
a real debt; it is not worth branching the migration chain from `0018` under time
pressure, and it is not worth blocking a slice whose value does not depend on it.

### What this means for the numbering

`0019` was tentatively assigned to Slice 007 and `0020` to Slice 008 so the two
would chain from `0018` rather than branch. **Slice 007 no longer needs `0019`.**
The cleanest outcome is that **Slice 008 takes `0019`** and the `duration_ms` column
follows as `0020` if and when SC-010 is pursued — but that is the author's call,
and nothing here creates a migration either way.

---

## 1. What changes in the database

### 1.1 `tailoring_run_calls.duration_ms` — nullable integer

**Closes M-001's remaining half** (FR-029, SC-010). The row already carries task, model, tokens and
cost; it carries **no timing**, so per-node latency is derivable only from a throughput assumption
(~92 tok/s, itself estimated across six runs).

| | |
|---|---|
| Type | integer, **nullable** |
| Meaning | wall-clock milliseconds for that one `complete()` call |
| NULL | **unknown, never zero.** Every existing row predates the column |
| Backfill | **none.** Deriving a duration from a token count would present inference as record — the rule `review_confidences` already follows |

**Why not a timestamp pair.** `func.now()` is transaction-scoped in PostgreSQL: every row written in
one transaction carries the same instant. That is already why `sequence` exists as the ordering
column rather than a timestamp, and the same trap would make a `started_at`/`finished_at` pair
report zero for every call in a run.

**Where it is written**: alongside tokens and cost in `_record_usage`, on **both** the success and
failure paths — a failed call was still billed and still took time, and run `cd27b092` is the
recorded reason the failure path records usage at all.

### 1.2 `tailoring_runs.benchmark_run_id` — nullable ***(WITHDRAWN — see §0)***

*Kept because the reasoning is what produced the verdict against it, and because a
proposal deleted without its argument is a proposal that gets re-made.*

**Makes benchmark runs distinguishable from user runs** (FR-011). A benchmark drives the shipping
path, so its runs land in `tailoring_runs` like anyone's. Without a marker the two populations
contaminate each other: a benchmark of thirty runs would swamp the eight real ones in every cost
and confidence statistic computed afterwards.

| | |
|---|---|
| Type | UUID, **nullable**, indexed |
| Meaning | the benchmark run this tailoring run belongs to |
| NULL | a user-initiated run. Every existing row |
| Referential integrity | **none — deliberately.** There is no `benchmark_runs` table |

**Why it references nothing.** Benchmark results are files (§2), so the id is an opaque correlation
key generated by the runner and written into both the row and the result file. A foreign key would
require the table §2 argues against.

**This is a real trade and it is stated rather than hidden**: an id with no constraint can be
mistyped or orphaned. It is accepted because the alternative — a table whose only purpose is to give
a nullable column something to point at — would put the evaluation record back inside the Docker
volume that §2 exists to get it out of. A test asserts every non-NULL `benchmark_run_id` in the
database has a matching result file, which is the constraint expressed where the data actually is.

**Rejected: inferring benchmark runs from the owning user.** Implicit, unenforceable, and wrong the
first time someone runs a benchmark under the wrong account.

**Rejected: a boolean `is_benchmark`.** It answers *whether* but not *which*, so two benchmark runs
could not be told apart — and telling them apart is the entire regression capability.

---

## 2. What is a file rather than a row, and why

Benchmark cases, benchmark results, judge scores, human ratings and comparison reports are
**version-controlled files**.

**The argument is the project's own failure mode, not tidiness.** Its entire evaluation evidence —
$3.562567 — lives in two local Docker volumes with a backup on the same machine that is already
behind; `HANDOFF.md` opens with that as a red-flagged risk. Putting this slice's results in the same
place would reproduce a known problem deliberately.

Files in git are replicated by every clone, diffable, reviewable in a PR, survive
`docker compose down -v`, and sit beside the spec that defines them. A benchmark result is a
**record of an experiment**; that is what version control is for.

It also keeps FR-005 honest: results reproducible from version-controlled inputs cannot depend on
rows somebody seeded by hand.

### 2.1 Benchmark case — `backend/benchmark/v1/<case-id>.md` *(committed, synthetic)*

| Field | Rule |
|---|---|
| `case_id` | stable, referenced by every result. Never reused after an edit |
| `discipline`, `role`, `seniority` | the axes FR-005b requires variety across |
| posting content | consumed through the ordinary path — the same field a pasted posting fills |
| profile state | which synthetic profile this case pairs with |
| `expected_gaps` | requirements the profile genuinely does not cover. **The AI-008 test material** — at least one case must have some |

**Fully synthetic, no real personal data** (FR-005a, FR-039). The precedent is
`backend/tests/fixtures`, whose subject is fictional precisely so it can be committed.

### 2.2 Benchmark set version — the directory name

`v1`, `v2`. **Editing a case is a new version, never an edit in place** (FR-002) — the rule the
match criteria and the finalisation rules already follow, and for the same reason: otherwise every
historical result silently becomes incomparable.

### 2.3 Benchmark result — `specs/007-evaluation-benchmark/results/<run-id>.json` *(committed)*

Holds the configuration fingerprint FR-031 compares on — model per task, guideline source,
finalisation rules version, benchmark set version, corpus identity, embedding model, pricing basis —
plus per-case outcomes, per-metric values with their `n`, the spend, and the projection that was
reported before it started.

**The fingerprint is the load-bearing part.** Two results are comparable only if it matches in every
dimension but the one under test; a mismatch is named rather than silently averaged over.

### 2.4 Judge score and human rating

Judge scores live in the result file, each carrying its rubric version. Human ratings live in their
own committed file so that re-running a benchmark never overwrites a person's judgement — and so
that the agreement figure can be recomputed against any later judge.

### 2.5 The gitignored real set — `benchmark-real/` *(never committed)*

D2's sanity check. Excluded from git and from CI. **Only the aggregate comparison is committed**,
labelled as coming from an unreproducible source (FR-005c, FR-005d).

---

## 3. Entities that already exist and are only read

`TailoringRun`, `TailoringRunCall`, `ReviewerFinding`, `ResumeVersion`, `ResumeVersionItem`,
`MatchAnalysis`, `MatchRequirement`, `KnowledgeDocument`, `KnowledgeChunk`.

**Read, never written** (FR-012). The harness adds rows; it modifies and deletes nothing — including
the eight versions, thirteen runs, eight analyses and one submission `HANDOFF.md` §5A protects.

---

## 4. Migration ownership — the reason this stops here

**Migration `0019` is tentatively assigned to Slice 007 and `0020` to Slice 008** (author's
decision, 2026-08-29), so that the two slices form a **chain from `0018` rather than two branches**.
**Slice 008 must not create `0019` independently.**

**It is still not written here.** The assignment resolves the *number*; the implementation waits
until ownership is confirmed in the implementation phase, because `down_revision` is a chain rather
than a set. Two slices branching from `0018` is trivial to resolve in git and vicious in a deployed
database: whichever merges second points at a revision that is no longer the head, and the failure
surfaces at `alembic upgrade head` during a **pre-deploy**, not at merge.

Slice 008 has begun landing shared surfaces — `config.py` at HEAD already carries
`llm_model_research_synthesise_company` — which is why the ordering had to be decided rather than
assumed.

**After §0's verdicts, `0019` contains nothing that this slice needs.** What is left
is one optional column, and it is optional:

```
0019_evaluation_instrumentation
  + tailoring_run_calls.duration_ms      integer      NULL   -- FR-029, SC-010, M-001
  + tailoring_runs.guideline_source      varchar(16)  NULL   -- retrospective comparability
```

Both nullable, neither backfilled. **NULL means unknown, never zero and never a
default value** — the rule `review_confidences` and `displaced_position` already
follow, and backfilling either would present inference as record.

`benchmark_run_id` is **not** in it (§0).

**The migration is not written.** `0019` is tentatively Slice 007's and `0020`
Slice 008's, so the two chain from `0018`; ownership is confirmed in the
implementation phase, and Slice 008 must not create `0019` independently.
