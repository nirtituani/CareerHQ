# Phase 0 Research: Role-Aware Company Research

The unknowns for this slice were resolved **empirically before the spec existed** — three POC
comparisons on real companies (Pango, Silverfort, Windward; session artifacts "The Pango Test"
and "The Generalization Test", 2026-08-31) plus a decision round approved by the project owner
("Three Research Decisions": 1A, 2A, 3B). This file consolidates those findings and the design
decisions they force, in the standard format. No `NEEDS CLARIFICATION` markers remain in the
Technical Context.

---

## D1 — Research production: external research service, builtin pipeline as fallback

**Decision**: produce research through Tavily Research (`POST https://api.tavily.com/research`,
`model="mini"`, `output_schema` set to our section schema, `citation_format="numbered"`), behind
a port. Keep the 008 pipeline as a second adapter behind the same port, selected by
configuration.

**Rationale** (measured): the 008 pipeline sourced 0/11 correct pages on a name-collided company
(Pango) in two arms, including one with the domain hint — whose `site:` queries turned out to be
unreachable because the first two queries fill `MAX_SOURCES=6`. The provider resolved the entity
3/3 (26/26 correct sources), produced role-specific content 3/3, and was faster in every pairing
(32–53 s vs 59–104 s). The provider accepts an `output_schema`, which returns the UI's shape
directly. Requests must send a `description` on **every** schema property (POC hit the 400).

**Alternatives considered**: patching the 008 pipeline (`include_domains`, query reordering, a
disambiguation pre-pass) — rejected as rebuilding what the provider already does, with less
context; OpenAI web search — untested by owner decision (no API key), kept possible by the port;
Tavily `model="pro"` — not needed at POC quality, 4–25× the credit floor.

## D2 — Persistence: reshape the empty `role_research_snapshots` into `application_research_snapshots`

**Correction recorded**: the decision document claimed persistence needs *no schema change*.
Planning falsified this: `role_research_snapshots.company_research_snapshot_id` is **NOT NULL**
(mandatory lineage to a Layer 1 snapshot, FR-023 of 008), and the new design has no Layer 1
snapshot to point at. A migration is required; pretending otherwise would surface as a
NOT NULL violation on the first successful run.

**Decision**: one migration (`0020_application_research`) that reshapes the table **in place**:
rename `role_research_snapshots` → `application_research_snapshots`; drop
`company_research_snapshot_id` entirely; rename `findings` → `sections`; add `produced_by`
(varchar, e.g. `provider:tavily-research` / `builtin`) and `cost_basis` (varchar,
`recorded` / `estimate`); carry over the status/tokens/cost check constraints and the
one-running-per-application partial unique index under new names. Rename
`research_sources.role_snapshot_id` → `application_snapshot_id` and rewrite
`ck_research_sources_exactly_one_snapshot` by hand (Alembic does not diff check constraints —
project gotcha). The migration **asserts the table is empty before reshaping** and fails loudly
otherwise.

**Rationale**: the table is provably empty everywhere — Layer 2 was never wired to any route
(persistence helpers exist; no caller outside tests), so the reshape rewrites no data and risks
no history. Reshaping in place keeps `research_sources` wiring and avoids a three-way FK web.
Dropping the lineage column rather than nulling it keeps the schema telling the truth: in this
design the snapshot *is* the whole research, and a permanently-NULL column is the kind of
unanswerable vestige the original model docstring warned about.

**Alternatives considered**: make the lineage column nullable (smallest diff) — rejected: every
future row would carry a NULL whose meaning ("no Layer 1 existed") is knowable only from this
document; a brand-new table plus a third `research_sources` FK — rejected: bigger migration,
three-way exactly-one-of constraint, and an abandoned empty table left behind; writing a synthetic
company snapshot as lineage — rejected outright as fabricated provenance.

## D3 — Both output shapes persist unconverted; `prompt_version` is the discriminator

**Decision**: `sections` (JSONB) stores whatever the producing path emitted: the new
`ApplicationResearch` shape (`prompt_version="app-v1"`) from the provider, or 008's tiered
`CompanyResearch` shape (`prompt_version="v2-dense"`) from the fallback. Legacy
`company_research_snapshots` rows are untouched and keep rendering through the read path.
The API response carries a `shape` discriminator derived from `prompt_version`; the frontend
dispatches renderers on it.

