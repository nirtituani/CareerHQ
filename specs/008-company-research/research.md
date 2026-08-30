# Slice 008 — Company Research: research notes

**Status**: design only. Nothing here is implemented.
**Method**: read against the repository at commit `298a45f`. Every claim about current behaviour
carries a `file:line`. Measured facts and interpretation are labelled separately throughout,
following the discipline `specs/005-resume-tailoring/research.md` R5 sets.

---

## R1 — The stated requirements are thin, and that is the first finding

**Measured.** The entire functional requirement is four lines
(`docs/01_Functional_Product_Requirements.md:436-467`):

- **US-005** — "As a job seeker, I want AI-generated company research before interviews."
- **FR-019** — "The system shall generate company research."
- **FR-020** — research *may* include Company Overview, Product Summary, Industry, Technology
  Stack, Interview Preparation Notes.
- Acceptance: "Research is generated on demand." / "Results are stored for future reference."

The workflow (`docs/01:684`) is four boxes: Application → Research Request → Generate Company Brief
→ Save Research.

`docs/07_Capabilities.md:135-150` is considerably more specific and is the better source:

| Field | Value |
|---|---|
| Input | Company name and domain |
| Output | An immutable research snapshot **with sources and retrieval timestamps** |
| Tools | **Web search MCP** |
| Memory | Snapshots accumulate per company; historical research is never overwritten |
| Evaluated by | **Citation accuracy — does each claim trace to a real source?** |

**Interpretation.** FR-020 says "may include", which is unimplementable as written — a schema needs
to know which fields are required. The five headings should become a fixed schema with every
section optional-but-present, so a section the research could not support comes back explicitly
empty rather than silently absent. This mirrors the slice 004 decision that made `unverified` an
explicit verdict rather than an omission: silence and absence must be distinguishable.

**Interpretation.** "Results are stored for future reference" plus "immutable snapshot" plus
"historical research is never overwritten" is a stronger constraint than FR-019 suggests, and it is
the constraint that shapes the data model. Treat `docs/07` as authoritative over `docs/01` here.

---

## R2 — The slice number is wrong in six documents

**Measured.** Company Research is **slice 008**, per the roadmap table
`docs/05_Implementation_Plan.md:91` and its definition at `docs/05:324` (§5.8). Slice 006 is
"Document & Retrieval".

These still call it slice 006:

| File | Line |
|---|---|
| `docs/08_Technical_Spec.md` | 199 — contradicts that document's own slice table at :720 |
| `docs/09_Design_Language.md` | 273, 291 |
| `specs/003-data-foundation/spec.md` | 196, 392 |
| `specs/003-data-foundation/data-model.md` | 193 |
| `docs/reference/02_original_design_notes.md` | 216 — frozen source material, should stay |

**Measured, and more serious.** The course-requirements coverage table at
`docs/05_Implementation_Plan.md:365-369` is on an entirely superseded numbering: it maps the
**graded** "Evaluation, benchmark, metrics" requirement to *slice 005*, which is Resume Tailoring.
Evaluation is slice 007. It also places the web-search MCP in 006 and PDF export in 004.

**This slice does not own those files.** Recorded here so the documentation pass that already owes
the `HANDOFF.md` run-count fix has the full list.

---

## R3 — Where the MCP client lives is the central architectural question

**Measured.** The boundary is enforced, not merely documented:
`backend/tests/unit/test_architecture.py::test_the_application_layer_imports_no_provider_sdk`
forbids any module under `application/` from importing a provider SDK, and slice 005 widened it
from one forbidden package to six because LangGraph pulls `langchain-core` transitively.

**Measured.** Every AI capability currently reaches a model through exactly one seam,
`complete(task, schema, prompt) -> Completion[T]`
(`specs/003-data-foundation/contracts/extraction-seam.md`). It has **no tools, no memory, and no
conversation**. The slice 005 tailoring graph loops by calling it repeatedly and holding state
itself (`CLAUDE.md`, Slice 005 section).

**Measured.** There is no MCP dependency in `backend/pyproject.toml` today.

