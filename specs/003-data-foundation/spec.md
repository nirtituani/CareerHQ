# Feature Specification: Data Foundation

**Feature Branch**: `003-data-foundation`

**Created**: 2026-08-13

**Status**: Draft

**Input**: Slice 003 per [docs/05_Implementation_Plan.md](../../docs/05_Implementation_Plan.md) §5.3 — CV import and parsing into a structured Professional Profile, an initial Master Resume, and a minimal Application entity holding jobs and their descriptions, seeded from JobTracker.

## Why This Slice Exists

The slice 004 tailoring agent needs two things that do not exist yet: **a structured profile to
tailor**, and **a job description to tailor against**. This slice produces both.

Nothing here requires an agent *loop*, and that is a scope guard rather than an observation: if a
task needs a multi-step LLM workflow, it belongs in 004.

One decision qualifies that guard rather than breaking it. CV extraction is performed by a
**single structured-output LLM call executed through an AI Gateway seam** (Q1, resolved). One typed
call with a validated schema is not an agent loop: there is no planning, no tool use, no
self-critique and no iteration. The guard still holds — anything needing those belongs in 004.

Two consequences follow and are treated as requirements rather than side effects. Principle V
means the call cannot originate in the Professional domain, so the seam this slice introduces is
the one slice 004 builds on rather than invents. And `docs/05` §5.3 describes 003 as "the last
purely deterministic work before the flagship"; that line is now inaccurate and must be amended
there, not quietly contradicted here.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reach a populated profile without retyping a career history (Priority: P1)

A new user signs in and has an empty Professional Profile. They upload the CV they already have.
The system extracts what it can and shows it back as structured content — contact details, titles,
a summary, roles with individual bullets, skills, education, and the rest — with each item marked
as unverified extraction. The user corrects what is wrong, removes what does not belong, and
approves. Only then does any of it become profile data. Approving also produces an initial Master
Resume, so they have something to tailor from immediately.

**Why this priority**: It is the reason the slice exists. Without a populated profile there is
nothing for slice 004 to tailor, and manual entry of a full career history is what makes users
abandon this class of product before reaching value. This story alone is a viable MVP.

**Independent Test**: Upload a real CV as a signed-in user with an empty profile. Confirm the
extracted content is displayed for review *before* anything is stored, that corrections survive,
and that approval produces exactly one populated Professional Profile and one Master Resume.

**Acceptance Scenarios**:

1. **Given** a signed-in user with an empty profile, **When** they upload a PDF CV, **Then** the
   extracted content is displayed for review and **nothing has been written to the profile yet**
2. **Given** extracted content on screen, **When** the user corrects a field and approves,
   **Then** the corrected value is stored and the original extraction is not
3. **Given** an approved import, **When** the profile is read back, **Then** it contains exactly
   one Professional Profile for that user and one Master Resume derived from it
4. **Given** extracted content, **When** the user views any item, **Then** they can tell whether
   it was extracted or user-verified
5. **Given** a signed-in user, **When** they upload a file that is neither PDF nor DOCX,
   **Then** they are told what formats are accepted and nothing is stored
6. **Given** a user who abandons the review without approving, **When** they return,
   **Then** their profile is still empty — an unapproved import never becomes profile data

---

### User Story 2 - Record a job to tailor against (Priority: P2)

The user adds a job opportunity they care about: company, title, the job description text, and
where it came from. It can exist before any resume is submitted — a wishlist entry is a legitimate
state, not an incomplete one.

**Why this priority**: Slice 004 needs a job description to tailor against, and this is the
**only** path to one. Reading the JobTracker source (research R8) established that it has no job
description field at all — only `job_link` and `job_desc_link`, both URLs. So US3 cannot supply
tailoring inputs even in principle, and "US1 plus US2 is the smallest combination that unblocks the
flagship" is a fact about the source data rather than a judgement about priorities.

**Independent Test**: As a signed-in user, create an application with a job description and no
submitted resume. Confirm it persists, is visible only to that user, and is retrievable with its
description intact.

**Acceptance Scenarios**:

1. **Given** a signed-in user, **When** they add a job with a description, **Then** it is saved
   and appears in their application list
2. **Given** an application with no submitted resume, **When** its status is a pre-submission
   state, **Then** it is valid and no submitted resume is required
