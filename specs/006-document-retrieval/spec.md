# Feature Specification: Document & Retrieval

**Feature Branch**: `006-document-retrieval`

**Created**: 2026-08-26

**Status**: Draft — design under review. **No implementation tasks yet.**

**Input**: Slice 006 per [docs/05](../../docs/05_Implementation_Plan.md) §5.6 — replace the
Tailoring agent's static rubric with cited retrieval over a guideline corpus in pgvector, and turn
an approved version into a sendable, permanently locked document.

---

## Why This Slice Exists

### The port is already built, and that is the whole design

Slice 005 did not hardcode its rubric. It defined `GuidelineSource` —
`guidelines_for(context: GuidelineQuery) -> Sequence[Guideline]` — and wired a static
implementation behind it. That port's docstring names itself "the 005/006 boundary … so that
boundary is structural rather than an intention someone remembers."

So this slice is **an implementation swap, not a redesign**. There is no Tailoring Agent v2. The
four nodes, their responsibilities, the state, the finalisation rules and the approval flow all
stay exactly as slice 005 built them. `Guideline.source` already exists and is already persisted
per run as `guidelines_used`, precisely so citations and slice 007's retrieval-quality metric
would not require changing node inputs later.

**The risk this slice must not realise** is letting RAG's vocabulary leak upward. The port
deliberately has no `top_k`, no similarity score, no embedding parameter. If those appear in the
graph, the boundary has failed.

### This is the project's only RAG

Vector retrieval is a graded architectural requirement and appears exactly once in this system, by
design. [Constitution VI](../../.specify/memory/constitution.md) and
[docs/03](../../docs/03_Domain_Model.md) §7.5 draw the line: **structured facts are retrieved
relationally; only semantic knowledge goes through vector search.** Resume-writing guidance is
semantic knowledge. Profile facts, application status and version ownership are not, and embedding
them would produce approximate answers to questions the database answers exactly (ADR-008).

### A resume nobody can send is not finished

Slice 005 ends at an approved version in the database. The document half closes that: one
ATS-safe PDF template, the `EXPORTED` and `SUBMITTED` states that `VersionStatus` deliberately
reserved, and a `SubmittedResume` locked permanently with a checksum — which is what
[Constitution IV](../../.specify/memory/constitution.md) requires and what lets slice 009 later ask
which versions led to interviews.

### Deliberately not here

Company Research (slice 008) is out of scope entirely and is being designed separately. This slice
adds no web access, no MCP, and no second agent.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The agent writes with sourced guidance, not a fixed rubric (Priority: P1)

When I tailor a resume, the advice steering the rewrite is retrieved from a guideline library and
chosen for *this* posting, and I can see which guidance was used and where each piece came from.

**Why this priority**: It is the architectural core of the slice, the project's only RAG, and
slice 007 cannot measure retrieval quality against something that does not exist.

**Independent Test**: Fully testable by running a tailoring job with the retrieval implementation
wired in and confirming the run records which guidelines it used, each with a resolvable source —
delivering better-targeted guidance with no change to the workflow.

**Acceptance Scenarios**:

1. **Given** a guideline corpus has been ingested, **When** I tailor a resume for a backend role,
   **Then** the guidance used is relevant to that role and each item carries a citation
   identifying the document and location it came from.
2. **Given** two postings in different disciplines, **When** each is tailored, **Then** the
   retrieved guidance differs between them.
3. **Given** a completed run, **When** I inspect its record, **Then** the exact guidance used is
   reproducible after the fact, not re-derived.
4. **Given** the corpus is empty or retrieval returns nothing, **When** I tailor a resume,
   **Then** the run still completes using a documented fallback rather than failing.

---

### User Story 2 - Export an approved version as a document I can send (Priority: P2)

Once I have approved a tailored version, I can export it as a PDF that applicant tracking systems
parse correctly.

**Why this priority**: It is the first point at which the product produces something a user can
actually use outside the system. Independent of retrieval.

**Independent Test**: Testable by approving a version and exporting it, with no retrieval involved.