**Rationale**: converting tiered→sections would discard verified excerpts (FR-010's whole value
on the fallback path) or fabricate section text nobody wrote; converting sections→tiers would
invent epistemology. JSONB is shapeless; the version marker already exists on every snapshot row
(both tables) and is exactly the mechanism FR-014 asks for. The UI must render two shapes anyway
because history exists.

**Alternatives considered**: lossy normalisation to one shape — rejected above; a view-model
conversion at read time only — accepted *in addition* where trivial (the legacy renderer is the
current UI extracted), but storage stays faithful to what was produced.

## D4 — Provider instructions: entity resolution, primary sources, dated claims

**Decision**: the research input sent to the provider contains, verbatim-quoted as untrusted
data: company name (+ domain when known), role title, and posting text; and instructs the
provider to (a) first identify the correct entity from the posting's details and exclude
same-named companies, (b) prefer primary sources (the employer's own materials, reputable press)
over aggregator/data-broker pages, (c) attach dates to time-sensitive claims and not present old
news as current. The output schema requires `company_identification.how_identified`.

**Rationale** (each clause earned by a measured failure): without (a), the 008 pipeline mixed
three wrong companies; with the JD present the provider resolved Pango without ever being told
the domain. Without (b), the provider stated a wrong Silverfort HQ twice, sourced from a
data-broker page. Without (c), it presented 2014 US-expansion news beside the later sale of US
operations without noticing the tension.

**Alternatives considered**: hard `include_domains` filtering — rejected as primary mechanism
(the domain is usually unknown at request time; the JD is the reliable disambiguator; soft
preference remains possible later without contract change).

## D5 — Cost recording: explicit basis, never zero, never estimate-dressed-as-billed

**Decision**: every snapshot records `cost`, `input_tokens`, `output_tokens`, and `cost_basis`.
Fallback runs record exact LiteLLM usage (`cost_basis="recorded"`). Provider runs record zero
tokens and a credit-derived estimate at the documented per-credit rate with
`cost_basis="estimate"`, plus the raw basis facts in `model_config_used` (model tier, documented
credit range). A failed run records whatever basis it had at failure. The UI and any reporting
must not sum estimates and recorded costs into one unlabelled number.

**Rationale**: measured — the Tavily usage endpoint reported the same totals before and after
every POC run (`research_usage: 0` throughout), so response-time billing attribution is not
available. Principle V's obligation is auditability; an explicitly-marked estimate is auditable,
a silent `$0` is the failure 008's own docstrings warn about (slice 005 lost $0.51 to runs that
read as free).

**Alternatives considered**: polling the usage endpoint later to reconcile — rejected for this
slice (adds a background job for a number that may never attribute per-run); recording NULL —
rejected by SC-006.

## D6 — Reuse and freshness: 008's windows, re-scoped to the application

**Decision**: keep `RESEARCH_REUSE_DAYS = 30` and `RESEARCH_STALE_DAYS = 90` and the derived
`freshness()`; the reuse question is asked against the application's own newest succeeded
snapshot. `POST` answers `reused: true` inside the window. Company-level reuse is retired.

**Rationale**: decision 1A, grounded in measurement — one multi-application company in 32 locally
(~3% possible saving); per-run provider cost is the same order as the 008 pipeline. No evidence
suggested different window durations, and changing semantics and durations at once would blur
which change caused what.

## D7 — No-posting applications: same flow, posting optional

**Decision**: `scoreable_posting(application)` remains the single answer. When it returns text,
the input includes role title + posting; when `None`, the provider is asked for company-only
research and the role sections must explain the absence (FR-011). One pipeline, one code path,
the posting an optional parameter.

**Rationale**: spec FR-003; 96 imported applications have no posting content, and a dead button
or a guessed role are both worse than honest company-only research. The two-questions gotcha from
Match (meaningful-to-score vs anything-to-send) does not recur here because research has only the
second question.

## D8 — Provider unavailability: configured, recorded, never silent

**Decision**: `research_provider` selects the primary path; `research_fallback_enabled` decides
what a provider failure does — run the builtin adapter (snapshot records `produced_by="builtin"`)
or fail the run with the provider's error class as the recorded reason. Malformed provider output
(schema validation failure) is a failed run, never a partially-persisted one. Timeouts come from
`research_provider_timeout_seconds` (default 300 — POC max observed 53 s, with headroom well
under the 900 s abandonment ceiling).

**Rationale**: FR-017's "never silently degrade"; the fallback's known wrong-entity risk is an
accepted degraded mode (spec assumption), visible in `produced_by`.