3. **Given** two different users, **When** each lists their applications, **Then** neither can see
   or retrieve the other's
4. **Given** an application, **When** its status changes, **Then** the change is recorded in an
   append-only history
5. **Given** an application in the list, **When** the user opens it, **Then** a detail view shows
   every stored field — including the full job description text, not a link to it
6. **Given** the detail view, **When** the user looks for analysis that later slices produce,
   **Then** the panels for it are present and visibly empty with an explanation, rather than
   absent — the view is the destination those slices fill

---

### User Story 3 - Arrive with existing history rather than an empty system (Priority: P3)

The user imports their real application history from JobTracker. Roughly twenty applications land
in the system, each with its company, status, dates, and notes — mapped onto CareerHQ's normalized
statuses rather than JobTracker's own representation.

**Why this priority**: It gives the slice 007 Career Advisor genuine history — statuses, dates and
outcomes — rather than waiting months for data to accumulate. It does **not** make the tailoring
demo realistic, which is what docs/05 §5.3 claimed: imported applications carry no job description
(R8), so nothing imported here can be tailored against. Valuable for history, and nothing
downstream is blocked without it.

**Independent Test**: Run the import against real JobTracker data and confirm the resulting
applications carry correct normalized statuses, that rejection is derived rather than stored
independently, and that re-running it does not duplicate anything.

**Acceptance Scenarios**:

1. **Given** JobTracker records, **When** they are imported, **Then** each becomes an application
   owned by the importing user with its status mapped to a normalized status
2. **Given** a JobTracker record marked rejected, **When** it is imported, **Then** rejection is
   represented by the normalized status and **no independent rejected flag is stored**
3. **Given** an import that has already run, **When** it is run again with the same data,
   **Then** no duplicate applications are created
4. **Given** records naming the same company, **When** they are imported, **Then** they reference
   one company record rather than several
5. **Given** a record that cannot be mapped, **When** the import runs, **Then** it is reported
   with enough detail to fix, and the remaining records still import
6. **Given** a record whose `rejected` flag is true but whose status is not `Rejected`, **When** it
   is imported, **Then** its original status is preserved as the label and its normalized status is
   `rejected` — recording both how far the application got and how it ended
7. **Given** a record with a status label CareerHQ does not recognise, **When** it is imported,
   **Then** the label is preserved, the normalized status is `other`, and the row is flagged for
   attention rather than rejected — JobTracker keeps custom statuses in browser storage, so
   unrecognised labels are expected rather than exceptional

---

### Edge Cases

- **A CV that extracts almost nothing** — a scanned image, a heavily designed two-column layout, a
  file that is technically a PDF but carries no text layer. The user must be told extraction
  failed rather than shown a near-empty form implying their CV was understood.
- **A CV in a language other than English**, or with dates in a non-obvious format.
- **A second import by a user who already has a populated profile.** Principle I allows exactly
  one Professional Profile per user, so this cannot create a second one.
- **A very large upload**, or one whose declared type does not match its contents.
- **Approval submitted twice** — a double-clicked approve must not produce two Master Resumes.
- **JobTracker data with a status label CareerHQ does not know**, or with a rejected flag that
  disagrees with its status field — the two contradicting each other is precisely why the flag
  must not survive.
- **A JobTracker record with no company**, or the same company spelled inconsistently.
- **Extraction that partially succeeds** — some sections recognised, others empty.

## Requirements *(mandatory)*

### Functional Requirements

**Import and extraction**

- **FR-001**: The system MUST accept an uploaded resume file in PDF or DOCX format, and MUST
  reject other formats with a message naming what is accepted (docs/01 FR-024)
- **FR-002**: The system MUST extract structured content from the uploaded file — contact
  information, professional titles, summary, work experience with individual bullets, skills,
  projects, education, certifications, and languages (docs/01 FR-025). Extraction is performed by a
  **single structured-output LLM call**, executed through the AI Gateway seam defined in FR-024
- **FR-003**: The system MUST present extracted content to the user for review, correction, and
  approval **before any of it becomes part of the Professional Profile** (docs/01 FR-026,
  Constitution II)