**Acceptance Scenarios**:

1. **Given** an approved version, **When** I export it, **Then** I receive a PDF whose text
   content matches the approved items, in the approved order.
2. **Given** an exported version, **When** I inspect its state, **Then** it is recorded as
   `EXPORTED` with the time of export.
3. **Given** a version that is not approved, **When** I attempt to export it, **Then** the export
   is refused.

---

### User Story 3 - Mark it submitted, and have that record never change (Priority: P3)

When I actually send a resume to an employer, the system freezes exactly what I sent.

**Why this priority**: Depends on export existing. Its value is historical rather than immediate,
but it is what makes application history trustworthy.

**Independent Test**: Testable by submitting an exported version and then attempting to alter it
or its source profile, confirming the record does not move.

**Acceptance Scenarios**:

1. **Given** an exported version, **When** I mark it submitted, **Then** a `SubmittedResume` is
   created with a stable checksum and the version becomes `SUBMITTED`.
2. **Given** a submitted resume, **When** anything in my profile later changes, **Then** the
   submitted record and its document are unchanged.
3. **Given** a submitted resume, **When** any actor attempts to modify it, **Then** the attempt is
   refused rather than silently ignored.
4. **Given** an application in `Applied` or later, **When** I inspect it, **Then** it references a
   submitted resume (Constitution IV).

---

### Edge Cases

- Corpus is empty, or retrieval returns nothing relevant — the run must still complete.
- Retrieval is slow or unavailable — tailoring must degrade, not hang or fail.
- A guideline document is re-ingested with changed content — historical runs must still resolve
  the citation they recorded.
- Retrieved guidance contradicts itself, or contradicts the honesty rules — grounding rules win.
- A profile item contains text that resembles an instruction — retrieval must not become an
  injection path into the Draft prompt.
- Export is attempted twice; submission is attempted twice.
- A version is submitted, then the user wants to "edit and resend" — this must produce a new
  version, never a mutation.
- Retrieved context is large enough to materially change prompt size and therefore cost.

---

## Requirements *(mandatory)*

### Retrieval and the guideline corpus

- **FR-001**: The system MUST provide a retrieval-backed implementation of the existing
  `GuidelineSource` port, selected by configuration, without changing the port's signature.
- **FR-002**: The tailoring workflow's nodes, state, finalisation rules and approval flow MUST NOT
  change as a consequence of this slice.
- **FR-003**: Retrieval vocabulary (result counts, similarity scores, embedding parameters) MUST
  NOT appear in the workflow, its state, or its prompts.
- **FR-004**: The system MUST ingest a **curated, version-controlled** guideline corpus into
  durable storage, dividing documents into retrievable units. User-supplied guideline documents are
  out of scope for this slice (D1).
- **FR-005**: Every retrievable unit MUST carry provenance sufficient to identify the document and
  the location within it.
- **FR-006**: Every guideline returned to the workflow MUST carry a citation derived from that
  provenance.
- **FR-007**: Retrieval MUST select units by semantic relevance to the supplied query.
- **FR-008**: Structured facts (profile content, application status, version ownership) MUST NOT
  be embedded or retrieved by vector search (Constitution VI, ADR-008).
- **FR-009**: When retrieval yields nothing, the system MUST fall back to documented default
  guidance and record that it did so.
- **FR-010**: Retrieval failure or timeout MUST NOT fail a tailoring run.
- **FR-011**: The guidance used by a run MUST be persisted with the run and remain resolvable after
  the corpus changes.
- **FR-012**: The corpus MUST be re-ingestable without invalidating the citations recorded by
  earlier runs.
- **FR-013**: Retrieved content MUST be treated as data, never as instructions to the model, and
  MUST NOT be able to override the honesty and grounding rules.
- **FR-014**: The volume of retrieved context injected into any prompt MUST be bounded by an
  explicit, configured limit.
