# Research: Document & Retrieval (Phase 0)

**Date**: 2026-08-27 · **Input**: [corpus-research/](corpus-research/) — 22 registered sources,
triaged; `before-after-analysis.md`; the shipped 12-rule rubric.

Measured facts, source-backed claims and interpretation are labelled throughout, because this
slice's central risk is treating a repeated assertion as an established one.

---

## R1 — Corpus provenance: curated only *(decision D1)*

**Decision.** The corpus is a curated, version-controlled house asset under `backend/corpus/`.
User-uploaded guideline documents are out of scope.

**Rationale.** Retrieved text enters the Plan and Draft prompts — the prompts of the one component
that writes claims on a person's behalf. A curated corpus is reviewed like code, which is what
makes FR-013 ("data, never instructions") structural rather than aspirational, and what keeps
citations resolvable (FR-012).

**Alternatives rejected.** User upload makes every chunk attacker-influenceable, changes the data
model from one global corpus to per-user corpora, and deprives slice 007 of a fixed corpus to
measure retrieval quality against.

---

## R2 — Authored rules, not ingested digests *(new; supersedes an earlier assumption)*

**Decision.** Corpus content is **written by CareerHQ in its own words, citing sources**. The two
research digests in `corpus-research/sources/research/` are `evidence`, never corpus content.

**Rationale (measured).** The digests are secondary, per-source entries of the form
"Source / URL / Summary". A chunk lifted from one reads *"Indeed presents a 6-part framework…"* —
text **about** guidance rather than guidance. Three consequences: it is a poor retrieval unit for
a Draft node; the citation would point at our own summary rather than at the source; and the
digest format flattens authority, presenting Technion and university career centres in the same
visual form as resume-tool SEO blogs.

**Bonus effect.** Authoring resolves most licensing exposure — facts are not copyrightable, their
expression is.

---

## R3 — Retrieval called once, before the graph *(decision D2)*

**Decision.** Guidance is retrieved a single time in the use case and shared by Plan and Draft,
exactly as slice 005 already does. **Rejected: per-node retrieval. Rejected outright: retrieval as
a graph node.**

**Rationale (measured).** The rendered guidance block is **507 tokens — 5.3% of the ~9,630-token
Draft prompt**, and retrieval replaces it with at most **1,500 tokens** under the FR-014 ceiling — ≈15.6% of that prompt, and ≈19 rules at the measured 76 tokens/rule. Plan-aware retrieval's real job
is fitting a context budget, and at this scale no such budget binds.

*Corrected 2026-08-28.* This read "~1,690 tokens even at 40 retrieved chunks", computed at 42
tokens/rule. At the measured 76, 40 chunks would be ~3,040 tokens and could never be retrieved
under the 1,500-token ceiling anyway. Quoting the ceiling instead removes the unreachable
hypothetical; **D2 is unchanged** — the bound is now smaller than the figure it replaces.

**Rationale (interpretation).** Resume-writing guidance is largely **job-independent** — "never
invent a number", "single column" hold for every posting. The plan decides which *profile items*
to emphasise; it does not imply different *writing advice*.

**Consequence.** FR-002 needs no amendment. `GuidelineQuery.section` stays unused, and its
docstring now says so. The `GuidelineSource` docstring has been corrected to match the
implementation, resolving the doc/code conflict explicitly as the constitution requires.

**Revisit only if** slice 007's retrieval-quality metric shows the shared query missing guidance a
per-node query would have found.

---

## R4 — Embeddings: local, behind an application port *(decision D3)*

**Decision.** A dedicated `EmbeddingSource` port in `application/`, implementation in
`infrastructure/`, defaulting to the local model `config.embedding_model` already names.

**Rationale (measured).** `config.py` already carries
`embedding_model = "sentence-transformers/all-MiniLM-L6-v2"` with the comment *"Anthropic has no
embeddings endpoint, which is why this is not an Anthropic model."* This cannot travel through the
`complete()` seam. `test_the_application_layer_imports_no_provider_sdk` forbids importing the
library in application code.

**Alternatives rejected.** A hosted embedding provider adds a second paid dependency and key, puts
a network call in the tailoring path, and sends query text derived from the user's profile and job
to a third party. Local execution also preserves the existing property that the stack runs with no
API key.

**Consequence.** Vector dimension is a schema commitment — MiniLM-L6-v2 is **384**.