- **FR-004**: Extracted content MUST be marked with its source and confidence, so user-verified
  facts remain distinguishable from unverified extraction (docs/01 FR-027)
- **FR-005**: The system MUST create an initial Master Resume from the approved import, so the
  user has something to tailor from immediately (docs/01 FR-028)
- **FR-006**: The uploaded file MUST be retained for reference but MUST NOT be the source of truth
  for any downstream capability. No downstream feature reads the original file (docs/01 FR-029,
  ADR-013)
- **FR-007**: An import that is not approved MUST leave the Professional Profile unchanged
- **FR-008**: When extraction yields little or nothing, the system MUST say so explicitly rather
  than presenting an empty review form
- **FR-009**: A user MUST have exactly one Professional Profile. A subsequent import MUST be
  reviewed and merged into it under the same approval gate, and MUST NOT create a second profile
  or silently overwrite verified facts (Constitution I, II)

**Applications and job descriptions**

- **FR-010**: Users MUST be able to record a job opportunity with at least a company, a job title,
  and a job description
- **FR-011**: An application MUST be valid without a submitted resume while in a pre-submission
  status (docs/03 §5.2)
- **FR-012**: Every status change MUST be recorded in an append-only history (Constitution IV)
- **FR-013**: User-facing status labels MUST map to normalized analytics categories
- **FR-014**: Applications MUST reference exactly one company, and repeated references to the same
  company MUST resolve to one company record rather than duplicates
- **FR-030**: The system MUST provide an application detail view rendering every stored field,
  including the job description text in full. It MUST include **named, visibly empty slots** for
  the analysis later slices produce — job-requirement extraction and match score (slice 004/005)
  and company research (slice 006) — each explaining that the capability is not built yet.
  The slots MUST be empty in this slice: rendering stored data is deterministic, and producing
  that analysis is not (see Out of Scope)

**JobTracker import**

- **FR-015**: The system MUST import JobTracker application records into applications owned by the
  importing user, from an **export file the user uploads** (CSV or JSON) (Q2, resolved). The import
  MUST NOT require credentials for, or network access to, any other system
- **FR-016**: JobTracker's `rejected` boolean MUST NOT be stored as an independent source of
  truth. Rejection MUST be derived from the normalized status (docs/03 §14, Constitution
  Technology Constraints). **This is a release blocker if violated** — two sources of truth for
  one fact is the inconsistent-state class the constitution exists to prevent. The source system
  demonstrates the failure directly: its own dashboard counts rejections as
  `rejected IS TRUE OR status='Rejected'`, because the two fields can disagree (research R8)
- **FR-017**: Re-running the import with the same source data MUST NOT create duplicates
- **FR-018**: Records that cannot be mapped MUST be reported individually with enough detail to
  correct them, and MUST NOT prevent the remaining records from importing

**Ownership, integrity and operations**

- **FR-019**: Every entity created by this slice MUST be owned by exactly one user, and ownership
  MUST be derived from the session — no endpoint may accept a client-supplied user or profile
  identifier (project convention, Constitution I)
- **FR-020**: Business invariants introduced by this slice MUST be enforced in the database schema
  rather than only in application code, wherever a constraint can express them (project
  convention)
- **FR-021**: Retaining the uploaded file requires object storage, which is **not configured in
  the deployed environment** and is currently reported `not_configured` by readiness. This slice
  MUST provision and configure it as an explicit prerequisite, and readiness MUST report it
  healthy before FR-006 can be considered met
- **FR-022**: Any log record needed to diagnose an import failure in production MUST carry its
  detail in structured fields rather than in the log message text, because the deployed platform
  discards message text (slice 002 observation)
- **FR-023**: Import operations MUST NOT partially commit. A failed import MUST leave no
  half-populated profile or partially imported application set

**Extraction through the AI seam** — obligations that follow from Q1 rather than choices

- **FR-024**: Extraction MUST execute through an AI Gateway seam. The Professional domain MUST NOT
  call an AI provider directly, and MUST remain deterministic and provider-agnostic
  (Constitution V). This seam is the one slice 004 extends; it is introduced here deliberately so
  the flagship inherits a proven boundary rather than inventing one
