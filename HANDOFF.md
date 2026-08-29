# HANDOFF

**Last updated:** 2026-08-29 (Slice 006 post-T046 — everything but deployment; every number below re-measured against the database) · **Commit:** `298a45f` · **Branch:** `005-resume-tailoring` (all Slice 006 and 008 work is **uncommitted** on this branch)

> **Slice 005 is complete and deployed** — 100 of 101 tasks; T088 is open *on purpose* (it needs a
> real paid production run). **Slice 006 — Document & Retrieval is at 47 of 51**: **T001–T046 and
> T050 are complete.** Corpus, retrieval, citations, latency instrumentation, export, submission,
> immutability, revision lineage, the insert-only gate, the API and affordance, corpus ingestion,
> and both measurements. **Next is T047** (full gates + Docker verification), then **T048**
> (deploy). **T051 is open and is not a blocker.**
>
> **Retrieval now runs against a populated corpus — locally.** T050 gave `ingest_corpus` a caller
> (`python -m careerhq.ingest`, pre-deploy). The local database holds **18 documents and 79
> chunks, all embedded at 384 dimensions**, and re-ingestion is idempotent (0/0/0/0). **The
> deployed database is still at head `0014` and has no knowledge tables at all**, so a production
> run would still fall back to the static rubric. T048 owns that.
>
> **SC-007 MET, SC-008 MISSED.** Latency **p50 12.1 ms / max 24.8 ms** against 500 ms (T044, R14).
> Cost **2.12%** against **≤2%** (T045, R15) — missed on the most favourable denominator
> available, and the target was **not** adjusted. The cause is measured: `token_count` budgets
> **rule text only** while the rendered prompt also carries a citation per guideline, so a
> "1,500-token" ceiling reaches the model at ~2,190. **No task owns fixing it** — see §5.
>
> 🔴 **$3.084181 of paid evaluation evidence lives in one local Docker volume and nowhere else**
> (8 real runs, 8 analyses, 6 versions — re-measured today; production has 0 runs).
> `docker compose down -v` destroys it. **Back it up before anything else** — §5 E2.
>
> **All three open questions are now closed.** **OQ-006-A — DECIDED, YES, implemented**: a run
> that retrieved guidance records it even if it later fails; the snapshot is written **immediately
> after retrieval**, a **pre**-retrieval failure leaves `NULL`, and `[]` is never a substitute for
> unknown. **OQ-006-B — DECIDED, implemented**: V1 tailors every run for the **Israeli** market
> (`V1_TARGET_MARKET`), stated at the call site and never inferred. **OQ-006-C — DECIDED and
> IMPLEMENTED at T050**: ingestion runs **pre-deploy, after `alembic upgrade head`, as
> `python -m careerhq.ingest`**; the startup hook is **ruled out** and stays ruled out.
>
> **The corpus is 79 rules across 18 documents and is REVIEWED. Do not add rules to hit a category
> target.** Three categories are deliberately short of their original targets because the source
> register has no further evidence to derive them from — see §2. Removal is preferable to invention.
>
> **A parallel session is working Slice 008 in this same working tree.** It owns
> `application/ports.py`, `research_*.py`, `citation_check.py` and `domain/schemas/research.py`.
> Do not edit those. Alembic head is `0016_export_and_submission`; **whoever writes a migration next
> rebases onto it and does not branch the history.**
>
> **Implementation priority, in this order: Correctness → Simplicity → Efficiency → Course
> requirements.** Do **not** add agent/ReAct complexity to look more agentic, or to satisfy a
> superficial reading of the course requirements.

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

**Every number below was produced by a command run on 2026-08-28. Nothing is carried forward.**
**Re-measured at the T037 handoff, and three recorded figures were wrong** — see §2a.

| Gate | Result | Command |
|---|---|---|
| Backend suite | **787 passed**, 86.50% coverage (gate 80%) | `.venv/bin/pytest -q` |
| Frontend suite | **172 passed** (12 files) | `npm test -- --run` |
| ruff check / format | clean, 202 files formatted | `.venv/bin/ruff check . && ruff format --check .` |
| mypy strict | clean, **82 source files** (+ `scripts/`) | `.venv/bin/mypy src` |
| Alembic | single head **`0016_export_and_submission`** | migration chain read directly |
| Local database | head `0016`, **1 user · 10 applications · 6 versions · 11 run rows (8 paid) · 8 analyses · 0 exports · 0 submissions** | `docker compose exec postgres psql` |
| Local corpus | **18 knowledge documents, 79 chunks**, all embedded (T050) | same |
| Deployed database | head **`0014_displaced_position`** · 1 user · 1 application · **0 versions · 0 runs** · 1 analysis | `railway ssh --service pgvector` |

| Slice | Tasks | State |
|---|---|---|
| 001 — Platform Foundation | 69 / 69 | Complete |
| 002 — Deployment | 52 / 52 | Complete |
| 003 — Data Foundation | 98 / 109 | US1, US2 done. **US3 blocked on a JobTracker CSV** |
| 004 — Match Analysis | 89 / 89 | Complete, verified in production |
| 005 — Resume Tailoring | **100 / 101** | Complete and deployed. T088 open deliberately |
| **006 — Document & Retrieval** | **38 / 51** | **Phase 4 complete** — export works end to end, endpoint and affordance included. Next is **T038** (submission). T050/T051 appended, both unbuilt |
| 008 — Company Research | no `tasks.md` | Spec/plan/research/open-questions only. **Being built in parallel in this tree** |

### 2a. What re-measurement corrected at the T037 handoff

**Three recorded figures were wrong, and the corpus finding is the consequential one.**

1. ***There is a SEVENTH real tailoring run that `research.md` R5 does not record.***
   `ff0e310c` — **succeeded, 0 revisions, $0.307106, `is_fixture = false`, 2026-08-26.** The R5
   table lists six. Whoever relies on that table for evaluation evidence is missing a successful
   zero-revision sample, which is the cheapest kind and the one the distribution has fewest of.
2. ***The spend figures were understated.*** Measured by `SUM(cost)`:
   **tailoring 7 runs / $2.122210**, match 8 analyses / $0.309312, **total $2.431522**. §5A said
   "roughly $1.43" and R5's table totals $1.815104; both predate the seventh run and neither was
   re-summed.
3. ***The corpus has never been ingested anywhere.*** The local database is at head `0016` with
   the knowledge tables present and **0 documents, 0 chunks**; the deployed database is still at
   `0014` and has no knowledge tables at all. So **no retrieval has ever run against a populated
   corpus outside the test suite** — every real tailoring run used the static rubric. This is
   OQ-006-C/T050 stated as a measurement rather than as a missing caller, and it is why
   **T044/T045 (SC-007/SC-008) cannot be measured yet**.

***And the evaluation data is LOCAL ONLY.*** All 7 runs, 8 analyses and 4 versions live in the
`careerhq` Docker volume on this machine. Production has 0 versions and 0 runs. §5A says this data
"must not be deleted" without saying where it is: **`docker compose down -v` destroys $2.43 of paid
evidence**, and CLAUDE.md documents that command as the way to get a clean database. There is no
backup.

