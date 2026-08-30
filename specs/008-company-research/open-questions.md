# Slice 008 — Company Research: open questions

Each carries **what would settle it**, so none of these becomes a standing argument. Ordered by how
much they block.

---

## OQ-A — ~~Which MCP web-search server?~~ **CLOSED: Brave** *(preferred implementation)*

**Decided 2026-08-27. Evidence and the four-way comparison are in `research.md` R10.**

### Three levels, deliberately kept apart

| Level | Statement | Lives in |
|---|---|---|
| **Requirement** | Research goes over an **MCP web-search boundary**. A hand-rolled search client does not satisfy it. | `spec.md` FR-003 — **vendor-neutral** |
| **Implementation choice** | **Brave** (`@brave/brave-search-mcp-server`), first-party. | `plan.md`, `research.md`, here |
| **Fallback** | **Tavily**, if Brave's terms or result quality disappoint. | `plan.md`, `research.md`, here |

**`spec.md` names no vendor, and must continue not to.** Swapping Brave for Tavily is then a plan
change, not a change to product requirements — the capability is the requirement; the server is an
implementation detail with a documented replacement.

**The deciding reason is security, not cost.** Brave returns **URLs and snippets only** — it cannot
return page content. So the intended trust boundary is Brave's *default behaviour* rather than a
rule we must keep remembering:

```
model decides WHAT to search
  -> Brave MCP performs the search
  -> returns URLs + snippets
  -> CareerHQ fetches, through the existing SSRF guard
  -> CareerHQ owns the retrieved documents and the citations
  -> model synthesises
```

Every byte a model sees provably passed our guard. Tavily reaches the same place only while
`tavily-extract` is never exposed and `include_raw_content` stays false — one careless change routes
content around the guard **silently**. Exa returns content by default, which fights the design
outright.

**Efficiency reasons, secondary but real.** One environment variable, matching the existing
`ANTHROPIC_API_KEY` pattern; no fifth container added to a Compose stack that already carries a
documented sharp edge around shared volumes; a 2,000 queries/month free tier worth roughly 200–400
research runs; and one canonical first-party implementation rather than a choice among community
forks.

**The MCP integration stays minimal, deliberately.** CareerHQ is the MCP **client** and decides when
to search; the model decides what to search for. `docs/reference/01_course_requirements.md:31` asks
only that "the agent should use Tools/MCPs" and does not require the LLM to initiate the call —
and line 54 attaches its ReAct suggestion to the **CV-guidelines** path, which is slice 006's
territory, not this slice's. **No additional ReAct or tool-calling loop will be introduced solely to
make web search look more agentic**: it would add unbounded model calls against the economics
measured in R7 and buy no requirement coverage the system does not already have from slice 005's
self-critique workflow.

**Carried forward as an implementation to-do, not an open design question**: free-tier figures and
maturity came from aggregator sources rather than vendor pricing pages, and no server has been
tested against this codebase. Confirm Brave's current limits and terms, and make one probe run,
when the adapter is built (`plan.md` §8 step 6). If either disappoints, the fallback is already
chosen and the spec does not move.

---

## OQ-B — Semantic verification: **DEFERRED for MVP**, revisit on evidence

**Narrowed 2026-08-27 by the OQ-A decision.** The question is no longer "is a verification node
needed" but "is a *model-based* one needed on top of a free structural check".

Because Brave returns URLs only and **CareerHQ performs the fetching**, the application holds the
full text of every retrieved page. Citation checking therefore splits in two:

| Layer | Question | Cost |
|---|---|---|
| **Structural — deterministic** | Does the quoted excerpt appear **verbatim** in the document we retrieved? | **Free.** String containment. No model. |
| **Semantic — model** | Does that excerpt actually *support* the claim made from it? | A model call |

**The free layer catches the dangerous failure.** A fabricated quotation — the "citation
laundering" named in R4, where an invented claim is paired with a real URL — cannot survive a
verbatim containment test. That is the failure mode that most looks correct and is therefore most
harmful, and it now costs nothing to detect. Realised as `spec.md` FR-032.

**What remains genuinely open** is only the semantic layer: an excerpt can be real, correctly
quoted, and still not support the claim built on it. That needs judgement, and judgement costs a
model call — slice 005's Reviewer was 49% of run cost.

**Decided 2026-08-27: semantic verification is deferred for MVP.** The deterministic verbatim check
(FR-032) is the **first and only** verification layer the MVP ships. Measure how often claims drift
from correctly-quoted sources, and add a semantic node only if the measured rate justifies it —
which is the same evidence-before-mechanism discipline slice 005 used for its own thresholds.

This was not deferrable before OQ-A. It became so because CareerHQ performs its own fetching and
therefore holds the documents to check against.