- **FR-028**: Embedding computation MUST sit behind an application-layer port, with its
  implementation in the infrastructure layer. No embedding library or provider SDK may be imported
  by the application layer (D3). *(Numbering is append-only so earlier references stay stable.)*
- **FR-029**: Guidance MUST be retrieved **once per run, before the workflow is invoked**, and the
  same result shared by every node that consumes it (D2).
- **FR-030**: Corpus content itself MUST be screened, before it can be retrieved, for guidance that
  invites fabrication — including instructions to estimate figures the profile does not supply,
  keyword-coverage quotas that could pressure invention, and any other guidance conflicting with
  Principle III or AI-008. Such guidance MUST be excluded from the corpus and recorded as excluded.
  *(This is distinct from FR-013: FR-013 governs how retrieved text is **treated**; FR-030 governs
  what is allowed to **be** corpus content.)*
- **FR-036**: The corpus MUST contain only **authored normative guidance**. Demonstrative material
  (Before/After examples) and research evidence (source digests, registers) MUST NOT be retrievable
  as writing guidance, and MUST NOT become normative by being stored alongside it.
- **FR-037**: A rule and a retrieval chunk are **1:1** in Corpus V1. A rule's qualifications and
  exceptions MUST live in the same chunk as the rule, never in a separate one.

### Israeli-market guidance

Market-specific rules. Each applies **in addition to** universal guidance and MUST NOT displace a
universal rule where no Israeli distinction is evidenced (see FR-038 for the precedence rule).

- **FR-032**: For the Israeli market, a CV MUST NOT include the candidate's age or date of birth.
- **FR-033**: For the Israeli market, a CV MUST NOT include a full residential address; city and
  country are sufficient.
- **FR-034**: Where military service is relevant to the candidate and the target role, it MAY be
  presented as a credibility signal, expressed as **translated capability** rather than rank or
  unit title alone. This is **contextual** — it MUST NOT be applied as a requirement that every
  candidate emphasise military service.
- **FR-035**: For experienced candidates in the Israeli market, professional experience MUST be
  placed before education and other secondary sections. The inverse MAY apply to students and new
  graduates.
- **FR-038**: Guidance MUST carry a market classification, and that classification MUST be applied
  as follows: `global` means **the supporting evidence is global — not that the guidance is
  inapplicable to Israel**, and such guidance remains applicable to Israeli-market CVs; `israel`
  means the evidence specifically supports the Israeli market. Where authoritative Israeli evidence
  conflicts with global guidance, the Israeli guidance MUST take precedence for Israeli-market CVs.
- **FR-039**: The system MUST record the duration of each retrieval operation — from retrieval
  start through the final selected guideline set being returned — so SC-007 can be **measured
  rather than derived**. Embedding-model initialisation MUST be excluded (SC-007). The
  instrumentation MUST be lightweight and deterministic; it MUST NOT introduce observability
  infrastructure beyond what this single metric requires.

### Export

- **FR-015**: Users MUST be able to export an approved version as a PDF.
- **FR-016**: Export MUST be refused for a version that has not been approved.
- **FR-017**: The exported document's text MUST correspond exactly to the approved items and their
  approved order.
- **FR-018**: The document MUST follow one plain, ATS-safe layout: no tables, columns, graphics or
  icons.
- **FR-019**: Export MUST record that it happened, and when.
- **FR-031**: Rendering MUST be **deterministic within one runtime environment**: rendering
  identical approved content twice **on the same runtime** MUST produce byte-identical output.
  Without this, the stable checksum FR-021 requires is not enforceable, and the failure surfaces
  only on a re-export — after submissions already exist.
  *(Scope clarified 2026-08-28, T032. The unqualified wording read as a claim about arbitrary
  machines, which nothing requires: FR-021 verifies **stored bytes** against a recorded checksum
  and never re-renders, and a re-export happens on the deployed runtime. **Which font resolves
  decides the bytes**, so cross-machine identity would mean vendoring a font — rejected, no
  requirement asks for it. The runtime's font is instead **declared**: `fonts-dejavu-core` is an
  explicit dependency of the backend image.)*