### Slice 006 — what is built (T001–T037, T049)

**The corpus — 79 rules, 18 documents, 4,285 tokens, 54.2 tokens/chunk** (`cl100k_base`, measured
this session, not estimated).

| Category | Rules | | Trust level | Rules |
|---|---|---|---|---|
| universal | 28 | | internal | 54 |
| integrity | 15 | | industry | 10 |
| role-seniority | 12 | | institutional | 9 |
| tailoring | 11 | | vendor_documented | 6 |
| israel | 7 | | **Market** | global 72 · israel 7 |
| ats | 6 | | **Topics** | 16 of 16 in use |

**Three categories are short of their original targets, deliberately.** israel 7 (target 10–14),
ats 6 (12–15), role-seniority 12 (20–30). The register holds no further evidence to derive them
from, and two of the most commonly written ATS rules are excluded by decision (header/footer
parsing, file format). **Do not pad them.** What would close each: a verified Israeli primary
source; a vendor documenting header handling or current format behaviour; any role-specific source.

**The pipeline.**

- `infrastructure/corpus/loader.py` (T025) — parses `## Rules` list items **only**. Document prose,
  preambles, change notes and `## Removed` sections can never become chunks. Both boundaries drilled.
- `application/ingest_corpus.py` (T026) — idempotent: re-running an unchanged corpus creates
  nothing, deletes nothing, and makes **zero embedding calls**. Not insert-only: rules deleted from
  the corpus leave the database.
- `application/retrieved_guidelines.py` (T027) — semantic selection, **all 15 integrity rules
  pinned regardless of similarity**, FR-014 ceiling enforced from stored `token_count`, resolvable
  citations, both fallback paths recorded on `last_fallback_reason`.
- `citation_snapshot()` (T028) — the recorded citation, **written from the retrieved objects and
  never from `TailoringState`**. Seven fields plus the rendered `source`; `RetrievedGuideline`
  gained `trust_level` for it. `state.guidelines` stays `list[dict[str, str]]` — the two keys a
  prompt renders and nothing more. **A guideline with no citation records none**: the static
  rubric persists `{text, source}`, because emitting `content_hash: ""` would write a record that
  fails its own verification and so is indistinguishable from drift. **No migration** —
  `guidelines_used` was already JSONB.
- **The export renderer (T031, with the minimum of T034/T035 it required)** —
  `domain/schemas/document.py` (`ResumeDocument`/`ResumeSection`, pure content, no ORM) and
  `infrastructure/documents/render.py` (WeasyPrint behind a boundary). **Sections are explicit, not
  derived from `SourceKind`**: a renderer that grouped by kind would decide the document's order
  itself, and "approved order" would mean something the caller could not control. **T035's metadata
  pinning did not land** — it belongs with T032.
- **The export endpoint and affordance (T037)** — `POST .../export` (409 on refusal, 404 for a
  missing or unowned version) and `GET .../document` (attachment, `private, no-store`, 404 before
  any export). **Separate routes so downloading again is not exporting again.** No storage key in
  any response. Frontend: `exportVersion`, `versionDocumentUrl`, and an Export/Download pair;
  `VersionStatus` gained `"exported"` only — `"submitted"` waits until something can reach it.
- **The export use case (T036)** — `application/export_resume.py`: refuse → render → store bytes →
  `ExportedDocument` → `status = EXPORTED`, the caller committing. **Bytes are stored before the
  row**, so a failed upload records nothing rather than leaving a checksum pointing at bytes that
  do not exist. SHA-256 is over the exact stored bytes; a fresh storage key per export so a
  re-export cannot overwrite what the first one checksummed. **Not in `export.py`** — T033 asserts
  the guard imports no renderer, so the use case took its own module (`plan.md`'s file map
  deviated from, recorded).
- **The renderer boundary (T035)** — `weasyprint` is imported by `render.py` alone, asserted in
  `test_architecture.py` beside the litellm guard. **The naive guard was not enough**: `render.py`
  re-exported `HTML`, so a caller could `from ...render import HTML` and drive the engine while
  that guard stayed green. Bound privately as `_HTML`, and asserted on the module's namespace
  rather than on `__all__`. **No metadata pinning was written** — WeasyPrint 69 emits nothing to
  pin, and T032's test already guards a future version that starts to.
- **The ATS template's guarantees (T034)** — contact details in the body rather than a page
  header/footer (asserted by flow position, so changing the margins cannot break it), headings
  surviving as recognisable words (the corpus's letter-spacing rule, S-006), no private-use icon
  glyphs, and **no vector objects at all**. Single column, no tables and no images were already
  guaranteed by T031 and are recorded rather than duplicated.
- **The export precondition (T033)** — `application/export.py`: `ensure_exportable(status)` and
  `ExportRefused`. **FR-016 only**; the use case is T036. Exportable is `{READY, EXPORTED}` —
  `READY` is what the specs call `APPROVED`, and `EXPORTED` is included because
  `ExportedDocument` has no unique constraint on the version *so that re-export works*.
  `SUBMITTED` is refused because it is terminal. The guard **imports no renderer**, asserted, so
  it cannot render before refusing.
- **Export byte-determinism (T032)** — `fonts-dejavu-core` declared in the image, FR-031 scoped to
  one runtime, and **no normalization code**: WeasyPrint 69.0 emits no timestamp and no document
  ID, so there was nothing to pin. Asserted across two processes, and the font declaration is
  asserted by parsing the Dockerfile's instruction lines (**comments stripped** — the first version
  matched the comment and passed the drill).
- **The guidance snapshot's placement (OQ-006-A)** — written **immediately after retrieval,
  before the graph**, so a run that failed inside the graph still records what it was advised. A
  failure *before* retrieval leaves `NULL`; `[]` is never written. The success-path assignment was
  removed, so there is one write and no success/failure divergence.
- **The V1 market (OQ-006-B)** — `tailor_resume.V1_TARGET_MARKET = "israel"`, passed explicitly
  into every `GuidelineQuery`. **FR-038 precedence fires in production as of this decision**; it
  did not before. Never inferred from the posting or the profile. The port's default stays
  `global`.
- **The wiring (T030)** — `build_guideline_source()` at the seam in `api/routes/tailoring.py`,
  `get_embedding_source()` (process-wide, `lru_cache`d) in `infrastructure/embeddings/`, and
  `warm_up()` called from `lifespan` only when the selector says `retrieval`. **`run_tailoring`
  itself was not edited**: it already called `guidelines_for` once before the graph, so FR-029
  needed a test rather than a change. A failed warm-up is **not fatal** — FR-010 decides that.
  `guideline_source` is now `Literal["retrieval", "static"]`, because a typo landing on retrieval
  is how SC-008's static baseline would be taken against retrieval and reported as a comparison.
- `RetrievedGuidelines.last_retrieval_ms` (T029) — FR-039 latency, plus `duration_ms` in the log
  record's `extra` (**never the message** — Railway blanks it). Recorded on **every** exit,
  fallbacks included; cleared at the top of each call; **the clock stops once**, so the
  empty-corpus path's two log records carry one figure. No migration, no dependency, no metrics
  pipeline — an attribute beside `last_fallback_reason`.