**This is the tension.** A web-search MCP is a *tool the model calls*. The existing seam cannot
express that: it takes a prompt and returns a validated object, with no round-trip for tool
invocation. Three options:

| Option | Shape | Cost |
|---|---|---|
| **A. Tool-use inside the gateway** | `infrastructure/ai/` gains an MCP-aware call that runs the tool loop and returns a final validated object. `application/` still sees `complete()`. | The seam's "one call in, one object out" contract holds, but the gateway grows a loop it did not have. Provider tool-calling semantics leak into infrastructure only. |
| **B. Search as an application-level port** | Define a `WebSearch` port in `application/ports.py`; `infrastructure/mcp/` implements it over an MCP client. The agent orchestrates: search → read results → `complete()` to summarise. | Keeps the seam untouched and the boundary trivially satisfied. The model does not choose when to search — the application does. |
| **C. Provider-hosted web search** | Use the provider's own server-side web search tool rather than MCP. | Simplest, but **fails the course's Tools/MCP requirement**, which `docs/05:330` names as a reason for this slice's existence. |

**Recommendation: B, with the port named so A remains reachable.** Reasons:

1. It satisfies the architecture test by construction — `application/` imports a port, never a
   client.
2. It preserves the property that makes this codebase testable without a provider: a scripted
   double can stand in for search exactly as `ScriptedSeam` does for completions.
3. **Citation integrity is the evaluation criterion (R4), and B makes it enforceable.** If the
   application performs the search, it holds the retrieved documents and can verify that every
   quoted claim traces to one. Under A, the model both searches and summarises, and the only
   record of what it read is what it chooses to tell us — which is precisely the shape of the
   grounding problem slice 005 spent a Reviewer node solving.

**Uncertain.** Option B means the *model* does not decide which queries to run unless the
application asks it to plan queries first. A plan-then-search-then-summarise shape (three
`complete()` calls plus N searches) probably reads best and is closest to the slice 005 precedent,
but I have not costed it against a tool-loop. Flagged in `open-questions.md`.

---

## R4 — Citation accuracy is the evaluation criterion, so it must be structural

**Measured.** `docs/07:147` — "Evaluated by: Citation accuracy — does each claim trace to a real
source?" Slice 007 is the graded evaluation slice and will measure this.

**Measured precedent.** Slice 004 made evidence structural rather than advisory: every verdict
except `unverified` must quote the profile, *including* `gap`, and an earlier evidence-free
`missing` verdict was removed because it "left the model free to invent its absence"
(`CLAUDE.md`, Slice 004 section). Slice 005 made the same move with `ungrounded` findings, which
must carry `quoted_text` — enforced in the database by
`ck_reviewer_findings_ungrounded_quotes`.

**Interpretation.** Company Research should follow the same pattern rather than inventing one: a
claim carries a reference to a retrieved source, and the schema makes an uncited claim
unrepresentable. Two things that must not be conflated, and the slice 004 note about conflating
questions applies directly:

- **Does the claim cite a source?** — structurally enforceable, cheaply.
- **Does the source actually support the claim?** — not enforceable by schema. This is the same
  problem the slice 005 Reviewer exists for, and it is where a review node would earn its cost.

**Uncertain.** Whether slice 008 needs its own reviewer node, or whether URL-plus-retrieval-
timestamp plus a stored excerpt is sufficient for slice 007 to grade against, is unresolved.

---

## R5 — Snapshot immutability, and OQ-002 is already half-answered by slice 003

**Measured.** `docs/03_Domain_Model.md:1877` — "Research is generated on demand and saved as a
time-stamped snapshot with sources." `docs/03:1706` — "Company Research snapshots are immutable
after generation." `docs/07:149` — historical research is never overwritten.

**Measured — and this is the significant find.** A `Company` entity already exists from slice 003,
`backend/src/careerhq/domain/models/application.py:131-164`:

- It is **per user, not global**, with the rationale stated in the model's own docstring: "Two
  users naming the same employer own separate rows: these carry the user's own notes and contacts,
  so sharing them across accounts would leak one person's research into another's."