- **FR-025**: LLM output MUST be validated against a structured-output schema before it is shown
  as extracted content. Output that fails validation MUST be treated as extraction failure
  (FR-008) — never partially accepted, and never shown as though it were understood
  (Constitution VI)
- **FR-026**: Every extraction MUST record the model used, its configuration, token usage and
  cost, so an extraction is auditable after the fact (Constitution V)
- **FR-027**: The extraction call MUST be substitutable in tests. The automated suite MUST run to
  completion without contacting an AI provider and without depending on nondeterministic output —
  a test that only passes when a live model answers is not a test of this system
- **FR-028**: AI provider credentials are a deployment prerequisite alongside object storage
  (FR-021). Their absence MUST be reported by readiness as `not_configured` and MUST fail at the
  point of use with a message naming the missing setting — never as a crash at startup, and never
  as a silent degradation to empty extraction
- **FR-029**: The extracted content MUST remain reviewable and correctable in full regardless of
  extraction quality (FR-003). No extracted value may bypass review on the grounds of high
  confidence — Principle II admits no confidence threshold

### Key Entities

- **Professional Profile**: The single source of truth for a user's professional information.
  Owns contact information, titles, summary blocks, work experience, experience bullets, skills,
  projects, education, certifications, courses, languages, and portfolio links. Exactly one per
  user. Only user-provided or user-approved information may become part of it.
- **Imported Resume**: An uploaded CV file plus the structured content extracted from it. A
  staging artifact, not profile data — it becomes profile content only on approval, and the file
  is never the source of truth for anything downstream.
- **Extraction Item**: A single extracted fact carrying its source and confidence, so unverified
  extraction stays distinguishable from a user-verified value.
- **Master Resume**: A career-focused view over the profile, created from the approved import.
  References profile facts rather than duplicating them. The domain entity is `ResumeProfile`
  (table `resume_profiles`, docs/03 §4.3); "Master Resume" is the user-facing name for the one
  marked `is_master`. Both terms appear across these documents and mean the same thing.
- **Application**: One tracked employment opportunity — company, job title, job description,
  dates, current status, normalized status category, append-only status history, source, notes.
  May exist before any resume is submitted.
- **Company**: An organization associated with one or more applications. Deduplicated, so repeated
  references resolve to one record.
- **Application Status**: A user-facing label mapped to a normalized analytics category.
  Rejection is one such normalized status, never an independent flag.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with an existing CV reaches a populated, reviewed profile in **under 10
  minutes** without retyping their career history
- **SC-002**: For a typical single-column CV, **at least 80% of work-experience bullets** are
  extracted and attributed to the correct role, so review is correction rather than re-entry
- **SC-003**: **100% of extracted content passes through review** before becoming profile data —
  measured by confirming that an abandoned import leaves the profile empty
- **SC-004**: After approval the user has exactly **one** Professional Profile and **one** Master
  Resume — never two, including when approval is submitted twice
- **SC-005**: Importing real JobTracker data produces applications whose normalized statuses match
  the source for **100% of successfully imported records**, with rejection derived and **zero**
  independently stored rejected flags
- **SC-006**: Re-running the JobTracker import produces **zero** duplicate applications and zero
  duplicate companies
- **SC-007**: A user can record a job opportunity with its description in **under 2 minutes**
- **SC-008**: No user can retrieve another user's profile, application, or uploaded file — every
  non-public route rejects unauthenticated access, verified by enumerating routes
- **SC-009**: A failed or abandoned import leaves **no** partial data behind
- **SC-010**: Slice 004 can begin with a real profile and a real job description present in the
  deployed system — the concrete definition of this slice being done

## Resolved Decisions

Both were genuine scope decisions touching a constitutional principle, so they were asked rather
than assumed. Recorded with their reasoning so slice 004 inherits the decision instead of
re-deriving it.

### D1: CV extraction is a single structured-output LLM call behind an AI Gateway seam

**Rejected**: deterministic parsing only, and deterministic text with user-assigned structure.

A PDF carries no semantic structure — two-column layouts interleave text, bullets lose the role
they belong to, and date formats vary without limit. Deterministic parsing would have forced
SC-002's 80% target down, which means weakening the feature rather than fixing it, and would
likely have been rebuilt with an LLM in slice 004 anyway.