### The R13 decision — resolved, and it reversed an earlier one

**Embeddings cannot express FR-038's "same topic".** Measured over 504 cross-market pairs: the one
true same-topic pair (Israeli section ordering vs the global section-order rule) scores **0.650 and
ranks 326th — below the 0.670 median** — while the pair the corpus review ruled *complementary*
scores **0.861, first of all**. The negative outranks the positive by 0.211, so no threshold orders
them correctly: at 0.60 the true case is caught but 435 of 504 pairs fire; at every higher
threshold the complementary pair is wrongly caught and the true one missed. Full account:
`research.md` **R13**.

**T025 had deferred `topic` on the argument that a hand-maintained taxonomy would duplicate what
the embeddings classify. R13 showed they do not classify it at all, so that objection fell** and
the field was authored at T027:

- **`topic` is a document-level LIST** from a 16-value vocabulary (`domain/models/knowledge.py::Topic`)
  read off the 79 shipped rules. A list, not a scalar, because two documents legitimately span two
  subjects — rules are grouped by *trust level*, a different axis — and a scalar would have forced
  those files to split for an unrelated reason.
- **`GuidelineQuery.market`** added (defaults to `global`) — the second blocker R13 found.
  Precedence is scoped *"for Israeli-market CVs"*, so retrieval that cannot tell which market it
  serves cannot apply it.
- **Precedence is a set intersection: deterministic, reviewable, nothing to tune.** No cosine
  anywhere in the topic path, and a test asserts no threshold appears.
- **Outranks, never replaces.** Nothing is suppressed — the volunteering pair is complementary, and
  FR-038 says global guidance remains applicable to Israeli CVs. One stable pass moves only the
  chunks the rule requires.

**Contested topics (where precedence can fire):** `section-order` — `israel-military-and-section-order`
vs `universal-document-conventions`; `volunteering` — `israel-military-and-section-order` vs
`universal-structure-and-ordering`.

### The open measurement question — unchanged, and now better than feared

`chars/4` overestimated the corpus by **23%** (~5,540 vs the measured 4,285). Consequences:
**~27 chunks fit the 1,500 ceiling, not ~19**, and **integrity pins 795 tokens = 53% of the budget,
leaving 705 (~13 chunks)** rather than the 67% projected.

D5's floor-upward sizing (~35 rules ≈ 1,890 tokens at 54/chunk) still does not fit 1,500, so **the
conflict is real but smaller**. **The ceiling has not been moved and must not be** until T044/T045
measure actual retrieval. The projection documents still carry the chars/4 figures — deliberately
not churned; re-baselining is the author's call.

### The T013–T018 reconciliation — closed, and it corrected this file twice

**Resolved 2026-08-28. All six are ticked and every one was drilled.** The previous entry here said
several were "substantively covered" by the T027 test file. **That reading was wrong about two of
them**, and the corrections are recorded in `tasks.md` rather than quietly ticked:

- **T014, T015, T017** — genuinely covered by tests written at T027. Ticked only after drilling
  each. T017 needed **three** drills, because "records that it fell back" is a separate claim from
  "survives the fallback" and only the third drill exercises it.
- **T016 was half covered**, and the covered half was the weaker one: recomputing a hash over text
  that has not moved says nothing about FR-011/FR-012, which are claims about a corpus that
  *changes*. Three tests added — unchanged re-ingestion, an edited rule, and a row tampered with in
  place (with a control, so a check that fails everything cannot pass).
- **T018 was not covered at all.** The existing test asserted `hasattr(source, "guidelines_for")`;
  the whole state-and-prompt clause had no test. Three added, one per surface. The forbidden-word
  scan is scoped to the **citation halves only**, and `rank` is excluded from the vocabulary
  because a real Israeli rule uses the word.
- **T013 was genuinely uncovered** and is now implemented. `StubEmbedder` cannot express it — a
  character-sum vector makes "a different query selects a different set" arithmetic about the
  double. `LexicalEmbedder` derives its vector from the words in the text. **Measured**: 13
  non-integrity rules for a backend posting, 12 for a nursing one, **1 in common**.

**The lesson for this file**: "substantively covered" was an inspection, and an inspection is what
this project's own rules forbid ticking on. Neither claim survived contact with a drill.

### Live system