- It carries a `normalized_name` dedup key derived by `normalize_company_name`
  (`application.py:105`), enforced by `UniqueConstraint("user_id", "normalized_name")`.
- It already has a `domain` column (`application.py:157`) — which is exactly the second half of
  `docs/07`'s stated input, "Company name and domain".
- `Application.company_id` is a foreign key to it (`application.py:187`).

**OQ-002** (`docs/03:1897`) asks: "Should Company Research be shared between all Applications for
the same Company?" MVP decision: "Preserve Company-level research while allowing
Application-specific snapshots."

**Interpretation.** The existing model makes this straightforward and forecloses the risky reading:

- A snapshot hangs off `company_id`, so it is naturally shared across every Application for that
  employer — satisfying "Company-level research".
- Cross-**user** sharing is already ruled out by slice 003's per-user Company decision, on privacy
  grounds. That is not a new decision for this slice to make; it inherits it. Any design that
  caches research globally to save cost would contradict a documented privacy rationale.
- "Application-specific snapshots" is then an optional nullable `application_id` on the snapshot —
  present when research was requested in the context of one posting, null when it is general.

> **⚠️ SUPERSEDED by OQ-F.** The bullet immediately above is the interpretation as it stood before
> the two-layer decision, and it is **not** the built design. OQ-F replaced the single table with
> **two**: Layer 1 is company-scoped and carries no `application_id` at all, Layer 2 is
> application-scoped and carries a non-nullable one. The rest of this section — the company-level
> reuse axis, the inherited per-user privacy decision, and the `current_match_analysis_id` pattern
> with its T093 fix — is unaffected and still governs. Left in place because it records *why* a
> nullable column looked right at the time, which is the part a future reader needs in order not to
> re-propose it. See `spec.md` FR-013 and `plan.md` §5.

**Interpretation.** Immutability plus a retrieval timestamp is exactly the shape of
`ResumeVersion` in slice 005 and `MatchAnalysis` in slice 004: a new run writes a new row and
updates a pointer to the current one. The `current_match_analysis_id` pattern and the lesson
attached to it — the pointer is written **only on success**, which made an in-flight run invisible
until T093 fixed the read path (`CLAUDE.md`, slice 005 gotchas) — should be copied deliberately,
including the fix, not just the pattern.

---

## R6 — This slice ingests untrusted content, at a scale nothing else in the system does

**Measured.** `backend/src/careerhq/infrastructure/jobs/fetch.py` is currently "the only place a
user-supplied URL is requested", and it carries an SSRF guard that resolves the hostname, refuses
any non-global address, re-checks **every redirect hop**, allows only http/https, and never names
what it found — "otherwise it doubles as a way to map the network" (`CLAUDE.md`). It was verified
against the live endpoint.

**Interpretation.** Company Research multiplies this exposure. It will fetch many URLs per run,
chosen by a search engine rather than by the user, and feed their contents to a model. Three
distinct risks, which should not be collapsed:

1. **SSRF** — the existing guard is the precedent and should be reused rather than reimplemented.
   Anything performing HTTP on this slice's behalf routes through the same check.
2. **Prompt injection from retrieved pages.** This is new. A page can contain text addressed to
   the model. The existing system has never fed arbitrary third-party page content into a prompt
   with any authority attached to it. Retrieved content must be framed as data, and the slice 003
   finding that a client-rendered page can serve `{{position.name}}` template text a model will
   happily "extract" shows the failure mode is real even without an adversary.
3. **Citation laundering** — a fabricated claim paired with a real URL. Structurally the most
   dangerous, because it *looks* cited. R4's second question.

**Interpretation.** Risk 2 is a reason to prefer R3 option B: if the application holds the
retrieved text, it can bound how much of it reaches a prompt and label it consistently.

---

## R7 — Cost envelope, from figures measured on this system today

**Measured**, this session, against the real deployment:

- Elapsed time tracks output tokens at roughly **92 tokens/sec**, consistently across six real runs.
- Output is **57–86% of cost** (`CLAUDE.md`, slice 003 job-reading notes).
- **Adaptive thinking is on by default** on Claude Sonnet 5 and Opus 5 when no `thinking` parameter
  is sent, and the gateway sends none. Controlled single-variable A/B on identical prompts:
  Plan node 2,524 → 1,458 completion tokens with thinking disabled (**42.2%**); Draft node
  8,707 → 3,448 (**60.4%**). Latency moved with it: 93.2s → 45.9s on Draft.
- That spend is **invisible in the usage object**: LiteLLM reports `reasoning_tokens: 0` for
  Anthropic unless thinking text is returned, and with `display` defaulting to `"omitted"` it never
  is. Arm A billed 8,707 tokens against 2,648 tokens of visible JSON.

**Interpretation.** A research agent that fans out over N search results is an output-token
machine, and output tokens are both the cost and the latency. Design implications:

- **Never ask the model to reproduce retrieved text.** Slice 003 measured this exact mistake: asking
  a model to retype a job description took **52 seconds** and timed out the frontend proxy, against
  5.4s for metadata only. Summarise, cite, and quote short excerpts — never echo pages.
- Bound the number of sources per run explicitly, and make the bound a named constant, not a
  prompt instruction.
- `llm_model_<task>` **must** be set for every new task name in `config.py`, or `model_for_task`
  falls back to `llm_provider_model` — Opus — at roughly 2.5× cost for no gain. A test AST-walks
  for task names and enforces this. It has already caught CV extraction once.
- Because thinking is on by default and invisible, any cost estimate for this slice derived from
  visible output length will be low by roughly half. Estimate from billed `completion_tokens` of a
  comparable node, not from expected JSON size.

---

## R8 — What I did not investigate

Stated so nobody mistakes silence for a finding:

- **Which MCP server.** I have not evaluated specific web-search MCP implementations, their
  licensing, rate limits, or cost. This is the largest unknown and is the first thing to settle.
- **MCP client libraries for Python**, their maturity, or whether the Anthropic SDK's MCP support
  is a better fit than a standalone client.
- **The frontend surface.** `frontend/src/components/applications/detail-tabs.tsx:56` already
  renders a "Company research" tab, asserted by `applications.test.tsx:176`, so a seat exists — but
  I have not read what it currently displays.
- **Slice 006 (Document & Retrieval)**, which is being designed in parallel and may introduce a
  retrieval layer this slice should reuse rather than duplicate.
- **Anything requiring the running stack.** No Docker commands, no database queries, no test runs,
  and no provider calls were made in producing these notes.

---

## R9 — These artifacts were first written for a different product

**Measured.** R1–R8 above were derived from `docs/01_Functional_Product_Requirements.md:436-467`
and `docs/07_Capabilities.md:135-150`. Both describe a **single-layer, role-independent company
profile** keyed on company name and domain. `docs/07:141` states the input as exactly "Company name
and domain"; nothing in either document mentions the user's target role, the job description, or the
application as an input.

**Measured.** A cross-check of the first draft against the stated product intent found: the words
"role" and "job title" did not appear anywhere in the requirement sense; "confidence" and
"inference" appeared zero times across all four artifacts; `spec.md` contained the word "technical"
zero times; US1 was framed as "As a job seeker **with an interview scheduled**"; and OQ-F actively
questioned whether application-scoped research was wanted at all, suggesting it "may belong in
neither slice".

**The intended product is two complementary layers**, not one profile:

| | Layer 1 — General company understanding | Layer 2 — Role-specific perspective |
|---|---|---|
| Scope | **Company** | **Application** |
| Depends on the role? | **No, deliberately** | Yes |
| Serves | HR/general conversation; simply understanding the employer | Technical/team-specific preparation |
| Reuse | Once per employer, across every application to it | Per job |
| Content mix | Mostly facts | Heavier on interpretation and inference |

**Interpretation, and the reason this is not a bolt-on.** The two layers differ in **reuse
lifetime**, not merely in content. That is what makes the split structural rather than cosmetic: a
single combined output could not be cached per company without carrying role contamination, so the
separation is forced by the product requirement rather than chosen for tidiness.

