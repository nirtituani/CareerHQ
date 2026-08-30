# Quickstart: Evaluation & Benchmark

**Everything on this page is free.** Nothing here makes a paid model call. The paid tier does not
run until D3 — the ceiling and the case counts — is approved.

## Prerequisites

```bash
docker compose up -d                 # postgres, backend, minio
cd backend && source .venv/bin/activate
```

Backend gates run **on the host, never in the container**: `backend/.dockerignore` excludes
`tests/`, so an in-container pytest collects nothing and looks like a pass.

## 1. See what there already is to measure — free, read-only

The metric definitions are developed against the thirteen runs that already exist. Read them before
writing anything:

```bash
docker compose exec -T postgres psql -U careerhq -d careerhq \
  -c "SELECT task, model, count(*) n, round(avg(input_tokens)) avg_in,
             round(avg(output_tokens)) avg_out, round(avg(cost),6) avg_cost
      FROM tailoring_run_calls WHERE is_fixture = false GROUP BY task, model ORDER BY task;"
```

Expected on 2026-08-29: five tasks, 26 calls, `tailor_draft` the most expensive at **$0.120885**.

```bash
docker compose exec -T postgres psql -U careerhq -d careerhq \
  -c "SELECT kind, count(*) FROM reviewer_findings GROUP BY kind;"
```

Expected: **64 `uncovered`, 13 `overstated`, 2 `ungrounded`**.

> ⚠️ **Read-only.** These rows are the project's only evaluation evidence — $3.562567 of it — and
> `HANDOFF.md` §5A forbids modifying or deleting them. Never run a benchmark, a test or a fixture
> against the real profile: one already merged a fictional CV into it.

## 2. Run the metric suite — free

```bash
.venv/bin/pytest tests/unit/test_evaluation_metrics.py -v
```

Every metric is tested against `ScriptedSeam` — deterministic, no model. **Read the
`N deselected` line**: a `-k` selector that matches nothing prints a cheerful pass, and this project
has been fooled by exactly that.

## 3. Drill a metric — free, and mandatory

A gate nobody has watched fail is not a gate (FR-033). For each metric and each refusal:

```bash
# 1. break it deliberately — e.g. let the severity split persist an `ungrounded` proposal
# 2. run the test; confirm it fails and NAMES the violation
# 3. restore
```

The drills are listed per metric in [contracts/metrics.md](contracts/metrics.md) and per refusal in
[contracts/benchmark-run.md](contracts/benchmark-run.md). **Ticking a task on inspection is a lie**
when the implementation predates the test.

## 4. Exercise the runner end to end — free

```bash
docker compose exec backend python scripts/run_benchmark.py run v1 --gateway fixture
```

Drives every case through the shipping path with **canned responses**, so nothing is billed. This
proves the plumbing: cost projection, ceiling refusal, per-case recording, result file.

Then confirm the harness **refuses to lie about it**:

```bash
docker compose exec backend python scripts/run_benchmark.py report <result-file>
# expected: refusal naming "fixture gateway" — not a grounding-accuracy number
```

**That refusal is the acceptance test for User Story 1**, not a limitation to work around.

## 5. Retrieval quality — free, and it needs no tailoring run

Retrieval is a local embedding plus a pgvector scan (p50 12.1 ms). Ten postings across three
disciplines can be retrieved for and rated without a single paid call:

```bash
docker compose exec backend python scripts/run_benchmark.py retrieve v1
```

This also discharges **SC-001 (006)**, which no slice-006 task records having performed.

> The local corpus was embedded with **MiniLM**; the production image bakes **bge-small**. Both are
> 384 dimensions, so **nothing raises** and a cross-model comparison returns confident nonsense.
> Every figure taken here is a MiniLM figure and the result file records which.

## 6. Cost a prompt change without paying — free

The token delta of a prompt change is measurable offline, by rendering through the real prompt
builder. This is how T057's **+16 tokens, 1.07%** was established, and it is why T057's *cost*
question needs no model at all — only its *quality* question does.

## 7. The paid tier — blocked

```bash
# docker compose exec backend python scripts/run_benchmark.py run v1
```

**Do not run this until D3 is approved.** It refuses without a configured ceiling, and it reports
its projection before any billable call either way. Expected spend per
[plan.md](plan.md) → *Estimated spend*: **$3.21 minimum / $6.11 recommended / $14.39 maximum**,
expected; **$3.69 / $7.03 / $16.51** conservative.

## What "done" looks like for each user story

| Story | Verified by |
|---|---|
| **US1** — a benchmark that runs the same way twice | §4, plus two fixture runs producing identical case sets, plus the refusal in §4 firing |
| **US2** — metrics, and a checked judge | §1–§3 against the thirteen existing runs, with every drill watched failing |
| **US3** — did the change help | The T057 experiment: baseline, the free presence assertion, T057, re-run, compare against the noise figure |

**And one rule the suite cannot enforce**: this project's test suite has **never once** caught a
display bug — contact fields, bullet attribution, skill categories, project URLs and every default
button in the application were all found by a person looking at real data. Read the first real
benchmark report by eye before believing any number in it.