**https://frontend-production-02ac.up.railway.app** — readiness reads `database ok · cache
not_configured · object_storage ok · ai_provider ok`. **Nothing from slice 005, 006 or 008 is
deployed.** It all lives uncommitted on this branch.

### Real evaluation evidence — measured 2026-08-26

**`specs/005-resume-tailoring/research.md` R5 is authoritative** for the tailoring numbers and
labels which parts are measured and which are one reader's interpretation. This is the summary.

**Tailoring runs — six real ones, three successful:**

| Job | Run | Status | Rev | In | Out | Cost | Elapsed | Proposals | Findings |
|---|---|---|---|---|---|---|---|---|---|
| Cellebrite | `a76bd349` | failed | 0 | 0 | 0 | $0 | 4m00s | — | — |
| Cellebrite | `cd27b092` | failed | 0 | 30,028 | 21,641 | $0.361819 | 3m29s | — | — |
| Cellebrite | `2615363e` | **succeeded** | 0 | 34,888 | 15,512 | **$0.295450** | 2m50s | **4** | 7 |
| Zipher | `6356fb4e` | **succeeded** | **1** | 41,621 | 23,908 | **$0.464942** | 4m20s | **1** | 12 |
| Harman | `60263226` | **succeeded** | **2** | 64,493 | 21,855 | **$0.547891** | 4m01s | **4** | 15 |
| Voyantis | `508f4c2c` | **failed** | 0 | 12,736 | 11,953 | **$0.145002** | 2m12s | — | — |

**The table above accounts for six runs and $1.815104. It is not the total, and has not been
since the T037 handoff.** It is left as written because it is R5's measured *analysis* of the six
runs R5 analysed; everything since has been counted, not analysed. **Never quote $1.815104, or the
table's row count, as a total.**

***The one authoritative figure is the database, and here it is, re-measured at the T046
handoff:***

| | |
|---|---|
| tailoring runs, all rows | **11** |
| of those, **real** (cost > 0) | **8**, totalling **$2.774869** |
| of those, succeeded | 6 |
| zero-cost rows | 3 — one old failure, and two from T045's free fixture dry-run |
| match analyses | 8, **$0.309312** |
| **total paid evidence** | **$3.084181** |

**Two things this accounting has got wrong twice, so read them before adding a number.**
A **row count is not a run count**: three of the eleven cost nothing, and two of those exist only
because a harness was validated against the fixture provider before it was allowed to spend.
And a **total is not a sum of the tables in this file**: T045 added $0.652659 that no table above
mentions. Re-measure with `SUM(cost)` rather than adding to a figure someone wrote down.

```sql
SELECT count(*) FILTER (WHERE cost > 0) AS real_runs, sum(cost) FROM tailoring_runs;
```

**Harman `60263226` is the full-revision-budget path** (seven calls, the Opus escalation firing,
three review passes). **T085/T086 remain open**: its cost and latency are *not* yet recorded in
`research.md`, and both SC targets were missed — SC-006 at 1.83×, SC-001 over the 3-minute ceiling.

**Voyantis `508f4c2c` is cost and reliability evidence only, never a quality sample.** Anthropic
returned `overloaded_error` on the first review call; the plan and draft had already been billed.
Recorded in `research.md` R5. **Voyantis remains a wanted candidate for a future successful
sample** — the posting is not disqualified by this.

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

| Job | D0 | D1 — Draft compliance | D3 — Plan effect | State vector (corrected) |
|---|---|---|---|---|
| Cellebrite | 0.500 | acted **3**, ratio **withheld** | **3/6 = 0.500** | 3 survived · **3 unknown_position** · 1 label_kind |
| Harman | 0.286 | acted **3**, ratio **withheld** | **0/5 = 0.000** | 2 reverted · 1 discarded · **2 unknown_position** · 2 label_kind |
| Zipher | 0.167 *(historical)* | **not computable** | **not computable** | 1 survived · **5 unknown** |

**D1's ratios were withdrawn by T095 and cannot be recovered.** They were computed by reading "no
text proposal" as "no proposal", and the position data disproves that: Cellebrite and Harman each
hold only **5 distinct positions across 9 bullets**, and master ordering is a unique sequence, so
both demonstrably reordered. The `acted` counts of 3 survive as floors; the denominator of 7 and the
0.429 ratio do not. **Whether a proposal arrived was never persisted for these runs** — not
destroyed, never written — so it is permanently unrecoverable, and **no replacement ratios are
offered**. Rows predating `displaced_position` classify as `unknown_position`, which leaves D1's
denominator and withholds its ratio while any remain. **No backfill.** Full account in
`research.md` R5 → *"the D1 ratios are withdrawn"*.

**D3 is unaffected and every D3 figure above stands** — whether text survived is knowable however
little is known about ordering.

**The surviving conclusion**, restated honestly: both uncontaminated runs acted on at least three
planned emphases by text evidence, and neither can say how many more it acted on by reordering. The
old 0.5-vs-0.167 D0 spread still must **not** be read as evidence that the Draft behaved
differently. Zipher remains contaminated by the pre-T094 Revise replacement defect: 1 determinable
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

### Slice 006 — uncommitted as of 2026-08-28

Regenerate with `git status --short`. Nothing is staged. **Files marked ⚠️ belong to the parallel
Slice 008 session — do not edit them.**

| Layer | File | Change |
|---|---|---|
| domain | `domain/models/knowledge.py` | **new** — `KnowledgeDocument`, `KnowledgeChunk`, `Market`, `TrustLevel`, `SourceType`, **`Topic`** |
| domain | `domain/models/tailoring.py` | `VersionStatus += EXPORTED, SUBMITTED`; `ExportedDocument`, `SubmittedResume` |
| domain | `domain/models/__init__.py` | registers the above |
| domain | ⚠️ `domain/schemas/research.py` | slice 008 |
| application | `application/embeddings.py` | **new** — `EmbeddingSource` port |
| application | `application/ingest_corpus.py` | **new** — idempotent ingestion (T026) |
| application | `application/export.py` | **new** — FR-016 precondition only (T033) |
| application | `application/export_resume.py` | **new** — the export use case (T036) |
| application | `application/retrieved_guidelines.py` | **new** — retrieval + precedence (T027), `citation_snapshot()` + `trust_level` (T028), `last_retrieval_ms` (T029) |
| application | `application/tailor_resume.py` | **MOD** — one line: `run.guidelines_used = citation_snapshot(guidance)` (T028). The only tracked backend source file this slice modified beyond config |
| application | `application/guidelines.py` | `GuidelineQuery.market` added; D2 docstring corrected |
| application | ⚠️ `application/ports.py`, `research_queries.py`, `research_company.py`, `citation_check.py` | slice 008 |
| infrastructure | `infrastructure/corpus/` | **new** — loader/chunker (T025) |
| infrastructure | `infrastructure/embeddings/` | **new** — fastembed adapter (T008) |
| infrastructure | `infrastructure/documents/render.py` | **new** — WeasyPrint behind a boundary (T031/T035). `__init__.py` untouched: the package already exists for CV import |
| domain | `domain/schemas/document.py` | **new** — `ResumeDocument`, `ResumeSection` (T031) |
| tests | `tests/conftest.py` | `DYLD_FALLBACK_LIBRARY_PATH` fallback so WeasyPrint imports on Apple Silicon |
| migrations | `alembic/versions/0015_knowledge_corpus.py` | **new** — corpus tables, `vector(384)` |
| migrations | `alembic/versions/0016_export_and_submission.py` | **new** — export/submit + status widening |
| corpus | `backend/corpus/` | **new** — 18 documents, 79 rules, + authoring contract |
| config | `config.py`, `Dockerfile` (+ **`fonts-dejavu-core`**, T032), `pyproject.toml` | embedding config; Pango/Cairo libs + baked model; `fastembed`/`pgvector`/`weasyprint`/`pyyaml`/`tiktoken`/`types-PyYAML` |
| tests | `tests/unit/test_corpus.py` (8), `test_corpus_loader.py` (12), `test_embeddings.py` (5), `test_export_ats.py` (5, T031), `test_export_determinism.py` (3, T032), `test_export_precondition.py` (10, T033), `test_export_template.py` (4, T034) | **new** |
| tests | `tests/integration/test_export_use_case.py` (13, T036), `test_export_api.py` (12, T037) | **new** |
| tests | `tests/integration/test_tailoring_ownership.py` | route-enumeration gates re-pinned 6 → 8 (T037) |
| frontend | `lib/api.ts`, `components/applications/tailor-tab.tsx` | export + download affordance (T037) |
| tests | `tests/integration/test_corpus_ingestion.py` (6), `test_guideline_retrieval.py` (**26** — T013–T018 and T029 added to T027's 15), `test_guideline_snapshot.py` (**7** — T028 plus OQ-006-A), `test_retrieval_wiring.py` (**10** — T030 plus OQ-006-B) | **new** |
| tests | `tests/unit/test_architecture.py` | import guard widened by 6 embedding runtimes + count assertion |
| docs | `CLAUDE.md` | refactored 11,448 → ~9,300 tokens; status moved here |
| specs | `specs/006-document-retrieval/` | full SDD artifact set incl. `corpus-research/` |

### Read these first

| File | Why |
|---|---|
| `specs/006-document-retrieval/tasks.md` T050 / T051 | The two appended tasks. **T050's design is decided and unbuilt; T051's is undecided.** Both block things |
| `backend/corpus/README.md` | The authoring contract. **Read before touching any corpus file** |
| `application/retrieved_guidelines.py` | T027. The precedence rule and the R13 argument for its shape |
| `infrastructure/corpus/loader.py` | The chunker-scope invariant — why prose can never become guidance |
| `specs/006-document-retrieval/research.md` §R13 | The measurement that reversed the topic decision |
| `specs/006-document-retrieval/corpus-research/source-register.md` | Every source, its licence, its disposition |

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

### Slice 006 — dependency and packaging (2026-08-27)

- **`sentence-transformers` is a 527 MB decision, not a library choice.** It was the obvious
  embedder and what `config.embedding_model` originally named. Its cp312 manylinux `torch` wheel is
  **527 MB**, on a backend image already measuring **1.01 GB** — roughly doubling it, for a
  component whose whole job is embedding ~35 short rules and one query string. Caught by checking
  PyPI metadata *before* installing. Replaced with fastembed/ONNX at **67 MB**, same 384 dimensions,
  same port, no migration.
- **"Pure Python" was wrong about WeasyPrint, and the failure is at import.** It binds Pango, Cairo
  and GObject through `cffi`. Without the native libraries, `import weasyprint` dies with
  `OSError: cannot load library 'libgobject-2.0-0'` — which reads as a code fault, not a missing
  apt package. Found by installing, not by reading. Fixed in the Dockerfile and verified **inside
  the built image**, because this project has repeatedly shipped things that worked on the host.
- **The `pgvector` Python package was never installed.** The *extension* has been enabled in the
  database since migration `0001`, which made it easy to assume the Python side existed. It did
  not; `from pgvector.sqlalchemy import Vector` fails.
- **A licence classifier can contradict the licence.** fastembed's PyPI classifier says
  `License :: Other/Proprietary License`; its repository `LICENSE` is Apache-2.0. The file governs.
  Worth knowing in a project that rejected PyMuPDF on licence grounds.

### Slice 006 — research and process (2026-08-27)

- **A "candidate source" arrived as byte-identical copies of a rejected one.** Three reference PDFs
  appeared under `corpus-research/examples/`; SHA-256 matched the assets of register entry S-017,
  rejected because its licence forbids derivative works and dataset use. Verified by hashing
  against upstream rather than trusting filenames.
- **Real CVs reached a public repository's working tree again.** 13 screenshots with real given
  names in the filenames, untracked and *not* ignored — one `git add -A` from publication. The same
  near-miss `CLAUDE.md` already records for `testing files/`. Now ignored.
- **The research digests would have poisoned the corpus if ingested.** They contain "defensible
  estimates when hard numbers are unavailable" and a "70–80% keyword coverage" quota — both direct
  violations of Principle III / AI-008. **Every fabrication-inviting claim traced to the
  SEO/resume-tool tier**; the institutional sources and the best practitioner source (Varun's
  MIT-licensed skill: *"Truth-preserving optimization… Never fabricate experience"*) said the
  opposite. Source authority and integrity correlate — that is itself a triage signal.
- **Thresholds that cannot fail are not gates.** SC-007/SC-008 were first written as 5 s and 10%.
  Retrieval *replaces* the 507-token rubric, so a 1,500-token ceiling adds ~1,000 input tokens
  across two calls ≈ **1.5%** of a $0.400 run, and latency tracks *output* tokens (~92 tok/s) so
  retrieval adds well under 500 ms. Both ceilings were 10–100× too loose. Re-pinned to **≤500 ms**
  and **≤2%**.
- **Four design decisions had no requirement behind them** until `/speckit-analyze` found it — the
  anti-fabrication corpus gate, byte-deterministic rendering, the four Israeli rules, and the
  `market` enum semantics. Tasks derive from FRs, so a decision with no FR becomes a feature nobody
  builds. Added append-only as FR-030–FR-039.
- **`quickstart.md` was never created.** A failed `cd` swallowed the heredoc while the shell still
  reported success, and `plan.md` referenced the missing file for two turns.


### Slice 006 — corpus, loader and retrieval (2026-08-28)

**Four drills passed when they should have failed. Every one meant the test was weaker than its
claim, not that the code was right.** This is now the most common failure mode in this project and
is worth expecting rather than discovering.

- **The chunker-scope drill (F10).** Removing the right-hand boundary — reading "everything after
  `## Rules`" — changed nothing, because prose paragraphs carry no `- ` items and the list-item
  pattern excluded them anyway. The fixture now carries a list item in the preamble **and** in the
  `## Removed` section, which is what makes either boundary load-bearing.
