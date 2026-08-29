# End-to-end validation — **zero model calls** *(T021, T024, T034, SC-012)*

**Measured 2026-08-29 against a scratch database (`careerhq_validate`), corpus
18 documents / 79 chunks / `BAAI/bge-small-en-v1.5`, embedding weights copied out of
the running container rather than downloaded.** `model_calls: 0`. Machine-readable
form: [`validation.json`](validation.json).

```
python scripts/run_benchmark.py validate
```

Everything a paid pass does **except call a model**: load and version the set,
fingerprint the configuration, project the cost, check it against the ceiling, seed
every case through the shipping preconditions, render the master the model would be
shown, retrieve guidance for every posting, and run every free metric over what
comes back. Nothing is committed — the session is rolled back.

## The evidence guard fired first

Pointed at the real database, `validate` **refuses**, exit 4:

> `REFUSED: this database holds 13 non-fixture tailoring run(s) — evaluation evidence
> that was paid for. Validation seeds twelve cases, and those rows would sit beside
> it in every statistic computed afterwards.`

## All twelve cases

| case | seniority | master items | reqs | gaps | retrieved | pinned | selected | ms |
|---|---|---|---|---|---|---|---|---|
| `be-01-mid-payments` | mid | 21 | 6 | 0 | 26 | 15 | 11 | 81.4 |
| `be-02-staff-platform` | staff | 21 | 5 | 2 | 27 | 15 | 12 | 8.3 |
| `be-03-junior-api` | junior | 21 | 5 | 0 | 26 | 15 | 11 | 13.0 |
| `ds-01-senior-forecasting` | senior | 19 | 5 | 0 | 27 | 15 | 12 | 9.6 |
| `ds-02-mle-production` | mid | 19 | 5 | 2 | 27 | 15 | 12 | 9.3 |
| `ds-03-analytics-lead` | senior | 19 | 5 | 1 | 27 | 15 | 12 | 14.6 |
| `fi-01-analyst-fpna` | junior | 13 | 5 | 0 | 26 | 15 | 11 | 15.1 |
| `fi-02-audit-senior` | senior | 13 | 5 | 3 | 27 | 15 | 12 | 8.3 |
| `fi-03-treasury-analyst` | mid | 13 | 5 | 2 | 27 | 15 | 12 | 8.4 |
| `rn-01-icu-senior` | senior | 17 | 5 | 0 | 27 | 15 | 12 | 10.3 |
| `rn-02-community` | mid | 17 | 5 | 1 | 27 | 15 | 12 | 14.9 |
| `rn-03-theatre-scrub` | mid | 17 | 5 | 2 | 27 | 15 | 12 | 8.0 |

Twelve of twelve pass the shipping preconditions. **Zero fell back** — every case
retrieved from the corpus. Master item counts differ by profile state (21/19/17/13),
so the four states are genuinely different documents rather than one reused.

The 81.4 ms is the first call, carrying model warm-up; the rest sit at **8–15 ms**,
consistent with the SC-007 (006) figure of p50 12.1 ms.

## Retrieval quality, structural half *(SC-012, and SC-001 (006))*

**Free — retrieval is a local embedding and a pgvector scan, so this needed no model
and no tailoring run.** 12 postings across 4 disciplines, which exceeds the ≥10 / ≥3
sample SC-001 (006) specifies and which no slice-006 task records having performed.

| | |
|---|---|
| Distinct selections across 12 cases | **12** — every posting gets a different set |
| Union of all selected rules | **13** |
| Pinned set identical on every case | **yes** (15 everywhere) |
| Mean overlap, same discipline | **0.554** |
| Mean overlap, cross discipline | **0.466** |
| Least similar pair | `be-01-mid-payments` / `ds-03-analytics-lead` |
| Selected rules per discipline | backend 11 · data 8 · finance 8 · nursing 8 |

**Measured. Two readings, kept separate from the measurement, and neither is settled:**

1. **Retrieval discriminates, but the pool it draws from is narrow.** Twelve
   postings produce twelve distinct selections — yet only **13 distinct
   non-integrity rules are ever selected**, out of roughly 64 available. The
   1,500-token ceiling minus 15 pinned integrity rules leaves room for about a
   dozen, and the same small set keeps winning.
2. **The discipline signal is weak.** Same-discipline overlap exceeds
   cross-discipline overlap by only **0.09**. T013 (006) found 1 rule in common
   between a backend and a nursing posting; that spread does not reproduce here.

**Whether either is a defect is not decidable from this.** Both are consistent with
a corpus whose rules are largely job-independent by design — "never invent a
number", "no tables or columns" hold for every posting, which is the argument D2
(006) used to reject per-node retrieval. They are also consistent with the ceiling
being the binding constraint rather than relevance. **Distinguishing the two needs
the relevance judgement SC-012 asks for, which is a human task, not another run.**

## Repeatability *(T034)*

Two `validate` runs, nothing changed between them:

| | |
|---|---|
| Same case set | ✅ |
| Identical configuration fingerprint | ✅ |
| Identical rule selections, per case | ✅ |
| Identical retrieval counts and master items | ✅ |
| Retrieval latency | mean absolute delta **6.6 ms**, max 67.6 ms (first-call warm-up) |

**This establishes harness determinism and nothing more, and the limit is the point.**
Everything measured here is deterministic given a fixed corpus and set; **model
variance is not measured and cannot be, because D3 approved one paid pass and the
noise repeat was the third.** Any comparison this slice reports — T057's included —
must state that its noise floor is unmeasured rather than compare against zero.