***Superseded during implementation, 2026-08-29 (recorded at T053).*** The decision above
— local embedding behind an application port — **stands unchanged**. What changed is the
model and the runtime behind it: `1cf9a70` moved from `sentence-transformers/all-MiniLM-L6-v2`
to **`BAAI/bge-small-en-v1.5` through fastembed/ONNX**, and `config.py` records the reason
— *"67 MB instead of a 527 MB torch wheel on top of a 1 GB image, for a component whose
whole job is embedding ~95-130 short rules and one query"*. The weights are baked into the
image at build time so a cold container makes no network call, which is what D3 actually
requires.

**The width did not change**, which is why no migration followed and why the paragraph
above still reads correctly about the schema: bge-small-en-v1.5 is **also 384**.

**That is precisely the hazard.** Two 384-dimension models are indistinguishable to
`EMBEDDING_DIMENSIONS`, to `vector(384)` and to the adapter's registry width check, and
ingestion's identity is `content_hash` over the rule text — so swapping the model leaves
every hash matching, embeds nothing, reports `0/0/0/0` and exits 0 while queries run
against vectors a different model produced. Measured on the real corpus: re-embedding a
stored chunk gives cosine **1.000000** for the model that wrote it and **0.345992** for
the other. Migration `0018` records the model on `knowledge_documents` and ingestion
refuses on a mismatch; that guard, rather than the choice of model, is what T053 delivered.

*(The original text is left as written rather than edited, because it records what was
decided at the time and why. `.env.example` carried MiniLM until T053 corrected it.)*

---

## R5 — Chunking: one rule, one chunk, qualifications included *(decision D4)*

**Decision.** One authored rule = one chunk. **A rule's qualifications and exceptions live in the
same chunk as the rule.** Identity is a content hash; the chunk belongs to a document identity and
version; the recorded citation carries
`{document_slug, document_version, content_hash, locator, text}`.
*(Corrected 2026-08-28: this sentence said `document_id` and `chunk_hash`. Both are prose drift —
the citation is by **slug**, because an id is not resolvable by a reader, and the hash column is
**`content_hash`** everywhere it actually exists. No code or schema changed.)*

**Rationale.** This is forced by the content, not chosen as a default. Several Corpus V1 rules are
**conditional**, and a condition separated from its rule is a materially worse instruction:

> "Military service can be a credibility signal" — retrieved *without* "where relevant to the
> candidate and the role" — instructs the model to emphasise military service universally.

**Verification property.** Recompute the hash of the stored text and look it up: a match proves the
guidance existed in the corpus unaltered; a miss proves drift, loudly. Unchanged rules keep their
hash across re-ingestion; edited rules become new chunks, which is the honest outcome (FR-012).

**Alternatives rejected.** Positional or offset-based citations break on every re-ingestion.
Fixed-size overlapping windows — the generic RAG default — would split rules from their conditions,
which is the specific failure above.

---

## R6 — Corpus size, revised *(decision D5 input)*

**Measured, 2026-08-27.** The shipped rubric is 12 rules / **507 tokens** → ~42 tokens per rule.

**Measured again, 2026-08-28, on authored corpus rules.** The four-file review sample is 18 rules
/ **~1,375 tokens** → **~76 tokens per rule**, 1.8× the rubric figure. Both numbers are measured;
neither replaces the other, because **they measure different things**. The rubric's rules are bare
imperatives. A corpus rule carries its qualifications and exceptions *in the same chunk* — FR-037
requires exactly that, and R5 records why ("military service can be a credibility signal" retrieved
without "where relevant to the candidate and the role" is a materially different instruction). The
extra 34 tokens per rule **are the qualifications**, so the rubric was never a valid per-rule
estimate for this corpus.

**Estimate, superseded.** Corpus V1 ≈ 95–130 rules, ~4,000–5,500 tokens, computed at 42 tokens/rule.

**Estimate, current.** Corpus V1 ≈ **95–130 rules, ~7,200–9,900 tokens**, computed at the measured
76 tokens/rule. The **rule count is unchanged** — the category split still stands at universal
30–40, Israel 10–14, ATS 12–15, integrity 12–15, tailoring method 10–15, role/seniority 20–30.
Only the token projection moved, and it moved because the rules are the shape the contract
requires. **Rules were not shortened to recover the old estimate**; that would trade a measured
number for a worse corpus.

**Revised down** from an earlier 150–250 / 6,300–10,500. Source-quality triage removed the SEO
cluster, which contributed duplication rather than distinct rules.