- **The tie-break drill.** Removing the `content_hash` tie-break left `test_retrieval_is_deterministic`
  passing, because PostgreSQL is incidentally stable across two calls in one process. **19 of 79
  chunks share a distance**, so the tie-break is real; a test now asserts tied chunks come back in
  hash order. Incidental stability is not a defined order and does not survive a vacuum or a replan.
- **The topic-intersection drill, twice.** Removing the intersection (hoisting *every* Israeli chunk)
  passed, because the test compared only the relative order of *global* chunks and inserting chunks
  between them does not reorder them. The second draft then demanded no Israeli chunk ever pass an
  unrelated global one — **which no implementation can satisfy**, since outranking a related chunk
  at position 25 means passing everything in between. The test now asserts the *justification*.

**Measurement and estimation**

- **`chars/4` overestimates by 23%.** The corpus measures 4,285 tokens by `cl100k_base` against a
  ~5,540 estimate. Every projection in the spec documents was built on the estimate. Use a real
  tokenizer for anything that feeds a budget.
- **The rubric was never a valid per-rule estimate for the corpus.** 42 tokens/rule came from bare
  imperatives; corpus rules carry their qualifications in-chunk (FR-037) and measure ~54–76. The
  extra tokens *are* the qualifications.
- **Embeddings cannot express "same topic".** See §2 and `research.md` R13. Semantic overlap and
  "makes a conflicting claim about the same decision" are different relations, and the corpus
  contains a clean counterexample to their being the same.

**Alembic and the schema**

- **Autogenerate emitted `pgvector.sqlalchemy.vector.VECTOR` with no import for it.** The generated
  migration raises `NameError` on first upgrade.
- **Autogenerate proposed 11 `server_default=None` strips** across five tables holding the paid
  evaluation data — pre-existing model/DB drift, out of scope, and silently behaviour-changing.
  **It will reappear on every future autogenerate.**
- **Alembic does not diff check constraints.** A widened Python enum with the database still
  refusing the values passes every gate and fails at the first real write. Write them by hand.
- **A new column named `storage_key` broke an unrelated architecture gate.**
  `test_the_uploaded_file_is_read_by_exactly_one_module` finds readers of the uploaded CV **by
  attribute name**. The new columns are `document_storage_key`; widening the gate's allow-list
  instead would have blinded it inside a growing file for ever.

**Dependencies**

- **fastembed's `lazy_load=True` does not defer the download.** Constructing `TextEmbedding` against
  an empty cache fetched 64 MB in 4.8 s. The first adapter therefore downloaded weights in its
  constructor and the unit suite pulled them twice — including a 768-dim model it then rejected.
  The suite was green; the only symptom was 14.75 s.
- **`pyyaml`, `tiktoken` and `types-PyYAML` were transitive-only.** Declared. Depending on somebody
  else's dependency tree is how a working install breaks on an unrelated upgrade.

