# The real-world sanity set — aggregate comparison *(T047, D2, FR-005c/FR-005d)*

**Measured 2026-08-31. Free tier only: no paid call was made to produce anything here.**

> ## ⚠️ Every real-set figure below is UNREPRODUCIBLE — FR-005d
>
> The real-world arm was measured against a gitignored set of the author's own CV and
> job postings, held **outside this repository** at `~/CareerHQ-benchmark-real/v1/` and
> never committed. **Nobody else can reproduce these numbers, including a grader.**
>
> The synthetic arm is fully reproducible from `backend/benchmark/v1`, which is in this
> repository. **The two are not the same kind of evidence and must never be quoted as
> though they were.** Where they appear side by side below, the real column is the
> unreproducible one.

**It answers exactly one question**: does the synthetic benchmark overstate the system?
It is not a source of headline numbers, and no success criterion in this slice depends
on it (`real-sanity-set.md`).

---

## 1. What was and was not measured

| | Status | Why |
|---|---|---|
| **`retrieval_quality`** (structural) | ✅ **measured**, both arms | retrieval is a local embedding plus a pgvector scan — no model call |
| **`difficulty_report`** | ✅ **measured**, both arms | pure set statistics — no model call |
| **`selected_relevance`** | ❌ **NOT measured**, both arms | no relevance judgement has ever been recorded for any retrieval, so the metric reports *not measured* rather than assuming everything retrieved was wanted |
| **LLM-based requirement `coverage`** | ❌ **NOT measured**, both arms | `coverage()` consumes the Reviewer's `uncovered` findings, which exist only after a paid tailoring run |
| **`grounding`, `calibration`** | ❌ **NOT measured** | same reason |

**Two of the four things this comparison would ideally cover are absent**, and the
absent pair includes requirement coverage — one of the two properties the spec names as
flatterable (`spec.md` §"Why the second tier exists at all"). What follows answers the
retrieval half directly and the coverage half only by structural proxy.

---

## 2. Conditions — both arms, one session, one corpus

| | |
|---|---|
| corpus identity | `18/79/unknown` — 18 documents, 79 chunks, embedding model **not recorded** |
| embedding model configured | `sentence-transformers/all-MiniLM-L6-v2` (MiniLM) |
| `guideline_source` | `retrieval` |
| `retrieval_token_ceiling` | 1500 |
| synthetic set | `backend/benchmark/v1` — 12 cases |
| real set | `~/CareerHQ-benchmark-real/v1` — 6 cases |

**The recorded `validation.json` baseline was deliberately NOT reused.** It carries corpus
identity `18/79/BAAI/bge-small-en-v1.5`; the local corpus today records no model and holds
MiniLM vectors. Comparing across embedding models returns confident nonsense — both are
384-dimension, so nothing raises. The synthetic arm was therefore **re-measured in the
same session, against the same corpus and the same embedder** as the real arm.

**That decision is evidenced, not assumed.** The fresh synthetic arm reproduces
`validation.json`'s guideline *counts* exactly (26–27 per case) but differs on *selection*
— 10 of 12 distinct against 12 of 12, union 11 against 13. Same ceiling, same pinned set,
different semantic picks: the signature of an embedding-model difference.

---

## 3. `retrieval_quality` — measured

| | Synthetic (reproducible, n=12) | **Real (UNREPRODUCIBLE, n=6)** | Difference |
|---|---|---|---|
| pinned rules per case | 15.00 | **15.00** | +0.00 |
| selected rules per case | 11.92 | **12.50** | +0.58 |
| **`pinned_proportion`** | **0.5573** | **0.5456** | **−0.0117** |
| distinct selections | 10 of 12 | **6 of 6** | — |
| union of selected rules | 11 | **11** | 0 |
| **`selected_relevance`** | **not measured** | **not measured** | — |

**The synthetic set does not overstate retrieval.** The gap is 1.2 percentage points on
`pinned_proportion`, and it runs *against* the synthetic set: real postings retrieve
slightly **more** selected guidance, not less. Both arms draw from the same 11-rule union,
so real postings are not reaching guidance the synthetic ones never touch.

**A fallback would have looked like a clean null result and was guarded against.** An
early pass returned 12 identical rules per case in both arms with `pinned_proportion`
0.0000 — the `StaticGuidelines` rubric, returned because the embedder could not load. The
harness now refuses when `last_fallback_reason` is set, and the guard was drilled: with a
broken embedder it refuses by case name and reason. Every figure above was taken with that
guard armed.

---

## 4. `difficulty_report` — measured, and a proxy rather than an answer

| | Synthetic (reproducible) | **Real (UNREPRODUCIBLE)** |
|---|---|---|
| cases | 12 | **6** |
| disciplines | 4 | **2** |
| seniorities | 4 | **2** |
| profile states | 4 | **1** |
| cases with `must_have` | 12 | **0** |
| cases with `expected_gaps` | 7 | **0** |
| max pairwise vocabulary overlap | 0.194 | **0.130** |
| min pairwise vocabulary overlap | 0.000 | **0.029** |
| max pairwise prose overlap | 0.205 | **0.154** |

**Only the overlap rows are comparable at all, and even those are weakly so.** The rest
are composition, not findings:

- **`must_have` 12 vs 0 and `expected_gaps` 7 vs 0 are an authoring choice, not a property
  of real postings.** Both are authored human judgements; they were left empty on the real
  cases rather than guessed. Read as a difference between the sets, they would be an
  artefact of how this file's own inputs were built.
- **`profile_states` 4 vs 1** is structural: the real set has one profile by construction.
- **The overlap maxima are taken over different numbers of pairs** — 66 for the synthetic
  set against 15 for the real one. A maximum over 66 draws exceeds a maximum over 15 on
  sample size alone, so **0.194 against 0.130 is not a like-for-like comparison** and must
  not be read as "the synthetic set is more redundant".

**What it does support**, weakly: nothing here suggests the real postings are *harder to
tell apart* than the synthetic ones. That is the direction which would have indicated a
flattering benchmark, and it is absent. It is a proxy for requirement coverage, not a
measurement of it.

---

## 5. Conclusion, and its limits

**On retrieval, the synthetic benchmark does not overstate the system.** By the reading
rule in `real-sanity-set.md`, this is the "close" case: the committed, reproducible
baseline can be trusted on its own, and T016's cases do not need hardening on this
evidence.

**This conclusion is bounded and the bounds are not incidental:**

1. **`selected_relevance` is unmeasured in both arms.** Whether the retrieved guidance was
   *right for the posting* — what most readers would take "retrieval quality" to mean — is
   untouched. What is measured is structure: how much was pinned, how much selected, how
   varied.
2. **Requirement coverage is unmeasured.** One of the two properties the spec names as
   flatterable rests on a structural proxy only.
3. **n = 6 against 12**, in **2 disciplines against 4**. A 1.2-point difference at this
   size is a direction, not a result. This project already fixes a floor for that judgement:
   `_MIN_CALIBRATION_SAMPLE = 4` exists because "a correlation is a description of four
   points rather than evidence".
4. **The real disciplines do not share labels with the synthetic ones**, so no
   per-discipline comparison is possible.
5. **One real case has an empty posting body.** Harmless for retrieval, which never reads
   the body, and it would matter for any paid tier.
6. **Retrieval never sees the posting text at all.** The query is
   `role_title + requirements + market`, so the spec's premise — that synthetic postings
   are "better structured, less redundant" — reaches retrieval only through the
   requirements list. The comparison is valid but narrower than the prose implies.

**No metric was changed, no threshold moved, no test altered and no production behaviour
touched to produce this file.** No paid call was made.
