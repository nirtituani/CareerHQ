# Slice 008 — Company Research: open questions

Each carries **what would settle it**, so none of these becomes a standing argument. Ordered by how
much they block.

---

## OQ-A — ~~Which web-search provider?~~ **REOPENED and re-closed 2026-08-30: Tavily**

> **⚠️ SUPERSEDED BELOW — the vendor is now Tavily, reached over its ordinary HTTPS API.**
>
> **This is a plan change, not a requirements change**, exactly as the original decision said it
> would be: `spec.md` names no vendor, so the vendor moves without a requirement moving. What the
> product needs is that the research agent calls a **real external search tool at runtime** rather
> than inventing sources, and one authenticated POST does that.
>
> **MCP was dropped with it, deliberately.** The Brave route needed a Node process, an MCP SDK and
> a second failure mode, for no behaviour the product gains — complexity bought to satisfy a
> reading of the requirement rather than the requirement. The rule this project already applies to
> agent design applies here too: do not add machinery to look more agentic.
>
> **The security reasoning below still governs, and Tavily makes it a live obligation rather than
> an inherited property.** Brave *cannot* return page bodies; Tavily *can*, via
> `include_raw_content`. The paragraph below already predicted this — "one careless change routes
> content around the guard silently" — so the adapter defends it twice: it sends
> `include_raw_content: False` explicitly rather than trusting a default, and `_hits_from_payload`
> reads only `title`/`url`/`content`, so a body that arrived anyway is dropped. Both are tested. If
> either is removed, CareerHQ starts summarising text it never fetched, the SSRF guard is bypassed,
> and FR-032 quietly degrades into comparing a model's quotation with a provider's summary — with
> every test still green.
>
> The original Brave analysis is kept below because it is *why* the trust boundary is shaped this
> way, and a future reader choosing a third provider needs it.

## ~~OQ-A — Which MCP web-search server?~~ **superseded: Brave** *(original analysis, retained)*

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

## OQ-J — Which synthesis model? **DECIDED 2026-08-31: Claude Sonnet 5 stays; Gemini 3.6 Flash is the validated low-cost alternative**

Benchmarked on **four frozen fixtures** — identical source bytes to every model, the real
`build_company_prompt`, the real `CompanyResearch` schema and the real `verify_excerpts` as judge.
Companies chosen to span the shapes that matter: **Anthropic** (large, well covered), **Doctolib**
(non-English-primary; its LinkedIn source carries 115 French-language markers), **Voyantis** (small
private), **Zipher** (thin, and *name-ambiguous* — the corpus contains three unrelated companies).

| Model | done | claims | citations | rejected | sections | billed |
|---|---|---|---|---|---|---|
| **Claude Sonnet 5** | 4/4 | **111** | 111 | **1 (0.9%)** | 20/20 | **$0.7272** |
| **Gemini 3.6 Flash + optimised prompt** | 4/4 | **84** | **119** | 2 (1.7%) | 20/20 | **$0** |
| Gemini 3.6 Flash, baseline prompt | 4/4 | 55 | 44 | 1 | 20/20 | $0 |
| Step 3.7 Flash | 4/4 | 68 | 113 | **20 (18%)** | 19/20 | $0.1119 |
| GPT-OSS-20B | 3/4 | 27 | 72 | **30 (42%)** | 12/15 | $0.0049 |
| Nemotron 3 Super `:free` | **0/4** | — | — | — | — | $0 |
| Groq (any model) | **0/4** | — | — | — | — | $0 |

**The rejection column is the one that decides this**, and it is why schema validity is not a
sufficient test. Every model above shows 0 uncited facts and 0 unknown source ids — but only
*because* `verify_excerpts` stripped the bad citations first. GPT-OSS-20B fabricated **more
citations than it got right** on the largest fixture; without FR-032 it would have produced a
confident, well-formed brief in which nearly half the quotations were invented, and nothing would
have flagged it. This is the clearest evidence the slice has that the verbatim check earns its keep.

**Two candidates failed structurally rather than on quality.** Nemotron `:free` on OpenRouter
returned nothing in over 30 minutes of queueing. **Groq is capped at 8,000 tokens/minute on every
standard model** (`x-ratelimit-limit-tokens: 8000`), while our prompts are 9,000-30,000 tokens — the
*smallest* fixture exceeds a whole minute's allowance, and a single request into a verified-empty
window is still refused as `Request too large`. Groq is built for small, frequent requests; this
workload is one large one. Only `groq/compound` has a higher cap, and it is Groq's *agentic* system
with its own web search, which would bypass Tavily → SourceFetcher → the SSRF guard entirely and
dismantle the trust boundary the slice is built on.

