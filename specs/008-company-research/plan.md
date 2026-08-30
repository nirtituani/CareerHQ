# Slice 008 — Company Research: technical plan

Design only. No code, no migrations, no task list. `research.md` carries the evidence; `spec.md`
carries the requirements. This document is *how*.

---

## 1. Product requirement vs implementation strategy

**The product requirement is two layers** (`spec.md` FR-020): a general company understanding scoped
to the company, and a role-specific perspective scoped to the application.

**How many model calls implement that is a separate question**, and the answer is not "one call per
layer times one planning call each". Slice 005 measured what an extra model call costs on this
system — output tokens are 57–86% of cost, elapsed time tracks output at ~92 tok/s, and adaptive
thinking silently adds 42–60% on top — so a call that does not earn its place is a first-class
design defect, not a rounding error. §2 justifies each one individually.

The layer split itself is **not** negotiable on cost grounds, but for a reason worth being precise
about: it is forced by **reuse**, not by quality. A single call producing both layers would take
role context, so its general half could not be cached per company, and every application to that
employer would re-pay for it. The split is what *saves* calls over a user's second and third
application to the same company.

---

## 2. How many model calls, and why

### The pipeline

```
application  ->  company + domain          (Layer 1 input)
                 job title, description,
                 extracted requirements    (Layer 2 input only)

  [1] general queries        DETERMINISTIC   template over company + domain
  [2] search + fetch         no model        N x MCP, through the SSRF guard
  [3] synthesise_company     MODEL           Layer 1  -- cached per company
  [4] role queries           MODEL (cheap)   role + requirements -> targeted queries
  [5] search + fetch         no model        M x MCP, through the SSRF guard
  [6] synthesise_role        MODEL           Layer 2  -- references the Layer 1 snapshot
```

**Three model calls on a cold run. Two when a fresh Layer 1 already exists** for that company, since
steps 1–3 are skipped entirely.

### Each call, justified

**[1] General query planning — deterministic, no model.** The queries depend only on company
identity, and `Company.domain` already disambiguates it. `"{company}" about`, `products`,
`customers`, `site:{domain}`, and a market/industry query are a fixed template. A model would be
choosing from a space that does not vary. **Eliminated.**

**[3] `research_synthesise_company` — necessary.** Reading N retrieved pages and producing a
sectioned, cited, tier-typed brief is irreducibly a model task. Nothing deterministic produces it.

**[4] `research_plan_role_queries` — defensible, and the one to challenge first.** Unlike [1], this
does not template well: turning "Senior Backend Engineer" plus a requirements list into the search
terms that actually find an engineering blog, an architecture talk, or a scale write-up is world
knowledge. It is also **cheap** — a query list is short output, and output is what costs. Kept for
MVP, but see the challenge below.

**[6] `research_synthesise_role` — necessary.** Same argument as [3], against the role-targeted
sources plus the Layer 1 snapshot.

### What cannot be combined, and why

- **[3] and [6] cannot merge.** Not a capability limit — a *reuse* limit. Merging feeds role context
  into the call that produces Layer 1, violating FR-021 and forfeiting company-level caching
  permanently. The saving would be one call today and a repeated cost on every subsequent
  application to that employer.
- **Nothing can merge across a search boundary.** [1] and [4] must produce queries *before* a search;
  [3] and [6] must read results *after* one. Query planning and synthesis are separated by an I/O
  step, so no prompt can span them.

### The challenge worth measuring

Make [4] deterministic too — template the structural queries (engineering blog, GitHub org,
architecture, careers/tech pages) and derive the rest from the **already-extracted** requirement
text on the application, which slices 003 and 004 persist. That yields **2 model calls cold, 1
warm**.

Recommendation: **keep [4] as a model call for MVP, and measure it.** The risk of templating is not
cost, it is that weak queries starve Layer 2 of sources — and Layer 2 is where the differentiated
value is. Cheap to test: run both query strategies over the same companies and compare how many
retrieved sources survive into the final brief. Recorded as OQ-I.

### A latency option, not an MVP requirement

[4] depends on the **job**, not on Layer 1's output. It can therefore run concurrently with the
general search [2], and only [6] must wait for [3]. This overlaps the two search passes and removes
roughly one search round-trip from wall-clock. Worth doing once correctness is settled; not worth
the concurrency on day one.

### Orchestration

**Decided (OQ-D): plain `async` application code.** A linear sequence with no conditional edge and
no loop. OQ-B deferred the semantic verifier, so the retry edge that would have justified LangGraph
does not exist — and using it anyway would import the state-reducer class of bug that cost slice 005
two separate defects, to express a sequence a function already expresses.