**Note the layer asymmetry.** Layer 1 is expected to be mostly `fact`, so the structural check
covers most of it. Layer 2 carries proportionally more `interpretation` and `inference` (FR-031),
which the structural check cannot touch — so if a semantic verifier is ever built, **Layer 2 is
where it earns its cost**.

**Settled by**: hand-checking ~10 real Layer 1 and Layer 2 outputs after the deterministic check is
in place, counting claims that are correctly quoted but unsupported. Needs OQ-A confirmed first.

---

## OQ-C — ~~How is a claim bound to its source?~~ **CLOSED: per-claim structure (option 1)**

**Decided 2026-08-27.** Every claim is a row-like object carrying its own tier, its own source
references, and its own excerpt. Prose-with-inline-markers (option 2) and section-level citation
(option 3) are rejected.

```
claim = { text, tier, source_ids[], excerpt }
   Layer 1:  sections[]  -> fixed heading  + claims[]
   Layer 2:  findings[]  -> role-derived heading + claims[]
```

**Three requirements added after this question was written each independently force option 1:**

| Requirement | Why prose-with-markers fails |
|---|---|
| **FR-028** — each claim carries a tier (`fact` / `interpretation` / `inference`) | A marker cannot carry a tier. Tiers would have to be inferred from prose, which is exactly the ambiguity the tiers exist to remove. |
| **FR-029** — tiers have different evidence obligations | Unenforceable without a per-claim object to attach the obligation to. |
| **FR-032** — every excerpt verified verbatim | Needs a per-claim excerpt. A marker points at a source, not at the passage within it. |

**And slice 005 measured the cost of getting this wrong.** `de_emphasise` holds free text with no
ids, which makes "did the draft do what the plan said" **not computable** — and fixing it now means
changing a schema and therefore a prompt. Option 2 would reproduce that failure one slice later,
against the criterion slice 007 grades this capability on.

**The cost objection is answered.** Option 1 spends more output tokens on structure. But the claims
themselves are the same words either way; only the wrapping differs, and structure is what makes the
output checkable. Given that citation accuracy *is* the evaluation criterion, unstructured output
would be cheaper and ungradeable.

**Layer asymmetry, resolved.** Both layers use the same claim shape. They differ only in whether the
**headings** are fixed (Layer 1) or role-derived (Layer 2, FR-022). Slice 007 can therefore compute
citation accuracy identically across both.

> **Coordination note.** This decision covers the claim structure **inside a research snapshot**.
> If slice 006 introduces a shared representation for sources or citations over its guidelines
> corpus, the two should align at the persistence layer rather than diverge — see *Shared with
> slice 006* below. That alignment does not change the claim shape decided here.

---

## OQ-D — ~~LangGraph or plain async?~~ **CLOSED: plain async**

**Decided 2026-08-27, unblocked by OQ-B.** This question was explicitly waiting on whether a
verification node with a retry edge would exist. OQ-B deferred semantic verification for MVP, so it
does not.

What remains is a **linear pipeline with no conditional edge and no loop**:

```
queries (deterministic) -> search -> synthesise_company
                        -> queries (model) -> search -> synthesise_role
```