**Consequence, stated plainly.** The corpus fits in context many times over. Retrieval is not a
scaling necessity at V1 — see plan.md *Why RAG*. The retrieved-context ceiling (FR-014) should be
set generously at first (~15–25 rules) and tuned with evidence, not guessed now.

**Two numbers that must not be conflated.** *Corpus size* is how many rules exist to search over:
95–130 rules, ~7,200–9,900 tokens. *Retrieval count* is how many arrive in one prompt: whatever
fits under the 1,500-token ceiling, **≈19 rules at 76 tokens each**. The ceiling is a **budget per
run**, never a target for how large the corpus should be — a corpus is supposed to hold more than
any one run needs, which is the entire point of retrieving from it.

**One consequence is open and is deliberately not resolved here.** D5 sized the 1,500-token ceiling
*from the floor upward* at ~35 rules: integrity 12–15, Israel 10–14, topic-relevant 10–15. At 76
tokens/rule that floor is ~2,660 tokens and **does not fit** — integrity alone would take 900–1,140
of the 1,500, leaving room for roughly 5–8 rules of everything else. The ceiling is **unchanged**:
it is not moved on an arithmetic argument when the thing it governs, actual retrieval behaviour,
has never been measured. T044 measures it; if the pinned integrity set genuinely crowds out
topical guidance, that measurement is what justifies a new number, and this paragraph is what it
answers.

---

## R7 — Israel-first, bounded by evidence

**Decision.** Four Israeli-market rules enter Corpus V1 as normative, confirmed by the product
owner and corroborated by evidence. Universal guidance stays universal; **no Israeli distinction is
manufactured where evidence does not support one.**

| Rule | Scope | Corroboration |
|---|---|---|
| Do not include age or date of birth | unconditional | Drushim (secondary); absent from all three reference CVs |
| Do not include a full residential address; city and country suffice | unconditional | Drushim; reference CVs show `Tel Aviv, Israel` + phone, no street |
| Military service, **where relevant to candidate and role**, presented as translated capability | **contextual** | S-002 (Israeli MOD, institutional) — the strongest Israel-specific source found |
| Professional experience before education, **for experienced candidates** | qualified | Techmonster; all three reference CVs; inverse holds for students/new grads per S-002 |

**Interpretation.** Most verified Israeli institutional guidance is, in substance, universal. Only
demonstrated differences are tagged `market: israel`; the rest stay `global`.

**Out of scope by product decision.** Anonymised submissions and agency-vs-direct etiquette are
hiring-process concerns, not CV-writing rules. Retained in the research record only.

---

## R8 — Truth-preservation: two rejected claims *(safety-critical)*

**Measured.** The research material contains advice that would instruct fabrication:

1. **"Defensible estimates when hard numbers are unavailable"** (STAR/PAR cluster) — directly
   contradicts rubric rule 3 and AI-008.
2. **"Target 70–80% coverage of required keywords"** (keyword-tailoring cluster) — a quota, and
   quotas pressure fabrication when the profile cannot meet them.

**Decision.** Both **rejected** from the corpus and recorded as rejected, so they cannot re-enter.
Keyword *mirroring* is adopted; the *quota* is not.

**Correlation worth recording (interpretation).** Every fabrication-inviting claim traces to the
resume-tool/SEO cluster. The authoritative sources and the strongest practitioner source point the
other way — `varunr89/resume-tailoring-skill` (MIT, 706 stars) opens with *"Truth-preserving
optimization… Never fabricate experience"* and requires a truthfulness justification for every
reframe. Source authority and integrity correlate, which is itself a triage signal.

---

## R9 — Practitioner sources: methodology, not rules

**Measured.** `varunr89/resume-tailoring-skill` is **MIT-licensed** — usable with attribution.
`JaimeYeung/Resume-Tailor-AI` has **no licence file**, therefore all rights reserved by default —
**not usable**. `shahar84/…/shahar-cv-optimizer` carries a personal-use licence prohibiting
derivative works and dataset use — **rejected**, and its three design PDFs are byte-identical
assets that must not be published.

**Decision.** Varun's material is `evidence-only`. It is a *matching algorithm* (weighted
Direct/Transferable/Adjacent/Impact scoring), not CV-writing guidance, and CareerHQ already has its
own verdict model from slice 004.

**Two findings adopted from it.** Its "Keyword Alignment" strategy supports rubric rule 4. Its
"Abstraction Level" strategy supplies the missing qualification for technical specificity:
specificity should move **up or down** depending on whether the target role values it — a
language-agnostic role wants "automated evaluation system", a specialist role wants the stack named.