Reversible in both directions: *adding* LangGraph later, if a verifier lands, requires no schema
change and no use-case change.

---

## 3. The seam, and the new port

### Completions — unchanged

All three model calls go through the existing
`complete(task, schema, prompt) -> Completion[T]`. No change to the seam, and no fourth call
signature. This keeps the count of call sites honest and keeps `UsageRecorder` working as-is.

New task names, each of which **must** get an `llm_model_<task>` entry in `config.py` or it silently
runs Opus at ~2.5× (a test AST-walks for task names and enforces this):

| Task | Layer | Suggested model | Reasoning |
|---|---|---|---|
| `research_synthesise_company` | 1 | Sonnet | Output-token-heavy, but the task is summarise-and-cite rather than judge. |
| `research_plan_role_queries` | 2 | Sonnet | Short output. The cheapest call in the pipeline, and the first to challenge (§2, OQ-I). |
| `research_synthesise_role` | 2 | Sonnet | Carries the interpretation and inference tiers, so it is the judgement-heavy node — a candidate for Opus if measurement shows Sonnet under-reads evidence. |
| `research_verify` | both | Opus | Only if OQ-B lands it. Slice 005 put the stronger model on the node that guards correctness. |

There is **no** `research_plan_queries` for Layer 1: that step is deterministic (§2).

### Search — a new application port

```
application/ports.py      WebSearch protocol      search(query, limit) -> list[SearchHit]
                          SearchHit               url, title, snippet     <- no page content
                          FetchedSource           url, title, retrieved_at, text
infrastructure/mcp/       BraveWebSearch          implements WebSearch over the Brave MCP server
tests/support/            ScriptedSearch          implements WebSearch from a fixture
```

**The capability is MCP web search; the implementation is Brave.** That distinction is deliberate
and load-bearing:

- `spec.md` FR-003 requires an **MCP web-search boundary** and names no vendor.
- **Brave** (`@brave/brave-search-mcp-server`) is the chosen implementation (OQ-A, closed), because
  it returns URLs and snippets only and *cannot* return page content — so the trust boundary below
  is its default behaviour rather than a rule we must keep.
- **Tavily** is the documented fallback.

Replacing Brave therefore means writing a second `WebSearch` adapter and changing one line of
configuration. It does not touch `spec.md`, the schemas, or any use case. Evidence: `research.md`
R10.

`SearchHit` carries **no page text, by design**. The port's type signature is where that boundary is
enforced: a future adapter that returned content would have to change the protocol to do it, which
is a visible change rather than a silent one.

`application/` imports the **protocol only**. The MCP client lives entirely under
`infrastructure/`, exactly as the provider SDK does, so
`test_the_application_layer_imports_no_provider_sdk` holds without modification. That test's
forbidden-package list should be **widened to include the MCP client package**, for the same reason
slice 005 widened it from one package to six.

`ScriptedSearch` is what keeps the suite runnable with no provider and no network — the promise
slice 003 already makes and this slice must not break.

### The trust boundary, stated once

```
model decides WHAT to search
  -> Brave MCP performs the search        (no page content crosses this line)
  -> URLs + snippets return to CareerHQ
  -> CareerHQ fetches, through the existing SSRF guard
  -> CareerHQ owns the documents, the excerpts and the citations
  -> model synthesises from what CareerHQ retrieved
```

Two properties follow, and both are load-bearing:

1. **Every byte a model sees passed our guard.** Not by convention — by the fact that Brave has no
   content to give us.
2. **We hold the source documents**, which is what makes FR-032's verbatim excerpt check possible
   at zero cost, and which narrows OQ-B from "do we need verification" to "do we need *semantic*
   verification on top of a free structural one".

### Why there is no ReAct loop here

`docs/reference/01_course_requirements.md:31` asks that "the agent should use Tools/MCPs" and does
**not** require the model to initiate the tool call; line 54 attaches its ReAct-over-RAG suggestion
to the CV-guidelines path, which is slice 006's. CareerHQ is the MCP **client**: it decides when to
search, the model decides what to search for. That is a genuine MCP integration.

Adding an autonomous tool-calling loop *solely* to make web search look more agentic would buy no
requirement coverage — slice 005's self-critique workflow already demonstrates an agentic workflow —
and would trade a bounded, 3-call pipeline for an unbounded one, against the economics measured in
§6. Efficiency first, deliberately. It should follow `tests/support/scripted_seam.py`: a sequence per query, and a
loud `ScriptExhausted`-style failure when the workflow asks for more than the script provides.

---