### Submission and immutability

- **FR-020**: Users MUST be able to mark an exported version as submitted.
- **FR-021**: Submission MUST create a permanent record carrying a stable checksum of the exact
  document sent.
- **FR-022**: A submitted record and its document MUST be immutable; modification attempts MUST be
  refused explicitly.
- **FR-023**: Later profile or version changes MUST NOT alter any submitted record.
- **FR-024**: An application in `Applied` or later MUST reference a submitted resume.
- **FR-025**: Producing a revised resume after submission MUST create a new version, never mutate
  the submitted one.

### Ownership and audit

- **FR-026**: Every corpus, export and submission operation MUST be scoped to the authenticated
  user's own data; ownership MUST derive from the session, never from the request.
- **FR-027**: Any model or embedding invocation MUST record its configuration and usage, as
  Principle V requires of all AI execution.

### Key Entities

- **Guideline Document**: A curated source of resume-writing advice. Has an identity, a version or
  revision, and provenance.
- **Guideline Chunk**: A retrievable unit of a document, carrying its text, its embedding, and its
  location within the parent document.
- **Guideline Citation**: The reference recorded alongside guidance a run used, resolvable to the
  document and location even after re-ingestion.
- **Exported Document**: The rendered artifact for a version, with its creation time.
- **SubmittedResume**: The permanent, checksummed record of what was actually sent. Immutable.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a sample of at least 10 postings spanning at least 3 disciplines, a reviewer
  judges the retrieved guidance more relevant to the posting than the fixed rubric it replaces in
  at least 70% of cases.
- **SC-002**: 100% of guidance items shown or recorded carry a citation that resolves to a
  document and location.
- **SC-003**: 100% of completed runs can reproduce, after the fact, the exact guidance they used.
- **SC-004**: Tailoring completes successfully in 100% of runs where retrieval returns nothing or
  fails.
- **SC-005**: The exported document's text matches the approved content exactly in 100% of exports.
- **SC-006**: 0 successful modifications of a submitted record across all attempts, including
  profile changes made afterwards.
- **SC-007**: Retrieval adds **no more than 500ms** to a tailoring run, measured as **steady-state
  per-run retrieval latency** rather than derived. Embedding-model initialisation is **startup
  overhead and is excluded** from this measurement — `sentence-transformers` loads the model into
  memory on first use, which takes seconds; that is a process-startup concern, and folding it into
  a per-run figure would let a real regression hide inside it.
  **MET — measured 2026-08-28 (T044), against the ingested corpus in the backend image.**
  n=30, `all-MiniLM-L6-v2`, 79 chunks, ceiling 1,500: **p50 12.1 ms, p95 20.9 ms, max 24.8 ms**
  (worst sample **20× under** the threshold). Every figure is
  `RetrievedGuidelines.last_retrieval_ms` — the number FR-039 requires the system to record — not
  a stopwatch wrapped around the call. **The excluded initialisation is 133–570 ms**, which on its
  own would consume most of the budget; measured separately rather than subtracted, and excluded
  by `warm_up()` at startup rather than by estimate. See research.md R14.
- **SC-008**: Retrieval increases tailoring cost per run by **no more than 2%**, measured and
  reported before the slice is called done. **Baseline and retrieval measurements MUST be taken
  under the same pricing and model conditions**, or the comparison means nothing (see the note
  below).
  **MISSED — measured 2026-08-28/29 (T045). 2.12% against a 2% threshold.**
  Two paid arms, one process, one application, one pricing window: static $0.446391 (5 calls,
  revised) and retrieval $0.206268 (3 calls, first-pass clear). The attributable cost is
  **+4,727 input tokens** across the two guidance-consuming calls — `tailor_plan` +2,371 (a
  perfect control: only the guidance block differs) and `tailor_draft` +2,356 — at Sonnet 5's
  $2.00/MTok input rate, **$0.009454**, or **2.12%** of the same-session baseline. It is
  **2.29%** against the mean of the five measured static runs and **3.18%** at the post-2026-08-31
  Sonnet rate.
  **The target is not adjusted**, following the SC-004 and SC-001 precedent. The excess is the
  citation metadata: `token_count` — what the 1,500 ceiling budgets — counts **rule text only**,
  while the rendered block also carries a `slug · locator · hash` per guideline. Measured on the
  same prompt builder: static 492 tokens (358 text + 134 citations), retrieval 2,190 (1,523 +
  **667**). See research.md R15.