**Convergence, noted not adopted.** Varun's Direct/Transferable/Adjacent/Gap taxonomy and Shahar's
five-verdict scheme both closely resemble CareerHQ's slice-004 verdicts, arrived at independently.
Three independent convergences is validation of the design, not a reason to import anything.

---

## R10 — Export: separate the requirement from the renderer *(decision D7)*

**Decision.** "ATS-safe" is specified as **six mechanical assertions**, renderer-independent:

1. Extracted text equals the approved items, in approved order (FR-017).
2. Real text, not images of text.
3. Single-column reading order — verifiable from word x-coordinate clustering.
4. No table structures (FR-018).
5. Character integrity — no ligature or Unicode mangling on round-trip.
6. **Byte-determinism** — see R11.

**Verification uses `pdfplumber`, already a dependency** and already trusted for CV import. Render
with one library, verify with an independent extractor: a genuine round-trip, not self-attestation.

**Renderer decision (D7, resolved).** WeasyPrint — BSD-3, no browser binary, and the template
stays reviewable HTML/CSS. Satisfies the recorded licensing discipline that rejected PyMuPDF for
AGPL. **It is not pure Python**: it binds Pango, Cairo and GObject through `cffi`, so the image
needs those system libraries and a missing one fails at *import*, not at render (T049).

**Measured note.** All three reference CVs are **single-column** — an earlier reading of
"two-column" came from a crude x-distribution heuristic and was wrong; the right-half tokens are
ordinary full-width prose wrapping.

---

## R11 — Checksum and immutability *(decision D8)*

**Decision.** The immutable artifact is the **rendered PDF bytes** in object storage, plus an
insert-only `SubmittedResume` row. The checksum is **SHA-256 over exactly those stored bytes**,
computed when the bytes are first persisted at export and re-verified at submission.

**Rationale.** Constitution IV requires "an immutable snapshot with a **stable file checksum**" —
*file*, meaning bytes, because the obligation is to reproduce exactly what was sent.

**The coupling that must not be missed.** PDFs embed a creation timestamp and document ID by
default, so **two renders of identical content produce different bytes**. Byte-determinism is
therefore a **product requirement on the renderer** (R10 assertion 6), not a nice-to-have — cheap
to specify now, expensive to discover after submissions exist.

**What verification proves**: the stored file is byte-identical to what was recorded. **What it
does not prove**: that an employer received it, or that its content still matches the profile — it
deliberately will not, which is the point of a snapshot.

---

## R12 — Evidence-confidence gaps *(recorded, not blocking)*

Per product decision, these are recorded rather than researched further. None changes the
architecture; each affects which marginal rules ship and at what `trust_level`.

1. **Israeli ATS ecosystem** — no evidence. Every ATS source is a global vendor or a US university
   career centre. ATS rules therefore ship tagged `market: global`, not `israel`.
2. **English-CV prevalence in Israeli high-tech** — narrowed, not closed. JobMob is a long-standing
   English-for-Israel guide and the reference CVs are English with Israeli contact details, but
   nothing establishes English as *standard* for tech specifically.
3. **Primary-source verification of marginal Israeli claims** — all reach us through digests. The
   unreconciled ones (recruiter scan time 20–30s vs ~6s; strict one page vs 1–2 pages) are
   **not promoted** to rules.

---

## R13 — Can embeddings express "same topic"? *(T027 experiment — measured 2026-08-28)*

T025 deferred the `topic` field to T027 with an explicit test: can embedding similarity express
the FR-038 precedence rule — *"an `israel` chunk outranks a `global` chunk **on the same topic**"* —
reliably and reviewably? **It cannot.** Measured over the shipped corpus, 79 chunks embedded with
`BAAI/bge-small-en-v1.5`, 7 israel × 72 global = **504 cross-market pairs**.

**Measured.** Two labelled cases exist in the corpus, both established by the corpus review:

| Case | Pair | Cosine | Rank |
|---|---|---|---|
| **True positive** — precedence *should* fire (F4) | `israel-military-and-section-order#2` ↔ `universal-document-conventions#1` (section ordering) | **0.650** | **326 of 504** |
| **True negative** — precedence must *not* fire (F6-B) | `israel-military-and-section-order#5` ↔ `universal-structure-and-ordering#4` (volunteering) | **0.861** | **1 of 504** |