The decisive argument is that **the approval gate already exists**. The standard objection to a
model touching professional data is fabrication, and Principle II already requires a human to
review every extracted item before it becomes profile data. The LLM is being introduced at the one
point in the system where its output is checked by a person before it counts for anything.

Constraints this carries: the call goes through a gateway seam and never originates in the
Professional domain (FR-024); output is schema-validated or treated as failure (FR-025); model,
tokens and cost are recorded (FR-026); the suite runs without a provider (FR-027); credentials are
a deployment prerequisite reported by readiness (FR-028).

**Databricks was considered and rejected as a slice 003 concern.** It is a lakehouse and analytics
platform — the wrong shape for parsing one document on upload — and it cannot run in the Compose
stack the constitution requires every service to run in. If Databricks-hosted models are wanted
later, LiteLLM supports Databricks as a provider, so it becomes one line of gateway configuration
behind FR-024 rather than an architectural change. That is what Principle V means by providers
being swappable via configuration.

### D2: JobTracker data arrives as a user-uploaded export file

**Rejected**: a migration script against the JobTracker database, and building both.

A file upload needs no credentials for another system, introduces no network coupling, and is
testable from a fixture. It is also the version that is a product capability rather than operator
tooling — docs/03 §14 maps "Data import" to an Import Service, and an Import Service that only the
author can run against their own database is not that.

The cost is that JobTracker must have an export, or one must be produced by hand once. That is a
known, bounded task rather than an open dependency.

## Assumptions

Recorded because the description did not specify them and a reasonable default exists.

- **Object storage becomes a deployment prerequisite.** FR-006 requires retaining the uploaded
  file and the deployed environment has none. This slice provisions it rather than dropping
  retention; FR-021 makes that explicit rather than letting it be discovered at runtime.
- **A second import merges under approval rather than replacing.** Principle I permits exactly one
  profile per user and Principle II forbids unapproved modification, so re-import is reviewed
  item by item and never silently overwrites a verified fact.
- **Extraction confidence is per item, not per document.** FR-004 is only useful in review if the
  user can see which individual values are doubtful.
- **The review step is a first-class interface, not a JSON dump.** It was certain work under every
  option considered in D1, and remains the control that makes an LLM acceptable here at all.
- **A single typed LLM call is not an agent loop.** No planning, no tool use, no self-critique, no
  iteration. That distinction is what keeps D1 inside the scope guard rather than through it, and
  it is the line to hold if the slice starts growing.
- **No agent loop, no vector retrieval and no embeddings in this slice.** Semantic retrieval
  arrives with the Knowledge Context in slice 004. Structured profile facts are retrieved
  relationally (docs/03 §7.5) — embedding them and asking a model to retrieve them produces
  approximate answers to questions the database answers exactly.
- **Statuses are seeded from JobTracker's normalized set**, extended only where the source data
  demands it.
- **Existing authentication and per-user isolation are reused** from slice 001 unchanged.

## Out of Scope

Stated so the slice cannot drift into the flagship.

- Any LangGraph workflow, self-critique, Reviewer, or multi-step agent loop — slice 004. The
  single extraction call of FR-024 is the **only** model call in this slice; a second one, or any
  iteration over the first, is slice 004 work arriving early
- **Summarizing a job description, or extracting its requirements** — that is slice 004's
  "Analyze Job Description" node, and doing it here would be the second model call the line above
  forbids. FR-030's detail view holds the slot; slice 004 fills it
- **Fetching a job description from its URL.** JobTracker stores `job_desc_link`, and retrieving
  it would turn imported applications into tailorable ones — but postings expire, the major boards
  block automated fetching, and web retrieval belongs to slice 006, where it runs over an MCP and
  produces citation-preserving snapshots. The best-targeted version, if wanted later, is an
  on-demand fetch for `Pre-Applied` rows, whose postings are most likely still live and which are
  exactly the ones worth tailoring for
- Tailoring a resume to a job description, diffing, or item-level approval of AI output — slice 004
- Embeddings, chunking, pgvector retrieval, or the Knowledge Context — slice 004
- PDF export of a resume, and the Submitted Resume immutability path — slice 004
- The from-scratch resume builder and presentation designer (ADR-013, docs/05 §7)
- Company research and the Career Advisor — slices 006 and 007