### Why these thresholds, and why the earlier ones were not gates

The first draft of SC-007/SC-008 said 5 seconds and 10%. Both were **so loose they could not
fail**, which makes a threshold decoration rather than a gate — the same defect this project
records elsewhere as "a gate nobody has watched fail is not a gate."

The architecture says why. Retrieval **replaces** the static rubric rather than adding to it. The
rendered guidance block measures **507 tokens**; a retrieval capped at 1,500 (D5) adds on the order
of **+1,000 input tokens across the two calls that consume guidance** — roughly **1.5%** of the
measured $0.400491 Harman run. A 10% ceiling is more than an order of magnitude looser than the
designed effect, so a genuine regression would pass unnoticed.

Latency is further off. Elapsed time tracks **output** tokens at ~92 tok/s across six measured
runs; input tokens barely move it. Retrieval's own work is a local query embedding (tens of ms) and
a pgvector scan over ~130 rows (sub-millisecond). The expected addition is **well under 500ms**, so
a 5-second ceiling was 10–100× too loose.

**On the pricing condition in SC-008.** Sonnet 5's introductory rate ($2/$10 per MTok) ends
2026-08-31, reverting to $3/$15, while the Opus reviewer's price is unchanged — so the cost *mix*
shifts across that date. A percentage measured with a baseline on one side and a retrieval run on
the other would report a pricing change as a retrieval regression. Measuring both arms in the same
session satisfies this naturally.

---

## Measurement Carried Forward *(mostly not built in this slice — see the exception)*

Two items from the slice 005 cost/latency investigation are recorded here so they stay visible.
Neither is a production configuration change. **One exception, added when D6 was resolved**: the
retrieval-latency half of M-001 *is* implementation work for this slice (FR-039); everything else
below stays carried forward.

- **M-001 — Per-call LLM latency is not instrumented.** Persisted call records carry task, model,
  tokens and cost, but **no timestamps**, so per-*node* latency (Plan, Draft, Review, Revise) is
  only derivable from throughput assumptions rather than measured. **This half remains carried
  forward** to slice 007. Its sibling — the latency of the *retrieval operation itself* — is
  **no longer deferred**: D6 assigns it to this slice, and FR-039 requires it, because SC-007 is
  now a measured threshold rather than an estimate.
- **M-002 — Thinking is a large, unmeasured share of cost and latency.** A controlled single-
  variable A/B on the real Draft prompt measured 8,707 → 3,448 completion tokens and 93.2s →
  45.9s when thinking was disabled, with quality impact **not** established. Adaptive thinking is
  on by default and is invisible in the usage object. This is evidence for slice 007 to evaluate;
  it MUST NOT be turned into a configuration change without a quality measurement.

---

## Resolved Decisions

Resolved 2026-08-27, before planning. Each records what was rejected, because the rejected option
is the part that gets silently re-litigated later.