**Decision: `anthropic/claude-sonnet-5` remains the production default.** A cold research run costs
~$0.17 **once per employer**, reused across every application to it inside the 30-day window
(OQ-E). The saving from switching is cents on an action a user triggers rarely, and it is paid for
in the density of exactly the briefs that are hardest to replace — small private companies, where
the brief *is* the research.

**Gemini 3.6 Flash with the optimised prompt is the validated alternative**, for a deployment
without an Anthropic budget: 76% of Claude's claims, **107% of its citations**, more distinct
sources cited than Claude (20 vs 18), all five sections, 1.7% rejection, half the latency, $0.
Selected by configuration alone — `llm_model_research_synthesise_company` — which is how every model
in that table ran, with no code change and nothing provider-specific in `application/`.

**Two caveats that must travel with the recommendation.** Google's free tier may use submitted
content to improve their products: acceptable for public company pages, **not** for anything
profile-shaped. And **LiteLLM prices Gemini from its paid-rate table regardless of actual billing**,
so `Usage.cost` — the Principle V audit record — would systematically overstate spend, and the same
figure feeds slice 007's ceiling. Unresolved, deliberately: see the follow-up below.

### The optimised prompt — **candidate, not yet adopted**

Density was a *prompting* problem, not a capability ceiling. The shipped prompt says "Summarise, and
quote only the passage that carries a claim" and never says **how much** to extract; Claude reads
that as "be thorough", Gemini as "be brief", and nothing adjudicates. Adding ~2,300 characters of
guidance moved Gemini from 50% to 76% of Claude's claims and **tripled** its citations, with **zero**
near-duplicate claims — the gain is evidence per claim, not padding.

Two blocks, inserted before *"How to make claims"*:

* **`## How much to extract`** — extract every materially useful fact rather than summarising;
  enumerate the particulars most often omitted (people, named customers, distinct products, numbers
  and dates, locations, technology); prefer several specific claims to one general one; **cite every
  source supporting a fact, not just one**; **state contradictions explicitly rather than silently
  choosing**; fill all five sections with real content.
* **`## The one thing that overrides all of the above`** — never invent to raise the count; a
  fabricated quotation is discarded and is worse than a missing claim; never promote an `inference`
  to a `fact`; if the sources are thin, a short honest profile is the correct output.

That second block is why integrity held while density rose, and it must not be dropped if the first
is adopted.

**It produced the single most valuable output of the whole benchmark**, which no model managed
otherwise — *including Claude at 2.4x the price*. On the Zipher fixture it read the two irrelevant
sources, recognised them as different companies, and told the reader:

> "The Kansas metal manufacturer Zephyr Products, Inc. and the UK printer manufacturer Zipher Ltd
> are separate companies that should not be confused with the AI data infrastructure startup
> Zipher.ai."

Baseline Gemini and Claude both silently ignored those sources. The behaviour came from the
"say so when sources disagree" instruction, so that clause buys contradiction-awareness rather than
verbosity.

**Why it is a candidate and not yet the prompt.** It is a *prompt* improvement rather than a Gemini
workaround, so it should apply to every model — a Gemini-only prompt would put provider branching
into the synthesis path, which is what the seam exists to prevent. But it has **only been measured
on Gemini**. Adopting it changes the production default's behaviour on an untested assumption, and
one Claude pass to check costs ~$0.70 and was explicitly not authorised. Until that is run,
"it would likely help Claude too" is a hypothesis.

**Caveat on all figures above**: n=1 per cell, and Gemini varied 16 -> 21 claims on an identical
fixture between runs, so treat +-20% as noise. The +53% density gain is well outside that; the
per-company numbers are not precise.

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

#### Binding constraints on the adapter — from the `b4e60b6` security review

**The entire SSRF guarantee of slice 008 rests on this adapter, which does not exist yet.** Nothing
in the committed pipeline makes an outbound request: `SourceFetcher` is a Protocol, and
`research_company` / `research_role` call `fetcher.fetch(url=...)` without validating anything
themselves. That is why the review found no SSRF issue — and why every one of these is load-bearing
the moment the adapter lands. They are constraints, not suggestions.

1. **Validate the final URL after every redirect, and persist that URL.** `FetchedSource.url` is
   written to `research_sources.url` and displayed as the citation. If the adapter returns the
   *requested* URL rather than the one actually retrieved, a redirect makes the stored citation name
   a page nobody read — and FR-032's excerpt check would then be verifying text against a document
   the citation does not point at.