**This is what `docs/03` already decided.** OQ-002 (`docs/03:1897`) resolved: "Preserve
Company-level research while allowing Application-specific snapshots." That is precisely the
two-layer model, recorded before this slice was designed. R5's finding that `Company` is per-user
with a `domain` column supplies the storage for layer 1; `Application` supplies the context for
layer 2. **OQ-F was wrong to doubt the application half** — it failed to see that the halves have
different reuse semantics, which is the whole point.

**Interpretation.** A third epistemic requirement emerged from the same cross-check and applies to
both layers: the output must distinguish **fact**, **interpretation**, and **inference** so a reader
can weigh confidence. This conflicts with FR-007 as originally written — see `spec.md` §4, which now
resolves it by giving each tier a different evidence obligation rather than requiring all content to
be directly quotable. The precedent is slice 004's five verdicts, where `unverified` is the only
evidence-free one "because it is the only one that asserts nothing".

**What did not change.** The MCP port boundary (R3), citation integrity as structural (R4), snapshot
immutability and the per-user `Company` finding (R5), the SSRF and prompt-injection posture (R6),
and the cost physics (R7) all survive the correction unaltered.

---

## R10 — OQ-A investigated: the web-search MCP server

**Measured** (web research, 2026-08-27; secondary sources, see caveat below). Four realistic
candidates:

| | **Brave** | **Tavily** | **Exa** | **SearXNG (self-hosted)** |
|---|---|---|---|---|
| Returns | URLs + snippets | URLs + snippets (`tavily-search`); raw content is a **separate** tool (`tavily-extract`) | **Full page content by default** | URLs + snippets |
| Our fetching retained? | Inherently | Only if `tavily-extract` is never exposed and `include_raw_content` stays false | Fights the design | Yes |
| API key | Yes | Yes | Yes | **None** |
| Free tier | 2,000 queries/month | Credit-based | Limited | Unlimited (self-run) |
| Maturity | **First-party** (`brave/brave-search-mcp-server`) | First-party, "production ready" | First-party | Community wrappers, several competing forks |
| New infrastructure | No — one env var | No | No | **Yes — another container** |
| Licence note | Commercial API ToS | Commercial API ToS | Commercial API ToS | AGPL, incl. its network-use clause |

**Interpretation — the deciding argument.** Brave is the only candidate where the intended trust
boundary is the **default behaviour** rather than a discipline that must be maintained. Brave
physically cannot return page content, so every byte reaching a model provably passed through
`infrastructure/jobs/fetch.py` and its SSRF guard. With Tavily the same outcome depends on
remembering never to call `tavily-extract`; one careless change routes content around the guard
silently. Exa returns content by default, so we would either discard what we paid for or ingest text
that never passed our checks.

**Interpretation — secondary reasons.** One environment variable matches the existing
`ANTHROPIC_API_KEY` pattern and adds no container to a Compose stack that already runs five; 2,000
queries/month is roughly 200–400 research runs at 5–10 queries each; and Brave publishes the server
itself, so there is one canonical implementation rather than a choice among community forks.

**Measured — the course requirement, read directly.** `docs/reference/01_course_requirements.md:31`
states only "The agent should use Tools/MCPs". Nothing there requires the **LLM** to initiate the
tool call. Line 54's "ReAct over a RAG knowledge base of CV best-practice guidelines" attaches the
ReAct suggestion to the **guidelines** path — slice 006's territory — not to company research.

**Interpretation.** An application-driven MCP client satisfies the requirement: CareerHQ is the MCP
client, the integration is a genuine MCP one, and the model still decides *what* to search. Adding a
ReAct tool-calling loop **solely** to make web search look more agentic would buy no requirement
coverage and cost an unbounded number of model calls — against the measured economics in R7. The
broader system already demonstrates an agentic workflow through slice 005's self-critique loop.

**Uncertain.** Free-tier figures and maturity claims come from aggregator sources, not from vendor
pricing pages, and no server has been tested against this codebase. Confirm Brave's current limits
and terms before committing. Recorded as *preferred*, not settled.