**Sources and citations**

- **A register entry can be wrong about its own source, and the error creates the problem.** S-009
  was recorded as an *"aggregator of company ladders"* whose *"per-ladder licences differ"*,
  requiring resolution **per ladder before any is used**. It is one author's own three ladders, one
  repository, **MIT** (`sdras/career-ladders`). There was never a per-ladder question. The earlier
  check searched for Creative Commons, did not find it, and recorded absence as risk. **Read the
  licence file.**
- **Decorative citations make unsourced rules look sourced.** `universal-projects-and-education`
  cited S-018 while deriving nothing from it; `universal-structure-and-ordering` held two rules
  S-001 does not support, inheriting institutional standing they had not earned.
- **A sourced *fact* does not make an instruction sourced.** Two ATS rules were removed for this:
  the header/footer claim (S-007 documents which fields parse, never that a header fails) and the
  mixed-script claim (S-006 documents that non-English handling exists, never what to do about it).
  Both files record why, because both are among the most repeated claims in resume advice.
- **Per-document metadata makes the weakest rule wear the strongest tag.** Two practitioner-derived
  Israeli rules inherited `institutional` from sharing a file with S-002's guidance. The fix is a
  file split on trust level — which is why two documents now span two topics.


### Slice 006 — export, Phase 4 (2026-08-28)

- **`status.value` on a `String` column crashed every real refusal, and the unit tests could not
  see it.** `ensure_exportable` was tested only with `VersionStatus` members; a row loaded in a
  session that did not create it comes back as a plain `str`. Membership and `==` survive that
  because `VersionStatus` is a `StrEnum` — **`.value` does not**, and it was in the refusal
  message. The first real HTTP request found it. **This is the third appearance of the enum-vs-str
  trap in this project.** When a function takes a status, test it with the string a row actually
  carries.
- **An error state nobody renders reads as success.** The tailor tab set `error` on failure but
  only displayed it in the start view, so a 409 on the diff screen just stopped the button being
  busy. Silence after a click is indistinguishable from a completed action.
- **Ownership drilled on one route is not ownership.** The export POST had an ownership test; the
  document GET did not, and removing its `_owned_version` call changed nothing. The GET is the one
  that hands over somebody's résumé. **Drill each route, not each feature.**
- **A "no filled panels" assertion could not be written, because WeasyPrint paints a
  `border-bottom` as two filled rectangles spanning the whole element box.** No height threshold
  separates a hairline rule from a shaded panel. The decoration was removed instead, which turned an
  indefensible threshold into an exact property: the page carries no vector objects at all.
- **A single-column check that asserts "no word starts past the midpoint" fails on correct
  documents.** Running text crosses the midpoint on every line. Gutter detection — merge every
  word's x-extent and read the holes — is the property that actually distinguishes two columns; the
  boundary was then set by measurement (correct render 0.0pt, two-column render 39pt), not guessed.
- **A test that greps a whole Dockerfile for a package name passes when the package is deleted**,
  because the comment above the install line still names it. Strip comments and require the package
  to be its own instruction line.
- **Restoring a backup taken before a fix silently reverts it, and a partial test run stays green.**
  Happened during T035's drills. Snapshot *after* the fix, and re-read the source rather than
  trusting a subset run.
- **`session.expire()` then touching the object raises `MissingGreenlet`** — the documented gotcha,
  hit again while fixing a stale relationship in a test. Use an awaited `session.refresh(obj, [...])`.
- **A seeded object's collection is stale in the identity map**, so a use case that re-queries with
  `selectinload` still sees the empty list assigned at construction. The composed document came out
  **empty while two assertions passed anyway**.

## 5. Exact next steps

### A0 — 🎯 **T047: full gates, then Docker** · **owner: Claude** · next · nothing blocks it

Verify: `cd backend && .venv/bin/pytest -q && .venv/bin/mypy src && .venv/bin/ruff check .`
and `cd frontend && npm test -- --run && npx tsc --noEmit && npm run lint && npm run build`

**Everything but deployment is done.** Export, submission, immutability, revision lineage, the
insert-only gate, the API and affordance, corpus ingestion, and both measurements. **T047** runs
the gates on the host and then verifies in Docker; **T048** deploys. Nothing else is queued.

**Two things T047 should not be surprised by.** The backend image had to be rebuilt during T050
because it predated migration `0016` and `alembic current` failed *inside the container* against a
database already at `0016` — the known "compose does not pick up backend code changes" trap.
And **`exported_documents` and `submitted_resumes` are both empty locally**: export and submit are
tested end to end but have never been exercised by a person in a browser, which is exactly the
class of bug this project's own rule says the suite has never caught.

***Below this line, the T038–T043 notes are kept as the record of what those tasks found.***

**Three defects were found at T037 and are worth remembering**, because none was found by reading
code: `ensure_exportable` crashed on **every real refusal** (`status.value` on a `String` column
that loads as a plain `str` — the enum-vs-str trap again, and the unit tests passed enum members
only); a failed action on the diff screen rendered **nothing**, so a 409 looked like success; and
**ownership was never checked on the document download** — the drill found it, and it was the route
that hands over somebody's résumé.

**Two of the three items that were waiting for T036 are closed:** the contract's `APPROVED`
wording is corrected (it now reads *"has been approved and is not submitted — `READY` or
`EXPORTED`"*), and the guard is called first, before any side effect, asserted on spies rather
than only on the exception.

**The third is not closed and was deliberately not solved: it is now T051.** `ResumeDocument`
carries no employer, job title or dates, so an exported résumé lists bullets with nothing saying
where or when — while the corpus's vendor-sourced ATS rule requires employer and title as separate
readable text. **The exporter does not fabricate them.** It is not T036's (FR-017 defines the
exported text as the approved items and their order, which is what it exports), and it is a real
decision rather than a field: the role context lives on `WorkExperience`, not on the version, so
reading it live would leave part of an approved document **unsnapshotted and able to change
underneath its own checksum** (Principle IV). See T051.

**T034 changed one thing in the template**: the heading's `border-bottom` was removed. WeasyPrint
paints a bottom border as **two filled rectangles spanning the whole heading box**, so no height
threshold could separate a hairline rule from a shaded panel — and loosening one until the border
passed would have admitted the panels the assertion refuses. The decoration bought nothing a parser
reads, so the guarantee is now exact: **the page carries no vector objects at all**.

**Carried into T036 from T033 — a contract wording fix, not a code change.**
`contracts/export.md` states the export precondition as *"the version is `APPROVED`"*. Two problems:
the state is named **`READY`** in the model (T005), and the literal reading makes a version
exportable **exactly once ever**, because FR-019 moves it to `EXPORTED`. `ExportedDocument` has no
unique constraint on `resume_version_id` precisely so re-export is possible. The guard resolves
this as `{READY, EXPORTED}` and refuses `SUBMITTED` (terminal). **The contract should be amended to
"has been approved and is not submitted"** when T036 touches that section.