- **D1 — Corpus provenance: curated only.** The corpus is a curated, version-controlled house
  asset. **Rejected: user-uploaded guideline documents.** Retrieved text is injected into the Plan
  and Draft prompts — the prompts of the one component that writes claims on a person's behalf.
  A curated corpus is a trusted input reviewed like code, which is what lets FR-013 ("data, never
  instructions") be structural rather than aspirational, and what keeps citations resolvable
  (FR-012). User upload would make every chunk attacker-influenceable, change the data model from
  one global corpus to per-user corpora, and deprive slice 007 of a fixed corpus to measure
  retrieval quality against. It is a legitimate future slice, not a side effect of this one.

- **D2 — Retrieval call site: once, before the graph (Option C).** Guidance is retrieved a single
  time in the use case and shared by Plan and Draft, exactly as slice 005 already does. **Rejected:
  per-node retrieval inside Plan and Draft** (which would have restored the call site the
  `GuidelineSource` docstring originally described), and **rejected outright: retrieval as a graph
  node**, which the same docstring pre-emptively forbids as "a workflow change caused by nothing
  but RAG arriving."

  The evidence: the rendered guidance block is **507 tokens — 5.3% of the ~9,630-token Draft
  prompt**, and retrieval replaces it with at most **1,500 tokens** under the FR-014 ceiling
  (~15.6% of that prompt, ≈19 rules at the measured 76 tokens/rule). Plan-aware retrieval's real
  job is fitting a context budget, and at this scale no such budget binds. *(Corrected 2026-08-28
  from "~1,690 tokens at 40 retrieved chunks", which assumed 42 tokens/rule; see `research.md` R6.
  D2 is unchanged.)* Structurally,
  resume-writing guidance is largely **job-independent** — "never invent a number", "no tables or
  columns" hold for every posting — so the plan adds little information to a guidance query that
  already carries the job requirements the plan was derived from. Per-node retrieval would have
  changed a just-stabilised workflow in exchange for a benefit nobody has measured.

  **Consequences.** FR-002 needs no amendment, which is itself evidence the option fits the slice.
  `GuidelineQuery.section` stays unused. The `GuidelineSource` docstring, which described the
  rejected call site, is amended to match — resolving the doc/code conflict explicitly as the
  constitution requires, on the cheaper side. Per-node retrieval is revisitable **only** if slice
  007's retrieval-quality metric shows shared retrieval missing relevant guidance.


- **D3 — Embedding execution: local, behind an application port.** Embeddings are computed by a
  local model reached through a dedicated application-layer port, with the implementation in
  infrastructure (FR-028). **Rejected: a hosted embedding provider**, and **rejected: importing an
  embedding library directly in application code.** Anthropic has no embeddings endpoint, so this
  cannot travel through the existing `complete()` seam; a direct import would break
  `test_the_application_layer_imports_no_provider_sdk`, a release-blocking guard. A hosted provider
  would add a second paid dependency and key, put a network call inside the tailoring path, and
  send guideline and query text — the latter derived from the user's profile and job — to a third
  party. Local execution also preserves the existing property that the stack runs with no API key.


- **D5 — Retrieved-context budget: 1,500 tokens, ≈19 rules.** This is the configured limit FR-014
  requires. Sized from the floor upward rather than guessed: **integrity rules are always retrieved
  and can never be crowded out by semantic relevance** (~12–15 rules), Israeli-market rules add
  ~10–14 where applicable, and topic-relevant universal/ATS/role guidance ~10–15. 1,500 tokens is
  about 3× today's 507-token rubric and ~15% of the Draft prompt's input — enough headroom that a
  close semantic match can never displace a safety rule. **Rejected: a tighter budget**, which would
  force integrity rules to compete with advice; **rejected: an open-ended budget**, which would make
  SC-008 unmeasurable.

  **Amended 2026-08-28 — the rule count, not the budget.** This decision originally read "~35
  rules", derived at 42 tokens/rule from the shipped rubric. Authored corpus rules measure **~76
  tokens/rule** (`research.md` R6), because FR-037 requires each rule to carry its qualifications
  in its own chunk. **1,500 tokens therefore holds ≈19 rules, not ~35**, and the floor-upward
  arithmetic above no longer fits inside it — integrity alone is 900–1,140 tokens.

  **The budget stays at 1,500 and the rules stay long.** Shortening rules to restore the count
  would strip the qualifications FR-037 exists to keep, and raising the ceiling on arithmetic
  alone would change a cost- and latency-bearing number before a single retrieval has been
  measured. T044 measures actual retrieval; if the pinned integrity set does crowd out topical
  guidance, that measurement is the evidence for a new ceiling. Recorded as an open consequence
  rather than resolved here.

- **D6 — Retrieval latency instrumentation belongs to this slice.** SC-007 is now a **measured**
  ≤500ms threshold, and a threshold nobody can measure is not a threshold — so the instrumentation
  is a dependency of verifying this slice, not an optional extra. **Scope is deliberately narrow**
  (FR-039): the complete steady-state retrieval operation, from start to the final selected
  guideline set, excluding embedding-model initialisation. Lightweight and deterministic; no new
  observability infrastructure.
  **Explicitly *not* in scope: per-call LLM timestamps** on `tailoring_run_calls` — that is the
  other half of M-001 and stays with slice 007. Conflating the two would widen this slice to solve
  a problem SC-007 does not have.

- **D7 — Renderer: WeasyPrint.** Selected for Slice 006. **Rejected: headless Chrome** (hundreds of
  MB in the image and a flaky CI dependency), **ReportLab** (workable and deterministic, but the
  template becomes imperative Python that nobody will review as a design), and **DOCX-then-convert**
  (two artifacts, an external converter, and a second thing to checksum, which collides with D8).
  **Not "pure Python", and that matters for deployment**: WeasyPrint binds Pango, Cairo and
  GObject through `cffi`, so the Docker image needs `libpango-1.0-0`, `libpangoft2-1.0-0`,
  `libharfbuzz0b` and `libcairo2`, and local macOS development needs `brew install pango`. A
  missing native library fails at **import**, not at render (T049). This is ~30–50 MB of system
  packages — still far below the 527 MB `torch` wheel that made option A unattractive, and it does
  not change the export contract or the renderer boundary.
  **Licensing rationale**: WeasyPrint is BSD-3, satisfying the discipline already recorded in this
  repository — `infrastructure/documents/pdf.py` documents that PyMuPDF was *deliberately* rejected
  for being AGPL-3.0-or-commercial, "a real obligation for a deployed web application and not a
  decision that should be made by whoever happens to write the import."
  **The choice is deliberately reversible**: the renderer sits behind a boundary in
  `infrastructure/documents/`, and the six export assertions are stated renderer-independently
  (contracts/export.md), verified with `pdfplumber` rather than by the renderer itself. Replacing
  WeasyPrint must not require redesigning the export contract.

- **D4 — Chunking and citation granularity: resolved by later decisions.** No separate decision was
  needed in the end. The retrievable unit is one authored rule (**FR-037**, 1:1 with a chunk,
  qualifications embedded); the citation names `document_slug` + `document_version` +
  `content_hash` + `locator` + snapshotted `text` ([data-model.md](data-model.md),
  [contracts/guideline-retrieval.md](contracts/guideline-retrieval.md)). Content-addressed identity
  is what makes FR-012 achievable — unchanged rules keep their hash across re-ingestion, edited
  rules become new chunks. **Rejected: positional or offset-based citations**, which break on every
  re-ingestion, and **fixed-size overlapping windows**, which would split a rule from its condition.
- **D8 — Checksum: the rendered bytes, resolved by later decisions.** Constitution IV requires "an
  immutable snapshot with a **stable file checksum**" — *file*, meaning bytes. SHA-256 over the
  stored bytes, computed at export and re-verified at submission (R11, `checksum_sha256` in
  [data-model.md](data-model.md), **FR-031** for the determinism that makes it enforceable).
  **Rejected: checksumming content**, which would let two different files compare equal and defeat
  the purpose of proving what was sent.

---

---

## Open Decisions

**None remain.** All eight were resolved before implementation began.





---

## Out of Scope

- Company Research, web search, and MCP of any kind (slice 008).
- The evaluation harness, including retrieval-quality metrics (slice 007).
- Any change to model configuration, thinking parameters, prompts, or revision thresholds.
- User-uploaded guideline documents (D1, resolved: curated corpus only).
- Multiple PDF templates, theming, or a document designer.
- Retrieval over anything other than resume-writing guidance — notably profile content, which
  Constitution VI forbids embedding.