Cross-market distribution: min 0.496 · **median 0.670** · p90 0.736 · p99 0.789 · max 0.861.

**The true positive scores below the median. The true negative is the single highest pair in the
corpus.** The negative outranks the positive by **0.211**, so the ordering is inverted and no
threshold can separate them:

| Threshold | Pairs firing | True case | Complementary case |
|---|---|---|---|
| 0.60 | 435 / 504 (86%) | HIT | **wrongly hit** |
| 0.65 | 322 / 504 | miss | **wrongly hit** |
| 0.70 | 147 / 504 | miss | **wrongly hit** |
| 0.75 | 29 / 504 | miss | **wrongly hit** |
| 0.80 | 2 / 504 | miss | **wrongly hit** |
| 0.85 | 1 / 504 | miss | **wrongly hit** |

**Interpretation** *(this is a reading, not a measurement)*: "same topic" in FR-038 means *makes a
conflicting claim about the same decision* — a logical relation. Cosine similarity measures surface
semantic overlap. The two labelled cases are precisely where those come apart: the F4 pair address
one decision in different vocabulary, while the F6-B pair share vocabulary (volunteering, youth
movements) while making complementary claims about different things.

**Consequence, implemented.** T027 suppresses nothing. Both markets' guidance competes on relevance
and both may be returned, which FR-038 permits because global guidance **remains applicable to
Israeli-market CVs**. The cost of doing nothing is a little redundancy; the cost of a threshold is
suppressing correct guidance on up to 86% of cross-market pairs.

**A second blocker, independent of any topic signal.** `GuidelineQuery` carries `role_title`,
`requirements` and `section` — **no market**. Even with perfect topic detection, retrieval cannot
tell whether the CV it is serving is Israeli-market, and FR-038 scopes precedence explicitly *"for
Israeli-market CVs"*. Precedence needs a topic signal **and** a market on the query; it currently
has neither.

**Resolved 2026-08-28 — the objection recorded at T025 no longer stands.** It was that a
hand-maintained taxonomy would duplicate what the embeddings classify; R13 shows the embeddings do
not classify this at all. `topic` is now a **document-level list** from a 16-value vocabulary
(`Topic` in `domain/models/knowledge.py`) derived only from the 79 shipped rules, and
`GuidelineQuery.market` closes the second blocker. Precedence is a set intersection: deterministic,
reviewable, nothing to tune. A list rather than a scalar, so the two multi-subject documents did not
have to split. See T027 in `tasks.md` for the assignments.

---

## R14 — SC-007 measured: retrieval latency *(T044, measured 2026-08-28)*

**Result: SC-007 is MET, by a factor of 20.**

| | ms |
|---|---|
| min | 10.3 |
| p50 | **12.1** |
| p95 | **20.9** |
| max | **24.8** |
| mean | 13.0 |
| *initialisation (`warm_up`), **excluded*** | *133–570* |
| *first call after warm-up, reported separately* | *35–40* |

n=30, three postings of different shapes rotated so the figure is not one embedding length
and one candidate ordering. Taken **inside the backend image** — the only place with both
the baked weights and the ingested corpus — against 79 chunks with the configured 1,500-token
ceiling, through `build_guideline_source()`, which is the seam `run_tailoring` uses.

**Every figure is `last_retrieval_ms`**, the instrumentation FR-039 required for exactly this
(*"so SC-007 can be measured rather than derived"*). A stopwatch around the call would have been
a second implementation of the boundary, and the two would drift.

**The boundary, stated because "retrieval latency" has four plausible readings.** Timed: query
construction, `embed_query`, the pgvector query, ranking, market precedence, ceiling selection —
start of the operation to the final selected set. Not timed: model initialisation, and the
decision to fall back, which happens after the selection is final.

**Initialisation is excluded by construction, and it is not small.** Removing the `warm_up()`
call put **415 ms** into the first retrieval — on its own, 83% of the whole budget. It does not
reach the steady-state figure because T030 warms the model at startup, and the script reports the
first post-warm-up call separately so a regression there cannot hide inside an average.

**What SC-007 does not cover.** This is the latency of the retrieval *operation*. The other half
of M-001 — the end-to-end tailoring run — remains carried forward to slice 007, and slice 005
already recorded SC-001 as missed at 2m50s–4m01s. Retrieval's ~12 ms is not what makes a run slow.