## 4. Fetching, and the security boundary

Search returns URLs. Something must fetch them, and **that something is the existing guard**:
`backend/src/careerhq/infrastructure/jobs/fetch.py` (FR-015). Reuse, do not reimplement, and do not
copy — a second SSRF implementation is a second thing to get wrong.

Likely required change to that module: it is currently shaped around one user-supplied URL. Serving
N machine-chosen URLs per run wants a batch entry point and a per-run budget. That is a **change to
a shared file outside this slice's directory**, so it is called out here rather than made.

Retrieved text is framed as untrusted data in every prompt (FR-016). Concretely: fenced, labelled
with its source URL, and preceded by a statement that instructions inside it carry no authority.
The slice 003 template-page finding (FR-017) means a retrieved page also needs a cheap
is-this-actually-content check before it is worth a model's attention.

---

## 5. Data model

Two new tables. No migration is written here.

**Two tables, one per layer.** Not one table with both layers, and not a `scope` discriminator: a
single row carrying both would duplicate Layer 1 for every application and forfeit exactly the reuse
that motivates the split (§1).

**`company_research_snapshots`** — Layer 1, company-scoped, role-independent (FR-021)

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `user_id` | FK users, cascade — ownership from the session (FR-018) |
| `company_id` | FK companies, cascade. **The reuse axis** (FR-013, US4) |
| `retrieved_at` | timestamptz, not null. Displayed prominently (US3) |
| `sections` | jsonb — **fixed** sections: what the company does, products/services, market and customers, secondary practical facts. Each present, each possibly empty-with-reason |
| `model_config_used`, `prompt_version` | jsonb / varchar — so slice 007 can compare like with like |
| `input_tokens`, `output_tokens`, `cost` | Principle V audit, same transaction as the work (FR-012) |
| `status`, `failure_reason` | a failed run is a recorded run, not an absent one |

**No `application_id`.** Its absence is the enforcement of FR-021 — a Layer 1 row that could name an
application would eventually be shaped by one.

**`role_research_snapshots`** — Layer 2, application-scoped (FR-022)

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `user_id` | FK users, cascade |
| `application_id` | FK applications, cascade. **Not nullable** — Layer 2 without a job is meaningless |
| `company_research_snapshot_id` | FK, not null. The lineage FR-023 requires: which Layer 1 this rests on, and therefore how old it was |
| `retrieved_at` | timestamptz, not null |
| `findings` | jsonb — a **variable** list of `{heading, claims[]}`, shaped by the role (FR-022). Not a fixed section set |
| `model_config_used`, `prompt_version`, usage columns, `status`, `failure_reason` | as above |

**Claims, in both tables**, use the per-claim structure decided in OQ-C:

```
claim = { text, tier, source_ids[], excerpt }
```

carrying the tier from FR-028 — `fact` | `interpretation` | `inference` — with the differing
evidence obligations of FR-029 enforced in the schema. Prose with inline citation markers was
rejected: it cannot carry a per-claim tier or a per-claim excerpt, and FR-032's verbatim check needs
the latter. A `fact` references one or
more `research_sources` rows; an `interpretation` references the facts it rests on; an `inference`
may reference neither but is never renderable as a fact.

**`research_sources`**

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `snapshot_id` | FK, cascade |
| `url`, `title` | as retrieved |
| `retrieved_at` | timestamptz — per source, because a run spans time |
| `excerpt` | text — the supporting passage (FR-008) |
| `fetch_status` | retrieved / failed / refused — FR-009 and FR-017 |

**Pointer.** `companies.current_research_snapshot_id`, nullable, written **only on success**
(FR-014). Slice 005's T093 lesson applies directly and should be designed in from the start: the
read path must prefer an in-flight run *while it is plausibly in flight*, or a re-run reports the
previous result and the interface stops polling.

**Immutability.** No `updated_at`, and no update path in the repository layer. The absence is the
enforcement — and per slice 003's `rejected`-column lesson, an invariant enforced by an absence
needs a test asserting the absence, watched failing.

**Alembic.** The head is `0014_displaced_position`. Slice 006 is being designed in parallel and
will also want the next revision — whoever writes second rebases rather than branching the history.

---

## 6. Cost and latency

From figures measured on this system (`research.md` R7): elapsed ≈ output_tokens ÷ ~92 tok/s,
output is 57–86% of cost, and **adaptive thinking is on by default, adding 42–60% of output tokens
invisibly**.

Consequences designed in rather than discovered:

- `[synthesise]` is the expensive node — it is the one with long output. Everything else is short.
- **Bound the fan-out.** Sources per run is a named constant (FR-004). Doubling it roughly doubles
  the input to synthesis and, through longer output, more than doubles the latency.
