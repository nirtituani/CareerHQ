# Feature Specification: Role-Aware Company Research

**Feature Branch**: `010-role-aware-research`

**Created**: 2026-08-31

**Status**: Draft

**Input**: User description: "Role-aware company research via a ResearchProvider seam. Replace the
company-scoped Layer 1 research flow as the primary path: research becomes application-scoped and
role/JD-aware, produced by one call to a research-provider abstraction, with an external research
service as the first implementation and the existing pipeline retained as a configurable fallback.
Approved decisions: 1A per-application research with per-application reuse; 2A role-independence
(008's FR-021) retired — the role comes from the job description, never from the user's CV; 3B
sections-first UI with quiet provenance."

**Supersedes**: parts of `specs/008-company-research`. Slice 008 remains the record of what was
built and why; this slice changes which path is primary and what the user sees. 008's pipeline is
not deleted — it becomes the configured fallback (FR-017). Where this spec and 008's spec
disagree about *current* intended behaviour, this spec wins.

**Evidence base**: three POC comparisons (Pango, Silverfort, Windward — session artifacts "The
Pango Test", "The Generalization Test", "Three Research Decisions", 2026-08-31). Measured: the
008 pipeline sourced 0/11 correct pages for a name-collided company; a role-aware research
provider identified the correct entity 3/3 with role-specific output in 32–53 s. Also measured:
company-level reuse would have saved ~3% of research calls on real local data (33 applications,
32 companies), which is what retired it.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Research for this application (Priority: P1)

A candidate has an application with a job description attached. From the application's Company
tab they request research and, within about a minute, read research about the correct employer,
organised for interview preparation: what the company does, its products, its business and
market, what is relevant to *this* role, what to know before the interview, and questions worth
asking — each claim traceable to a listed source.

**Why this priority**: this is the product promise the POCs validated and 008 could not deliver —
role-aware, correct-entity interview preparation. Everything else in the slice supports it.

**Independent Test**: on an application whose posting names a company with a collided name (the
Pango class), request research and verify the result describes the employer from the job
description — not any same-named company — and contains role-specific content that quotes or
engages the posting's own stack/team/domain.

**Acceptance Scenarios**:

1. **Given** an application with a job description, **When** the user requests research, **Then**
   the run starts in the background, the tab shows it running, and the finished result contains
   all seven sections with the entity identification visible.
2. **Given** the finished research, **When** the user reads "Relevant to Your Role", **Then** its
   content engages the specific role and posting (team, stack, domain), not generic company
   description.
3. **Given** a company name shared by several unrelated companies, **When** research completes,
   **Then** every listed source concerns the employer identified from the posting, and the
   identification explains how the entity was resolved.
4. **Given** research completed for this application less than the reuse window ago, **When** the
   user requests research again, **Then** the existing result is returned with no new spend, and
   the response says it was reused.

---

### User Story 2 - Research without a posting (Priority: P2)

A candidate has an application with no job description and no requirements (for example, an
imported row). They can still request research; the result is company-scoped — the role-specific
sections honestly say why they are thin — and nothing pretends a job description existed.

**Why this priority**: 96 imported applications on the deployed instance have no posting content.
The feature must not be a dead button for them, and must not fabricate role context.

**Independent Test**: request research on an application whose posting-content answer is empty;
verify the run proceeds, the company sections are populated, and the role-specific sections carry
an explanation instead of invented role content.

**Acceptance Scenarios**:

1. **Given** an application with no posting content, **When** the user requests research, **Then**
   the run proceeds as company-only research through the same flow, and the result's role-specific
   sections state that no posting was available rather than guessing a role.
2. **Given** the same application later gains a job description (user pastes one), **When** the
   user requests a refresh, **Then** a new run uses the posting and produces role-aware research.

---

### User Story 3 - The provider is down (Priority: P3)

The external research service is unreachable or misconfigured. The user either gets research from
the retained fallback pipeline (clearly recorded as such) or an honest failure they can retry —
never a silent degrade, never a result that pretends to be something it is not.

**Why this priority**: availability protection for a paid external dependency; the POC measured
the provider as a single point of failure the 008 pipeline did not have.

**Independent Test**: with the provider made unavailable in configuration, request research and
verify the configured behaviour occurs (fallback runs and is recorded as the producing path, or
the run fails with a recorded reason) and the user-facing state is accurate either way.

**Acceptance Scenarios**:

1. **Given** the provider is unavailable and fallback is enabled, **When** the user requests
   research, **Then** the fallback pipeline produces the result and the stored snapshot records
   which path produced it.
2. **Given** the provider is unavailable and fallback is disabled, **When** the user requests
   research, **Then** the run is recorded as failed with a reason, the tab shows the failure, and
   a later retry is possible.

---

### User Story 4 - Old research still readable (Priority: P3)

A user who ran 008-era company research can still open and read it. Old snapshots render in the
old shape; new snapshots render in the new shape; nothing is migrated, rewritten, or hidden.

**Why this priority**: Principle IV — research snapshots are immutable after generation. History
must keep reproducing exactly what the user was shown.

**Independent Test**: with an old-shape snapshot in the database, open the research tab and verify
it renders legibly; run new research on the same application and verify both the new result is
shown as current and the old snapshot's stored content is unchanged.

**Acceptance Scenarios**:

1. **Given** a stored 008-era snapshot, **When** the research tab loads, **Then** the old content
   renders without error and without alteration of the stored record.
2. **Given** both an old-shape and a new-shape snapshot exist for the relevant scope, **When** the
   tab loads, **Then** the newer, application-scoped result is the one presented as current.

---

### Edge Cases

- **Concurrent requests**: a second research request for the same application while one is
  running is refused as a conflict, not queued and not doubled (mirrors 008's one-running guard,
  re-scoped to the application).
- **Abandoned runs**: a run that has been "running" longer than the configured maximum is treated
  as abandoned — it stops blocking new runs and stops being shown as in-flight.
- **Provider returns the wrong entity**: the identification section is the user's tripwire — it
  names the entity and the reasoning, so a wrong resolution is visible rather than silent. The
  user's recourse is refresh (optionally after adding the company domain to the application).
- **Provider output fails validation**: a response that does not match the required structure is
  a failed run with a recorded reason — partial or malformed output is never persisted as
  research.
- **Posting text contains adversarial instructions**: posting content is untrusted data in every
  prompt or provider instruction; a posting that says "ignore your instructions" must be treated
  as text to research around, not directives (continues 008's FR-005/FR-016 framing).
- **Very long postings**: posting text beyond a configured length limit is truncated from the
  end (requirements and role context concentrate early), and the fact of truncation — and how
  much was sent — is recorded on the snapshot's stored model-configuration record, so an
  unexpectedly thin result on a huge posting is diagnosable.
- **Stale-but-reusable**: between the reuse window and the stale window the result is served with
  its age visible; past the stale window it is flagged as old and refresh is suggested — same
  two-window semantics as 008, re-scoped to the application.
- **A failed run after a successful one**: the previous successful result remains the one shown;
  failure never evicts the last good research.

## Requirements *(mandatory)*

### Functional Requirements

**Scope and input**

- **FR-001**: Research MUST be requested explicitly, per application. No automatic runs.
- **FR-002**: The research input MUST be assembled from the application: company name, company
  domain when known, role title, and posting content. The role and posting MUST come from the
  application/job description. The user's profile or CV MUST NOT contribute to research input.
  *(This retires 008's FR-021 role-independence — recorded here so its removal is deliberate:
  FR-021 existed to protect company-level reuse, which decision 1A retired.)*
- **FR-003**: Whether posting content exists MUST be answered by the application's single
  existing posting-scoreability answer, not by a new check. When it answers "nothing", research
  proceeds as company-only input through the same flow — one pipeline, with the posting as an
  optional input, never a second pipeline.

**The provider boundary**

- **FR-004**: Research MUST be produced through a replaceable research-provider boundary: one
  call taking (company name, domain, role title, posting text) and returning a validated,
  section-shaped result with sources. Provider-specific vocabulary (model tiers, credit budgets,
  search depths) MUST NOT appear in the boundary.
- **FR-005**: The first implementation MUST delegate web search, source selection, and synthesis
  to an external research service. The 008 pipeline MUST be retained and selectable by
  configuration. Every snapshot MUST record which path produced it.
- **FR-006**: The provider instructions MUST require: entity resolution from the posting's
  context with same-named companies excluded; preference for primary sources (the company's own
  materials, reputable press) over aggregator/data-broker pages; and dating of time-sensitive
  claims so stale news is not presented as current. *(Each of these failed observably in a POC
  when absent: wrong-entity sources, a data-broker headquarters error, 2014 news beside 2024
  news.)*
- **FR-007**: The result MUST include an entity identification — official name, website, and how
  the entity was distinguished from same-named companies — and the interface MUST show it.

**Output shape and provenance**

- **FR-008**: The user-facing result MUST be organised as: Company Overview; Products & Services;
  Business & Market; Relevant to Your Role; What to Know Before the Interview; Questions Worth
  Asking; Sources.
- **FR-009**: The fact/interpretation/inference tier taxonomy MUST NOT appear in the user-facing
  research surface. Provenance remains: every section's claims trace to the sources list, and
  sources are always visible and reachable.
- **FR-010**: Content whose citation was verified verbatim against a fetched page (possible on
  the fallback path) MAY be presented as verified; provider-synthesised content MUST be presented
  as provider-attributed and MUST NOT be presented as verified. The two MUST be distinguishable
  wherever both can appear.
- **FR-011**: An empty or thin section MUST explain itself (no posting available, no sources
  found) rather than rendering blank.

**Persistence, reuse, cost**

- **FR-012**: Each run produces an immutable, application-scoped snapshot recording: the
  sections, the sources, the producing path and its version marker, and the run's recorded cost
  and usage. Snapshots are never updated in place (Principle IV).
- **FR-013**: Reuse is per application: a request within the reuse window returns the existing
  snapshot with no new spend and says so; between reuse and stale windows the result shows its
  age; past the stale window it is flagged and refresh suggested. Company-level reuse across
  applications is retired (decision 1A).
- **FR-014**: 008-era snapshots MUST remain readable and unmodified. Old-shape and new-shape
  snapshots are distinguished by their stored version marker; both render; no migration of stored
  research content.
- **FR-015**: Every run MUST record what it cost. Where the producing path reports token usage
  and cost, record those. Where the provider's billing is not returned with the response (the
  external service reports credits asynchronously and its usage endpoint lags), the snapshot MUST
  record an explicit cost basis — the documented rate marked as an estimate — rather than zero,
  and MUST never present an estimated cost as a billed one. A failed run records what it spent
  before failing (008's lesson: a failure that reads as free is worse than one that reads as
  unrecorded).
- **FR-016**: At most one run per application may be in flight; a concurrent request is refused
  as a conflict. A failure is recorded with a reason, never swallowed, and never evicts the last
  successful snapshot. A run exceeding the configured maximum duration is treated as abandoned.

**Fallback and failure honesty**

- **FR-017**: When the provider is unavailable or unconfigured, behaviour follows configuration:
  either the retained 008 pipeline runs (and the snapshot records it as the producer) or the run
  fails honestly with a recorded reason. A provider failure MUST NOT silently degrade into
  partial results.

**Security and trust**

- **FR-018**: Ownership comes from the session; research is reachable only through an application
  the requesting user owns (continues 008's FR-018/019).
- **FR-019**: Posting text sent to any provider or model is untrusted data and framed as such.
  Provider output is untrusted until validated against the expected structure. Profile/CV data is
  never sent to a research provider (see FR-002).

### Key Entities

- **Application Research Snapshot**: an immutable, application-scoped record of one research run —
  sections, entity identification, producing path + version marker, cost/usage, status
  (running/succeeded/failed), failure reason. The application's current research pointer moves
  only on success.
- **Research Source**: one consulted source for a snapshot — title, URL, and (fallback path only)
  the verified excerpt that survived checking; failed fetches recorded as such.
- **Legacy Company Research Snapshot (008)**: existing immutable records in the tiered shape;
  read-only from this slice onward, still renderable.
- **Provider selection**: the configuration that names the producing path (external provider vs
  retained pipeline) and is stamped into each snapshot.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On applications with a posting, research names and describes the correct employer —
  measured on at least 5 real applications including at least one name-collided company, with
  every listed source concerning the identified employer. (POC baseline: 3/3 companies, 26/26
  sources.)
- **SC-002**: On applications with a posting, the role-relevant section and questions engage the
  posting's specifics (team, stack, or domain) in 100% of runs — assessed by a person reading the
  output against the posting, not by keyword matching.
- **SC-003**: Research completes and is readable within 90 seconds for at least 9 of 10 runs
  (POC observed 32–53 s on the provider path; the fallback path's 59–104 s also fits).
- **SC-004**: A repeat request within the reuse window completes without any new spend and
  returns in under 2 seconds.
- **SC-005**: Every 008-era snapshot present before the change still renders afterwards, with
  stored content byte-identical.
- **SC-006**: 100% of runs — succeeded and failed — carry a recorded, non-null cost basis, with
  estimates explicitly marked as estimates.
- **SC-007**: No research input contains profile/CV-derived content, verified by a test that
  inspects the assembled input on a seeded application whose profile contains a sentinel value.
- **SC-008**: A user shown the new research surface sees no fact/interpretation/inference
  labels anywhere in it.

## Assumptions

- The external research service account (already configured for 008's search) includes the
  research capability within the current plan's credit allowance; per-run pricing is dynamic
  (documented range known), which is why FR-015 demands an explicit cost basis rather than a
  number the response does not contain.
- Decision 1A's economics rest on measured local data (one multi-application company in 32) and
  on typical job-search behaviour; if multi-application companies become common, a company-level
  cache can be added later as an optimisation without changing the user-facing contract.
- The 008 pipeline is kept as the fallback *as it is*, wrong-entity risk included — it is a
  degraded mode, and its known weakness is part of why it is not the primary path. Fixing the
  fallback's entity resolution is out of scope.
- The two freshness windows keep 008's durations (reuse 30 days, stale 90 days), re-scoped to the
  application; no evidence suggested different durations.
- Old-shape snapshots stop being produced but their read path stays until a future slice decides
  their retirement; deleting them is out of scope.
- The Match analysis flow, which reads posting content through the same scoreability answer, is
  unaffected; this slice adds a third caller, changing nothing about the first two.

## Out of Scope

- Implementing any production code, schema migration, or UI in this phase (definition only).
- Improving the fallback pipeline's entity resolution.
- Company-level research caching (may return later as an optimisation slice).
- Wiring 008's unbuilt Layer 2 (`research_role`) — superseded by this design.
- A second external provider implementation (the boundary makes it possible; nothing selects it).
- Automatic re-research on posting changes; refresh stays explicit.