**Not measured against `bge-small-en-v1.5`.** The configured model is MiniLM (see the finding in
tasks.md under T044); a deployment that used the Dockerfile's baked model would need re-measuring,
though both are 384-dimension models of similar size and the figure is dominated by neither.

---

## R15 — SC-008 measured: retrieval's cost per run *(T045, measured 2026-08-28/29)*

**Result: SC-008 is MISSED at 2.12%, against a ≤2% threshold. The target was not adjusted.**

### The two arms

One application (`2c36feee`, Senior Backend Engineer), **one process**, one pricing window —
`guideline_source` `static` then `retrieval`, everything else identical.

| | static | retrieval |
|---|---|---|
| run | `e70ecd76` | `7c1d64d4` |
| status | succeeded | succeeded |
| guidelines in the snapshot | 12 (no content hashes) | 27 (content-hashed) |
| calls | 5 — the Reviewer revised | 3 — first pass clear |
| **total cost** | **$0.446391** | **$0.206268** |

### Why the total-cost ratio is not the answer

The retrieval arm came out **54% cheaper**. That is not evidence about retrieval. Run cost is
dominated by whether the Reviewer triggers a revision — an extra Sonnet call plus an extra Opus
call, about a third of a run — and slice 005's R5 already measured four runs of the same pipeline
at $0.295 to $0.548, an **85% spread**. A 2% threshold cannot be resolved through that, and a
single pair reporting −54% would have been a fabricated pass.

### What was measured instead

Retrieval **replaces** the static guidance block in the two prompts that consume guidance. The
**Plan** call is a perfect control — same posting, same analysis, same profile, same prompt,
differing only in that block — so its input-token delta *is* the guidance delta.

| call | static input | retrieval input | delta |
|---|---|---|---|
| `tailor_plan` | 7,428 | 9,799 | **+2,371** |
| `tailor_draft` | 8,149 | 10,505 | +2,356 |
| | | **total** | **+4,727** |

Draft corroborates Plan to within 0.6% while also carrying a differing plan, which is strong
evidence the guidance block is the whole difference.

`+4,727 × $2.00/MTok = **$0.009454**` → **2.12%** of the same-session baseline.

| denominator | % | |
|---|---|---|
| same-session static arm, $0.446391 | **2.12%** | MISSED |
| mean of the five measured static runs, $0.412356 | 2.29% | MISSED |
| cheapest measured static run, $0.295450 | 3.20% | MISSED |
| most expensive, $0.547891 | 1.73% | met |
| same-session baseline at post-2026-08-31 $3.00/MTok | 3.18% | MISSED |

It fails on the **most favourable** defensible denominator available.

### What causes the excess

The spec predicted +993 tokens (1,500 − 507). Measured: **+2,371**, 2.4× the prediction. Rendering
both blocks through the real prompt builder (`prompts.py::_guidelines`, free, no model call):

| | guidelines | block | rule text | **citations** |
|---|---|---|---|---|
| static | 12 | 492 tok | 358 | 134 |
| retrieval | 27 | **2,190 tok** | 1,523 | **667** |

**`token_count` — what the 1,500-token ceiling budgets — counts rule text only.** The rendered
prompt also carries `document_slug · locator · content_hash` per guideline, which is uncounted:
**667 tokens, 31% of the block**, and the reason a "1,500-token" ceiling renders at ~2,190. The
ceiling is doing what it says; what it says is narrower than what reaches the model.

*(The offline counter gives the block delta as +1,698 where the provider reports +2,371. The
provider's own accounting is authoritative and is what the verdict uses; the offline render is
used only for the **proportions**, which are in consistent units.)*

### Pricing

Read from **LiteLLM's table, the same source the gateway prices every call with** — Sonnet 5
**$2.00/$10.00 per MTok**, Opus 5 $5.00/$25.00, on 2026-08-28. No external pricing was
substituted and no price is written down in the harness. The spec's note that the introductory
Sonnet rate ends **2026-08-31** still stands; the sensitivity is in the table above.

### Sample size

**One paid pair, and the reason is the design rather than the budget.** The numerator is a
deterministic input-token delta on a perfectly controlled call — more pairs would add output-token
noise to it, not signal. The denominator has five measured static runs across two slices, and the
verdict is reported against all of them. Total spend: **$0.652659**.

### Not done

No prompt, model, ceiling or citation format was changed. Reducing the delta means changing what
the citation renders or what the ceiling counts, and both are decisions with retrieval-integrity
consequences (FR-012 rests on the citation being resolvable) that T045 has no mandate to take.
