# Contract: A Benchmark Run

## The shape

**`run` is paid; `report` is free.** The split is the pattern
`scripts/measure_retrieval_cost.py` established, and the reason is that arithmetic must be
re-checkable — and **drillable** — without paying again.

```
run     <set-version>   → drives the shipping path across every case, writes a result file
report  <result-file>   → computes every metric from persisted records. No model call.
compare <a> <b>         → before, after, delta, versus noise. No model call.
```

## Order of operations, and the refusals

1. **Resolve the set version.** A missing or edited case is a refusal, not a warning.
2. **Fingerprint the configuration** — model per task, guideline source, finalisation rules version,
   corpus identity, embedding model, pricing basis.
3. **Project the cost and report it.** From the measured per-task figures, and the projection is
   printed whether or not anyone is watching.
4. **Refuse above the ceiling** (FR-008). Before any billable call. The ceiling is configuration;
   its value is **D3, pending**.
5. **Run each case through the shipping use case** — `create_pending_version` then `run_tailoring`,
   the same path a user's click takes (FR-010). Not a reimplementation, which would measure the
   reimplementation.
6. **Record each case's outcome**, including failures, with the reason.
7. **Write the result file**, including the actual spend and the projection it was compared against.

## Refusals, and each one's drill

| Refuses when | Requirement | Drill |
|---|---|---|
| projected cost exceeds the ceiling | FR-008 | set the ceiling below one run |
| any call came from the fixture gateway | FR-030 | run the benchmark against `FixtureGateway` and ask for grounding accuracy |
| retrieval was configured but fell back to static | FR-030 | empty the corpus |
| the model mix differs from the shipping one | FR-010, FR-030 | point one task at a different model |
| the target profile is not the synthetic benchmark profile | FR-013 | point a case at the real profile |
| a comparison spans differing fingerprints | FR-031 | compare across benchmark set versions |

**Every one of these must be watched failing before its task is ticked** (FR-033). A harness that
cannot refuse a mocked arm, an empty corpus or a fallback produces numbers with no claim attached —
and this project has shipped four gates that examined nothing and passed cheerfully.

**Assert the count of what was examined.** A benchmark that ran zero cases and reported clean
metrics is the same failure as a route enumeration walking zero routes.

## What a run must never do

- **Modify or delete any existing run, version, analysis, export or submission** (FR-012). It adds
  rows only. The eight versions, thirteen runs, eight analyses and one submission already in the
  database cost $3.562567 and are the project's only evaluation evidence.
- **Touch the owner's live Professional Profile** (FR-013). A test seeded against it has already
  merged a fictional CV into it once and replaced the contact block.
- **Approve anything.** Every metric is computable from the composed résumé at review time. Approval
  is the user's action and the harness does not take it (Principle II).
- **Auto-retry a failed case.** A failed node ends a run; whether to retry is a recovery-behaviour
  decision deliberately separated from correctness work. A failed case is counted and named.

## The correlation key

Each run generates a `benchmark_run_id`, written into both `tailoring_runs.benchmark_run_id` and the
result file. It references no table, because the results are files — see
[data-model.md](../data-model.md) §1.2 for why, and for the test that stands in for the missing
foreign key.