2. **Re-run the guard on every hop**, for each of the up-to-`MAX_SOURCES` URLs per run. The existing
   `fetch_posting` already does this for its single user-supplied URL; a batch entry point must not
   quietly weaken it to a first-hop check because it now has six URLs to get through.
3. **Do not widen the DNS-rebinding window — and close it if practical.**

   ⚠️ **Corrected 2026-08-30.** An earlier version of this note claimed *"the current single-URL
   path has no such gap"*. **That was wrong, and reading `fetch.py` disproves it.**
   `assert_fetchable` resolves the hostname with `getaddrinfo` and then returns; `client.get()`
   then resolves the **same name again, independently**, when it opens the connection. Nothing
   carries the checked addresses forward. That is a textbook TOCTOU: a name whose A record is
   public at check time can answer `169.254.169.254` or `pgvector.railway.internal` microseconds
   later at connect time, and the guard will have approved it.

   The window is **narrow** — it is one round trip wide, and exploiting it needs an attacker-run
   DNS server with a very low TTL and the ability to win the race — but it is real, it is on the
   shipped single-URL path today, and slice 008 makes it *N* times more likely to be met by
   fetching up to `MAX_SOURCES` machine-chosen URLs per run instead of one URL a human typed.

   The honest constraint is therefore: a batch entry point must not make this worse, and should
   close it. **Closing it means connecting to the address that was validated rather than to the
   name** — resolve once, check every address, then pin the connection to a checked address while
   still sending the original `Host` header and SNI so TLS and virtual hosting keep working.
   Documenting the window is not a fix; it was documented as absent, which was worse than not
   documenting it at all.

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

---

## Security review — `b4e60b6`, **COMPLETE, no vulnerabilities found**

Run 2026-08-30 against the Steps 1–5 commit, covering the four areas the pipeline actually puts at
risk: attacker-controlled web content reaching model prompts, citation and evidence handling, the
SSRF boundary, and persistence.

**Result: no security vulnerabilities.** Three candidates were raised and all three were rejected on
independent review, each at confidence 2/10 against a ≥8 bar:

| Candidate | Why rejected |
|---|---|
| Excerpt check satisfiable by a one-word quote | No boundary crossed; the path is prompt injection end to end, and an attacker who controls the page can place the fabricated sentence *on* it and have it quoted verbatim — so a length floor raises cost, it does not close a hole |
| `interpretation` / `inference` skip excerpt verification | This is the documented contract (FR-029), stated in `_check_claim`'s own docstring. `CitationReport.examined` already exists to stop a checker that walked nothing reading as clean |
| Unescaped structural delimiters in prompts | Attribution laundering is already blocked because source ids are **ours**, not the page's; synthesis has no tool use and no outbound channel |

**What the review confirmed positively**, and what must therefore stay true: `SearchHit` carries no
page content; source ids are assigned by us and never read from a page; every prompt frames fetched
text as data with no authority; synthesis makes one completion call with no tool use; all new
queries use bound parameters, with `sa.text()` in `0019` only for literal index predicates; and both
snapshot tables are `user_id`-scoped with every read reached through an already-owned `Company` or
`Application`, so no cross-user path exists.

**One forward-looking note beyond S1**: reads are scoped by traversing an owned object rather than
filtering on `user_id`. That is safe now and matches the codebase, but once routes accept ids a
defence-in-depth `user_id` filter is worth adding.

## Deferred correctness follow-ups — **not security**, and deliberately not acted on

Both surfaced during the `b4e60b6` review and were judged robustness rather than vulnerability. They
are recorded because a rejected security finding is easy to lose, and neither is wrong to fix.

- **Minimum excerpt length.** `Evidence.excerpt` carries only `min_length=1`, and the verbatim check
  is an unanchored substring test after whitespace collapse — so `"the"` matches almost any page.
  The module docstring claims the check "defeats citation laundering", which overstates what a
  one-word excerpt is defeated by. A length-and-word-count floor belongs in **both**
  `Field(description=...)` and the validator, per the slice 005 rule that a validator-only rule is
  never shown to the model. **Cannot be fixed by a threshold alone** — an attacker controlling the
  page can supply a long quotable sentence — so this is a cost increase, not a fix, and should be
  described that way when it is done.
- **`rests_on` referential closure after rejection.** `_check_section` removes rejected claims but
  leaves surviving claims' `rests_on` untouched, so an `interpretation` can cite a claim id that is
  no longer in the persisted brief. The reader cannot tell that dangling reference from a sound one.
  Resolving `rests_on` against the surviving ids — and deciding whether an orphaned interpretation is
  dropped or relabelled with a recorded reason — is the fix.

Neither is scheduled. Neither blocks Step 6.