- **Never echo retrieved text** (FR-005). Slice 003 measured 52 seconds and a proxy timeout for
  exactly that mistake.
- Estimate cost from a comparable node's billed `completion_tokens`, never from expected JSON size —
  the invisible thinking makes the latter low by roughly half.
- A run is long enough to need the background-task pattern and a committed status transition, per
  the slice 005 finding that an in-flight run is invisible until its transaction commits.

**Rough envelope**, extrapolated from slice 005's measured nodes and explicitly *not* measured for
this slice:

| Run | Model calls | Estimate |
|---|---|---|
| **Cold** — first application to an employer | 3 | ~$0.10–0.20 |
| **Warm** — a fresh Layer 1 exists | 2 | ~$0.05–0.12 |
| With a verification node (OQ-B) | +1–2 | roughly +50% |

Treat every figure as an estimate to be replaced by measurement.

**The reuse is the point, and it is what `docs/00:42` asks for** — "Company research is repeatedly
repeated." A user applying to three roles at one employer pays for Layer 1 once, not three times.
That saving is only available because Layer 1 never reads the job (FR-021); it is the direct
economic consequence of the product requirement, not an optimisation bolted on afterwards.

**Reuse and staleness are two windows, not one.** Decided in OQ-E:

```
RESEARCH_REUSE_VERSION = "v1-30d"
RESEARCH_REUSE_DAYS    = 30    # beyond this, re-run Layer 1 rather than reuse it
RESEARCH_STALE_VERSION = "v1-90d"
RESEARCH_STALE_DAYS    = 90    # beyond this, mark visibly — never hide
```

A warm run reuses Layer 1 only inside the **reuse** window; past 30 days the run goes cold and
re-pays for Layer 1. Display marking is governed separately by the **stale** window, so research
between 30 and 90 days old is still shown unmarked to the reader while no longer being reused. The
shorter reuse window is deliberate: the saving is only ~$0.05–0.08 per warm run, and briefing
someone with stale facts before an interview costs far more than that.

Both versioned rather than edited, per the slice 004 rule that changing a threshold in place
silently reinterprets every historical run. **Layer 2 inherits Layer 1's age** for display purposes:
its effective age is the older of the two (FR-033). Layer 2 is never reused, so the reuse window
does not apply to it.

---

## 7. Testing

Following the five rules in `CLAUDE.md`'s testing section, and the ones this slice is most likely to
trip over:

- **Assert the count of what you examined.** A citation test that walks zero claims passes forever.
  This has shipped four times in this project.
- **A test double is fed by someone who read the code; a model is not.** If a citation must be
  matched back to a source id, the scripted double must *read that id out of the prompt* rather than
  being handed it — otherwise the suite proves the plumbing and never that a model could supply it.
- **Drill the absence.** The no-update-path invariant and the never-shared-across-users invariant
  are both enforced by absences. Break each, watch the test name the violation, restore.
- **Scoped absence assertions.** "No cross-user leakage" must be asserted against a second user's
  session, not against an empty result set.
- Every prompt-shaped test runs on `ScriptedSearch` + `ScriptedSeam`. No network, no provider.

---

## 8. Sequence, if built

1. Data model — both tables, the tier-typed claim schema, immutability invariants, and their
   drills. No model, no network.
2. `WebSearch` port + `ScriptedSearch` double, and the deterministic Layer 1 query template. Still
   no network.
3. **Layer 1 end to end** against scripted doubles: `research_synthesise_company`, fixed sections,
   tier typing, citations, and **FR-032's deterministic verbatim excerpt check** — free, and it
   defeats citation laundering before any model-based verifier exists. Useful on its own; this is a
   shippable increment.
4. **Layer 2 end to end** against scripted doubles: role queries, `research_synthesise_role`,
   variable findings, lineage back to the Layer 1 snapshot.
5. Reuse and staleness: warm-run path that skips Layer 1 inside the reuse window, and
   display marking governed by the separate stale window.
6. MCP adapter under `infrastructure/`, and widening the architecture test's forbidden list.
7. Fetch-path integration with the existing SSRF guard, including its batch entry point.
8. Interface: the `Company research` tab that already exists at
   `frontend/src/components/applications/detail-tabs.tsx:56`.
9. One real run, measured, and the estimates in §6 replaced with figures.

Steps 1–3 need no MCP server, so the slice can start before the largest open question (OQ-A) is
settled — and step 3 delivers a genuinely useful Layer 1 before Layer 2 exists.