**Resolved at T032 (A1 + B, the author's decision).** `fonts-dejavu-core` is now an **explicit apt
dependency** of the backend image, and FR-031 is **scoped to one runtime environment** in both
`spec.md` and the export contract. Vendoring the font (A2) was rejected: cross-machine byte
identity is not a requirement any spec establishes. **The test was not weakened** — it renders the
same document twice in two separate processes and demands byte-identical output.

**No metadata normalization was written, deliberately.** Measured first: **WeasyPrint 69.0 emits no
`/CreationDate`, no `/ModDate` and no `/ID`**, so R10's premise is false at this version and
T035's "pin metadata and timestamps" had nothing to pin. The tests are the gate that catches a
version bump reintroducing one.

*Background — the earlier note, which was half wrong and is kept because the correction is the
useful part:*

**Found at T031, and half of it was WRONG — corrected 2026-08-28.** The claim was *"neither host
nor container has DejaVu"*. The host half holds: macOS resolves to **Verdana**. **The container
half did not.** Built against the Dockerfile's exact package list, `python:3.12-slim` carries **8
DejaVu font files**, so production renders in the font the template asks for and the divergence is
**dev-host vs container**. The claim was generalised from the host to an image nobody had opened.
**The real risk is that DejaVu arrives transitively rather than by declaration** — a base-image
change would alter output silently, which is exactly FR-031's *"surfaces only on a re-export"*.

**Also measured, and it contradicts R10:** two renders in separate processes 2.5s apart are already
**byte-identical**; the PDF's only metadata is `Producer: WeasyPrint 69.0` — no `CreationDate`, no
`/ID`. R10's premise that timestamps make renders differ is **not true of WeasyPrint 69**, so
T035's pinning may be a no-op at this version. The test still earns its place: it is what catches a
version bump reintroducing one.

**Environment, now required for the backend suite**: `brew install pango` is installed but is **not
sufficient on Apple Silicon** — Homebrew's prefix is off the dynamic linker's search path and
WeasyPrint `dlopen`s GObject at import. `tests/conftest.py` sets `DYLD_FALLBACK_LIBRARY_PATH` as a
fallback so a bare `.venv/bin/pytest` works. **T049's documented prerequisite was incomplete**;
the doc sweep at T046 recorded the real one in `CLAUDE.md` under *Environment and tooling*:
`brew install pango` is necessary and **not sufficient** on Apple Silicon, and `conftest.py` sets
`DYLD_FALLBACK_LIBRARY_PATH` so a bare `.venv/bin/pytest` works.

### A — **T050: give `ingest_corpus` a caller** · **DONE 2026-08-28** · no longer blocks T048

**T001–T030 are done. T028, T029 and T030 are accepted and must not be changed.** Phase 3 is
complete: tailoring runs on retrieved, cited guidance and the workflow is unchanged.

**It does not yet do so in a deployed environment.** `ingest_corpus` has no caller outside the
test suite, so a deployed backend retrieves against an empty corpus, falls back to the static
rubric on every run, and records `empty_corpus` faithfully. **No task in T031–T049 covered this**;
T050 was appended for it. The code is correct and the slice does nothing — which is the worst
shape a gap can have, because every gate is green.

**DECIDED 2026-08-28 by the author. OQ-006-C is closed. IMPLEMENTED at T050 the same day.**
`src/careerhq/ingest.py`, `preDeployCommand = "alembic upgrade head && python -m careerhq.ingest"`,
documented locally as `docker compose exec backend python -m careerhq.ingest`. Measured in the real
image: **18 documents, 79 chunks, exit 0, ~5.7s**; a second run is **0/0/0/0**; a dead database
exits **1**. The local corpus is populated for the first time. **Production is not** — see T048.

```toml
# backend/railway.toml
preDeployCommand = "alembic upgrade head && python -m careerhq.ingest"
```

Four parts, all settled: ingestion runs **pre-deploy**; **after `alembic upgrade head`** (the `&&`
is the ordering guarantee — `knowledge_chunks` must exist first); the command is
**`python -m careerhq.ingest`**; and **the application startup hook is ruled out** — not
deprioritised, ruled out, because it pays a model load on every container start and races two
replicas against `uq_knowledge_chunks_document_content`, both of which scale with replica count
and would surface as a mysterious boot failure after an unrelated scaling change.

Verified against the real build context: **19 corpus `.md` files and 0 test files reach the
image**, and the weights are baked (T008/D3), so pre-deploy ingestion makes no network call.
Pre-deploy already reaches the private database. An **operator command** was rejected too: a corpus
edit would ship without reaching the database. **Not** in `entrypoint.sh` either — a stale schema
breaks the application, a stale corpus does not.

**This is not a config line.** There is no CLI in this project at all (no `[project.scripts]`, no
`__main__.py`), so `python -m careerhq.ingest` has to be written — with a commit, the
`IngestionReport` logged in `extra={…}`, and a **non-zero exit on failure**, without which the
pre-deploy placement buys nothing. Full scope under **T050**.

Also unblocked now that `warm_up()` has a caller: **T044 may measure SC-007** — but a measurement
taken before T050 measures the fallback path, not retrieval.

Verify: `cd backend && .venv/bin/pytest -q && .venv/bin/mypy src && .venv/bin/ruff check .`

### B — Slice 006's design decisions · **all three closed; one still needs building (T050)**

**Newly surfaced by OQ-006-A's analysis, and NOT part of that decision.** The tailoring route
returns `run.guidelines_used or []`, so a `NULL` reaches the client as an empty list — the exact
conflation of *unknown* with *advised nothing* that the column now refuses. It affects a run that
failed before retrieval. A route concern, not a persistence one; unowned, and small.

**OQ-006-A — DECIDED 2026-08-28 by the author: YES. Implemented.** ***A run that has successfully
retrieved guidance records it, even if the run later fails.*** Written **immediately after
retrieval, before the graph** — not on the failure path, and the success-path assignment is gone,
so success and failure cannot drift into two different records.

| Run fails | `guidelines_used` |
|---|---|
| **Before** retrieval | **`NULL`** — nothing was fetched, and `NULL` means unknowable |
| **After** retrieval | **the full T028 citation** — those rules reached the Plan prompt and were billed for |

***`[]` is never written for either.*** An empty list asserts a run was advised nothing, which is a
claim about a retrieval that never happened. **Why after retrieval rather than on the failure
path**: Principle V requires every WorkflowExecution to preserve *its inputs*, and three of the
four things it names already survive a failure because they are written at run creation.
`guidelines_used` was the only input written at the end — an accident of when the field was added.
The precedent is `UsageRecorder`, verbatim: *a run that reads as free is worse than one that reads
as unrecorded, because nobody investigates a free run.*

**Consequences**: the three existing failed runs stay `NULL` for ever; **slice 007 must filter on
`status`**, not on the presence of a snapshot; and **T029's latency number is unaffected** — it
stays unpersisted, and the parallel question for it is *not* answered by this decision. Full
record in `tasks.md` under T030.

**OQ-006-B — DECIDED 2026-08-28 by the author, and implemented.** ***V1 tailors every run for the
Israeli market.*** `tailor_resume.V1_TARGET_MARKET = "israel"`, passed explicitly into
`GuidelineQuery`; FR-038 precedence now fires in production, where it previously never did.
**Nothing infers the market** from the posting, the location or the profile — a wrong constant is a
line someone can read, a wrong inference is not. **`GuidelineQuery.market` still defaults to
`global`**, deliberately: moving the default would make every future caller Israeli by omission.
The extension path is a real product-level market selection, at which point the constant becomes
that field's default. Full record in `tasks.md` under T030.

**OQ-006-C — CLOSED 2026-08-28, decided by the author. Implementation not started; T050 owns it.
Blocks T048.** *`ingest_corpus` has no caller outside the test suite.* Decided:
`preDeployCommand = "alembic upgrade head && python -m careerhq.ingest"` — pre-deploy, after the
migration, by that command, **with the application startup hook ruled out**. Locally a documented
`docker compose exec` equivalent, **not** a line in `entrypoint.sh`. Evidence, rejected
alternatives and T050's scope are in §5 A and under **T050**.

### C — T044/T045 own the ceiling question · **owner: Claude, later in the slice**

The 1,500-token ceiling **has not been moved and must not be** on arithmetic. Integrity pins 795
tokens (53%); D5's floor is ~1,890 at the measured 54/chunk and still overshoots. T044 measures
real retrieval latency; T045 measures cost against a `StaticGuidelines` baseline **in the same
session**, so pricing conditions match. Those two are the evidence a different ceiling would need.

**Blocked by T050, and measurement at this handoff made that concrete.** The local database has
**0 knowledge documents and 0 chunks** — the corpus has never been ingested anywhere outside the
test suite. Running T044/T045 today would measure the **static-fallback path** and report it as
retrieval. Do T050 first, then measure.

### D — Evidence-quality follow-ups · **owner: the author** · recorded, not blocking

Neither triggers a register-mandated removal, and **no rule should change because of them**:

- **F8** — 9 institutional rules rest on gov.il sources (S-001, S-002) whose licensing is
  **unverified**. The register calls this low-risk under authored rules and records the check as
  owed. Given the S-009 finding, treat "low-risk" with less confidence than the register does.
- **F9** — **6 of 79 rules** rest on `summary_only` sources (S-006/7/8), all of them the ATS rules.
  Bounds how much weight `vendor_documented` can carry. *(Recounted 2026-08-28: this was 19 before
  S-009's licensing was resolved and its verification moved `summary_only` → `read`, which took the
  8 seniority rules out of the count. The earlier figure was carried forward without re-measuring —
  exactly the drift this file exists to prevent.)*

### D2 — T046: move the durable gotchas into CLAUDE.md · **owner: Claude, at Phase 6**

§4 gained a large block this session (autogenerate's two defects, Alembic not diffing check
constraints, `lazy_load` not deferring the download, the four drills that passed). **Several are
durable engineering rules rather than slice history**, and T046 is the tracked task that moves them
— `CLAUDE.md` was refactored this session to hold exactly that kind of rule and nothing about
status. Do not move them ad hoc; do it once, at T046, so the two files do not drift again.

### E — T088, the last Slice 005 task · **owner: the author** · needs a paid run

Deliberately open. Deployment and infrastructure were verified; the *real paid production run*
acceptance criterion was consciously deferred. **Do not close it by weakening the criterion.**

### E2 — 🔴 **Back up the local evaluation data** · **owner: the author** · new at this handoff

**$2.431522 of paid evidence exists in one Docker volume on one machine and nowhere else.** 7
tailoring runs, 8 match analyses, 4 versions — measured today. Production has 0 versions and 0
runs. `docker compose down -v` destroys all of it, and CLAUDE.md documents that command as the way
to get a clean database; §5A says the data must not be deleted without ever saying where it is.

Cheapest fix, and it needs no decision:

```bash
docker compose exec -T postgres pg_dump -U careerhq careerhq > careerhq-eval-$(date +%F).sql
```

Keep it outside the repository — it contains a real profile. **Slice 007's benchmark is measured
against this data**, so losing it costs the evaluation slice its baseline as well as the money.

### F — Slice 003 User Story 3 · **still blocked on the author** · 11 tasks

Needs `backend/tests/fixtures/jobtracker_export.csv`. **Checked 2026-08-28: still absent.**

### G — Slice 008 · **owner: the parallel session** · coordinate, do not touch

It owns `application/ports.py`, `research_queries.py`, `research_company.py`,
`citation_check.py` and `domain/schemas/research.py`, and has **no `tasks.md`**. It has added no
migration; **head stays `0016_export_and_submission` and whoever writes next rebases onto it.**
OQ-E (the 90-day staleness threshold) still awaits the author's approval.

### H — Commit and push · **the author's call** · nothing is staged

Two slices of uncommitted work sit on `005-resume-tailoring`. **Before any `git add -A`:**

```bash
git check-ignore -v "specs/006-document-retrieval/corpus-research/examples/cv 1/elnatan_after_p1.png"
```

must report the ignore rule. Verified 2026-08-28: all 16 files under `examples/` are ignored and
**0 are tracked**. The two S-021 research PDFs under `corpus-research/sources/research/` are **not**
ignored and a `git add -A` would stage them — left untracked on the author's instruction, kept, and
not to be published.

### I — Rotate the `logo.dev` token in `job-tracker-web` · **owner: the author**

`nirtituani/job-tracker-web` is public and hardcodes a logo.dev token (`ApplicationTable.jsx:4`).
A different repository; nothing here depends on it, which is why it keeps being forgotten.

## 5A. Real data that must not be deleted or modified

This is the project's only evaluation evidence. It was paid for.

| Record | Why it must survive |
|---|---|
| Version `a8f1e4b7` + runs `a76bd349`, `cd27b092`, `2615363e` | Cellebrite. Two failures and the first successful run, on one reused draft — also the evidence the retry-reuse fix works |
| Version `c582d938` + run `6356fb4e` | Zipher. The only run with a revision, and the 0.167 adherence sample |
| Match `ad25de2c` (Voyantis, 0/100, **0 requirement rows**) | The historical invalid analysis. **Deliberately not deleted.** It is rendered as `nothing_to_score` rather than a verdict, which is the spec's own edge case finally implemented — so it also proves that fix |
| Match `1285d10a` (Voyantis, **84 Strong**) | The scoreability fix working on real data |
| All 8 match analyses | $0.309312 of real measurement |
| Run `ff0e310c` (succeeded, 0 revisions, $0.307106) | **Not in R5's table.** A successful zero-revision sample, which the distribution has fewest of |

**Total real spend to date: $2.431522** — **$2.122210 tailoring across 7 runs**, $0.309312 match
across 8 analyses. Measured by `SUM(cost)` at the T037 handoff. *(This line previously read
"roughly $1.43 — $1.12 tailoring", which was wrong before the seventh run and wronger after it.)*

***Where it lives, which nothing here used to say: the LOCAL Docker volume only.*** Production has
**0 versions and 0 runs**. `docker compose down -v` destroys all of it, and CLAUDE.md documents that
command as the way to get a clean database. **There is no backup.**

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