LangGraph exists to express branching, retries and state merging across a graph. None are present.
Using it here would add orchestration ceremony, a heavier import surface, and the state-reducer
class of bug that cost slice 005 two separate defects (`usage` keeping one record of seven; `items`
silently erasing the draft's drops) — for a sequence a function already expresses.

**Reversible by construction.** Slice 005's rule stands: deleting every LangGraph import must
require no schema change and no use-case change. Here the inverse holds — *adding* LangGraph later,
if a semantic verifier lands with a retry edge, requires no schema change and no use-case change
either. The orchestration choice is not load-bearing, which is precisely why the cheaper option
wins now.

---

## OQ-E — ~~Staleness threshold~~ **CLOSED: two constants, 30 and 90**

**Decided 2026-08-27.** One threshold was doing two unrelated jobs. Split:

```
RESEARCH_REUSE_VERSION = "v1-30d"
RESEARCH_REUSE_DAYS    = 30    # beyond this, re-run Layer 1 rather than reuse it
RESEARCH_STALE_VERSION = "v1-90d"
RESEARCH_STALE_DAYS    = 90    # beyond this, mark visibly — never hide
```

**Why they differ.** The two windows answer different questions:

| | Question | Consequence of being wrong |
|---|---|---|
| **Reuse — 30 days** | Do we spend money and time on a fresh Layer 1? | Briefing someone with stale facts before an interview, to save ~$0.06 |
| **Stale — 90 days** | Do we warn the reader that this is old? | Hiding research that is still useful, or crying wolf on research that is fine |

**Reuse takes the shorter window** because the saving is small — roughly $0.05–0.08 and one search
pass per warm run — while the downside is disproportionate. Cheap insurance. **Display takes the
longer window** because old research genuinely remains useful when honestly labelled, which is what
`docs/07:152` argues: research from three months ago "is still useful, but it must be visibly three
months old rather than silently wrong."

**What actually goes stale.** Not the snapshot uniformly. Funding, headcount, leadership, launches,
hiring focus and scale figures move in weeks or months; what the company fundamentally does, its
product category and its market move in years. A snapshot therefore inherits the shelf life of its
most perishable claim, and both numbers are proxies for that rather than measurements of it.
Citations do **not** go stale: excerpts are stored and verified verbatim at write time (FR-032), so
a source 404ing later invalidates nothing.

**Layer asymmetry.** For Layer 1 both constants apply — reuse expiry *and* display marking. For
Layer 2 only the display constant applies, because Layer 2 is application-scoped and never reused
across applications. **Layer 2 inherits Layer 1's age**: its effective age is the older of the two
(FR-033), so a recent role analysis resting on long-stale company research is not reported as fresh.

**Nothing refreshes automatically.** FR-001 keeps research on demand. Past the reuse window, the
next request simply goes cold.

**Both versioned, both honest placeholders.** The values are reasoned guesses, not measurements —
the same posture as slice 005's `CONFIDENCE_THRESHOLD`, "a placeholder with a version number, which
is the only kind of placeholder that does not rot silently." Changing either is a version bump, not
an edit, per the slice 004 rule that editing a threshold in place silently reinterprets every
historical run. Slice 007 can measure whether either corresponds to anything.

---

## OQ-F — ~~Is application-scoped research actually wanted?~~ **DECIDED**

**Resolved 2026-08-27 by product intent. Recorded, not open.**

The answer is yes, and the framing in the first draft was wrong. Company Research is **two
complementary layers**:

- **Layer 1** — general company understanding, **company-scoped**, deliberately role-independent,
  useful for a general or HR conversation or simply to understand the employer.
- **Layer 2** — role-specific perspective, **application-scoped**, driven by the job title,
  description and requirements, useful for technical or team-specific preparation.

**Why the first draft got this wrong.** It asked what application-scoped research would *contain*
that company-scoped research would not, and concluded the distinction was thin. The real distinction
is **reuse lifetime**: Layer 1 is computed once per employer and reused by every application to it,
which is precisely the problem `docs/00:42` names — "Company research is repeatedly repeated."
Layer 2 cannot be reused because it is about one job. That is a structural difference, not a
content one.

**This is what `docs/03:1897` already decided** — "Preserve Company-level research while allowing
Application-specific snapshots." The MVP decision was right; the first draft simply failed to see
what it was for.

Realised by `spec.md` FR-020 through FR-027 and the two tables in `plan.md` §5. What remains open is
not *whether* but *how well* — see OQ-C (schema), OQ-E (reuse and staleness windows) and OQ-I (query
strategy).

---

## OQ-I — ~~Role query planning: model or deterministic?~~ **CLOSED for MVP: model call**

**Decided 2026-08-27 on the evidence available, and revisitable by measurement.**

`research_plan_role_queries` **stays a model call** for MVP. The reason is the OQ-A decision, not
caution: **Brave's index is keyword-oriented and independent, not semantic.** Keyword engines reward
well-chosen terms, so mapping "Senior Backend Engineer" plus a requirements list onto the terms that
actually surface an engineering blog, an architecture talk or a scale write-up is exactly the work a
template cannot do. The call is also the cheapest in the pipeline — a query list is short output,
and output is what costs.

**The inverse is recorded because it is real:** under a neural index like Exa you could pass the job
description almost verbatim and skip query planning entirely. The search engine partly determines
whether this optimisation is even available, which is why this could not be settled before OQ-A.

**Why "closed for MVP" rather than closed outright.** The deterministic variant — templated
structural queries plus terms derived from the already-extracted requirement text — remains a live
option worth **2 model calls cold, 1 warm** instead of 3 and 2. It is not rejected; it is
unmeasured, and measuring it needs a working Brave adapter.

> **⚠️ Deferred at Step 5, and it now costs a migration.** `Layer2Result.queries` records what the
> planner chose, but **nothing persists it** — `role_research_snapshots` has no column for it, and
> `0019` does not add one. So the revisit trigger below cannot be run against historical rows: only
> against runs observed live, in memory. Making it measurable retrospectively means a new migration
> **after `0019` ships**, which is why the cost is recorded here rather than left to be rediscovered.
> Deliberate — the comparison also needs a working Brave adapter (Step 6 / S1), so storage for an
> experiment that cannot yet be performed would have been premature.

**Revisit trigger**: run both strategies over the same set of companies and compare how many
retrieved sources survive into the final brief, and whether the technical findings differ in
substance. If they do not, take the cheaper path. This is a **plan-level** choice — changing it
touches no requirement in `spec.md`.

---

## Shared with Slice 006 — **coordinate; do not unilaterally finalize**

Slice 006 (Document & Retrieval) is being designed in parallel. The areas below are ones where both
slices plausibly need the same infrastructure, and where **two independent implementations would be
the worst outcome**. For each: what 008 needs, the boundary 008 would prefer, and what is being left
open on purpose.

**None of these block 008.** `plan.md` §8 steps 1–3 deliver a working Layer 1 without touching any
of them.

### S1 — `fetch.py` ownership and interface *(was OQ-H)*

- **008 needs**: fetch N machine-chosen URLs per run, with a per-run budget, through the **existing**
  SSRF guard in `backend/src/careerhq/infrastructure/jobs/fetch.py` (FR-015).
- **Preferred boundary**: a batch entry point alongside the current single-URL one, taking a URL list
  and a budget, returning per-URL success/failure. The guard itself unchanged.
- **Left open**: the signature, and whether the module moves out of `infrastructure/jobs/`, which is
  now a misleading home if two slices fetch through it.
- **Why not unilateral**: it is a shared file, and a second SSRF implementation is a second thing to
  get wrong.

### S2 — Shared web-fetching infrastructure

- **008 needs**: retrieval of **untrusted public web** pages.
- **Note the asymmetry**: 006 retrieves from a **curated internal** corpus. The trust boundary is the
  entire difference, and it argues for shared *transport* with separate *trust policy* rather than
  one undifferentiated fetch layer.
- **Left open**: whether one component serves both, or 006 bypasses fetching altogether.

### S3 — Shared retrieval interfaces

- **008 needs**: the `WebSearch` port (`plan.md` §3) — query in, URLs and snippets out, **no page
  content**.
- **Preferred boundary**: keep 008's `WebSearch` distinct from any RAG/vector retrieval port 006
  defines. They answer different questions: *find me public pages* versus *find me relevant passages
  from our corpus*.
- **Left open**: whether a common `Retriever` abstraction is worth having above both. 008's view:
  probably not — the shapes differ enough that unifying them would produce a lowest-common-
  denominator interface.

### S4 — Shared source/citation infrastructure

- **008 needs**: per-claim source references with URL, title, retrieval timestamp, and a verbatim
  excerpt (FR-006, FR-008, FR-032).
- **Preferred boundary**: 008's **claim shape is decided** (OQ-C) and is internal to a research
  snapshot. If 006 needs citations over guidelines, the two should share the **source/excerpt**
  representation at the persistence layer rather than diverge.
- **Left open**: whether one `sources` table serves both, or each slice owns its own. 008 leans
  toward separate tables — a web URL and a guideline passage differ in almost every column — with a
  shared *concept* rather than a shared row.

### S5 — Shared document/content representations

- **008 needs**: `FetchedSource` — url, title, retrieved_at, text.
- **Left open**: whether 006's document representation and this are the same type. They may
  superficially match while differing in what is guaranteed: 008's text is untrusted and may contain
  prompt injection (FR-016, R6); 006's is curated.
- **Why not unilateral**: a shared type that silently loses the untrusted marking would be a
  security regression, not just a modelling one.

### S6 — Database and migration boundaries

- **008 needs**: two new tables and a `companies.current_research_snapshot_id` pointer
  (`plan.md` §5).
- **Known collision**: the Alembic head is `0014_displaced_position`. **Both slices will want the
  next revision.** Whoever writes second rebases rather than branching the history.
- **DECIDED 2026-08-27 — sequencing**: **slice 006 finishes and settles its schema first**, and
  slice 008 then chains its migration from the **final** 006 head. Explicitly rejected: creating a
  competing head from `0014`; chaining onto the current *uncommitted* `0015_knowledge_corpus`
  ("autogen probe") as though it were final; and committing 006's work merely to unblock 008.
- **Consequence**: `plan.md` §8 step 1 (data model and migration) is **blocked pending 006**. Steps
  2–3's non-persistence work is unaffected and proceeds.

---

## Documentation defects found, owned elsewhere

Not questions — findings, recorded so the documentation pass can act on them. Full list with line
numbers in `research.md` R2.

- Six documents call Company Research **slice 006**; slice 006 is Document & Retrieval.
- `docs/05_Implementation_Plan.md:365-369`, the **course-requirements coverage table**, is on an
  entirely superseded numbering and maps the **graded** evaluation requirement to slice 005. That
  one is worth fixing before the table is used to argue requirement coverage.
