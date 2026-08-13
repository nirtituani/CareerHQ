# Phase 0 Research: Data Foundation

Decisions taken before design, each with what was rejected and why. Package versions were
verified against PyPI rather than recalled — CLAUDE.md records nine version guesses in this
project that turned out not to exist.

---

## R1 — The AI Gateway seam (FR-024). The highest-risk decision in this slice

**Decision**: a `Protocol` declared in the application layer and implemented in `infrastructure/`
by a LiteLLM adapter. The seam is a **typed, task-named, structured completion** — not a generic
`chat(prompt) -> str`.

```
StructuredCompletion.complete(task=..., schema=<PydanticModel>, prompt=..., ) -> Completion[T]
                                                                                  .value: T
                                                                                  .usage: model, tokens, cost
```

Four properties make it the right shape, and each maps to a requirement rather than a preference:

1. **`schema` is required, and the return is typed.** There is no way to call this seam and get
   unvalidated text back, so FR-025 and Principle VI are structural rather than remembered.
2. **`task` is a name, not a model.** Model choice resolves from configuration keyed by task —
   `cv_extraction` here. This is precisely how slice 004 expresses docs/08 §3.2.3's per-node
   mapping (Sonnet to analyze/draft/revise, Opus for the Reviewer and for a second-attempt
   revision): each node is a task name, and the escalation on a failed revision is a second task
   name rather than a branch inside business code. Had the seam taken a model identifier, every
   caller would hardcode a model and §3.2.3 would live scattered across the workflow.
3. **`usage` is returned, not logged internally.** The application layer records it (FR-026), so
   infrastructure stays dumb and the audit trail is written where the transaction is.
4. **It is a Protocol, so `domain/` and `application/` import no provider code.** Principle V's
   "Business Domains MUST NOT call AI providers" becomes a fact about imports, which is the same
   mechanism already keeping `domain/` free of framework code.

**Rejected**: a generic `chat()` returning text — pushes parsing and validation to every caller
and makes FR-025 a convention. Calling LiteLLM directly from the application layer — violates
Principle V outright. Passing a model identifier per call — scatters §3.2.3 and makes the slice
004 escalation a business-code branch.

**Gateway**: LiteLLM `1.96.2`, already fixed by docs/06 §7 as the AI Gateway. The application
speaks only to LiteLLM; providers stay replaceable by configuration.

## R2 — Test seam for FR-027

**Decision**: a FastAPI dependency override, reusing the pattern slice 001 established for
`get_verified_google_claims`, whose docstring already calls itself "**the seam**". Tests override
the provider dependency with a fake returning canned structured values.

That precedent matters more than novelty here: the OAuth seam let slice 001 exercise the entire
sign-in flow with only the network call to Google removed, and it is the reason those tests are
deterministic. The same shape gives the same property for extraction. The suite then runs with no
API key, no network, and no nondeterministic output — which is what FR-027 requires.

**Rejected**: recording and replaying real provider responses (cassettes drift silently from the
provider and pass long after the integration has broken); monkeypatching the LiteLLM module
(couples tests to a third party's internals rather than to our own boundary).

## R3 — What happens locally with no API key

docs/06 §7 commits to a property worth protecting: "**the stack runs with no API key** … `docker
compose up` works on a clean clone before any provider account exists, which is what keeps the
quickstart honest." CV extraction needs a provider, so this slice is the first to strain it.

**Decision**, three distinct behaviours rather than one compromise:

| Context | Behaviour |
|---|---|
| No provider configured | Readiness reports `ai_provider: not_configured`; the import endpoint fails at the point of use naming the missing setting (FR-028). It does **not** crash at startup and does **not** degrade to empty extraction |
| Automated tests | Dependency override with a fake (R2). No key, no network |
| Explicit local demo | `AI_PROVIDER=fixture` returns canned structured content, **labelled in the response as fixture data**. Never the default, never silently selected |

The fixture mode is opt-in precisely because the alternative is worse: silently returning canned
data when a key is absent would mean a user uploads their real CV and reviews someone else's
career history. FR-008 already requires the system to say when extraction produced nothing —
inventing content instead is the same failure wearing a better mask.

**Consequence to state plainly**: the quickstart's import walkthrough needs either a real API key
or `AI_PROVIDER=fixture`. `docker compose up` still works on a clean clone; the import is the
part that asks for something.

## R4 — Text extraction from PDF and DOCX

**Decision**: `pdfplumber 0.11.10` (MIT) for PDF, `python-docx 1.2.0` (MIT) for DOCX. Both
verified present on PyPI at those versions.

The job here is only to recover text faithfully — the LLM does the structuring (D1) — so
layout-reconstruction sophistication buys little.

**Rejected**: **PyMuPDF 1.28.2**, which is the best extractor of the three and is **dual-licensed
AGPL-3.0 or commercial**. AGPL is a real obligation for anything network-served, and this is a
deployed web application. That is a licensing decision, not a technical one, and it should not be
made accidentally by whoever writes the import. `pypdf 6.15.0` is lighter and permissively
licensed but recovers multi-column text noticeably worse, which would degrade the input the model
reasons over.

## R5 — Object storage for FR-021

**Decision**: a **Railway native bucket** (`railway bucket create`), with S3-compatible
credentials from `railway bucket credentials` filling the existing `S3_*` settings.

Verified: the Railway CLI exposes `bucket create|list|credentials|info`, and the project currently
has **no bucket** in `production` — so this is real work, not a check-the-box.

This needs **no application code change**: `infrastructure/storage.py` already speaks S3 through
boto3, and slice 002 already made the `S3_*` settings optional with
`object_storage_configured` driving readiness. Configuring them flips the dependency from
`not_configured` to probed, through a path that already has tests.

**Rejected**: deploying MinIO as a fourth Railway service — a whole service, volume and upgrade
path to operate for one bucket. External S3 or R2 — another vendor and another credential set,
for no gain over a bucket in the project that already exists.

**To verify during implementation**: the endpoint URL form Railway issues, and whether path-style
addressing is required. `storage.py` passes `endpoint_url` already, so this is configuration.

## R6 — Atomicity for FR-023

**Decision**: one transaction per import operation, committed once at the route boundary — the
pattern `provision_user` already uses. Approval writes the profile, its child records and the
Master Resume in a single transaction; the JobTracker import writes all accepted rows in one.

FR-018 (unmappable rows reported, the rest still imported) is not in tension with this: rows are
validated and partitioned **before** the transaction opens, so the transaction contains only rows
already known to be mappable. Rejected rows never enter it.

**Rejected**: per-row commits, which produce exactly the half-populated state FR-023 forbids.

## R7 — Which invariants become schema constraints (FR-020)

| Invariant | Constraint | Why not application code |
|---|---|---|
| One Professional Profile per user | `UNIQUE (user_id)` — **already exists** from slice 001 | Principle I; a race would create two |
| One company per user per normalized name | `UNIQUE (user_id, normalized_name)` | FR-014, and it is what makes import dedup correct under retry |
| JobTracker import idempotency | `UNIQUE (user_id, source, source_record_id)` | FR-017. A re-run inserts conflicting rows and the database refuses; an application check has to read-then-write and can be raced |
| One Master Resume per profile at creation | `UNIQUE (profile_id) WHERE is_master` (partial index) | FR-005 and SC-004 — a double-clicked approve must not produce two |
| An application belongs to exactly one company | `FOREIGN KEY`, `NOT NULL` | FR-014 |
| Status history is append-only | Insert-only table, **no update or delete path in code**, plus a test asserting none exists | Constitution IV. A trigger is available if it later needs enforcing against direct SQL |

**Rejection is derived, never stored** (FR-016): there is no `rejected` column anywhere in the
schema. Rejection is a value of the normalized status. This is the one constraint whose violation
is a release blocker, so its absence is the thing to check in review — a column that does not
exist cannot fall out of sync with the status that does.

## R8 — JobTracker export shape: **resolved from the source**

**Status: resolved.** `nirtituani/job-tracker-web` was read directly. The mapping below is written
against the actual schema rather than a guess.

### The source schema

Flask over raw SQL. One table, `applications`, with three columns added later by `ALTER TABLE`
(hence their position at the end — the export is `SELECT *`, so column order matters):

```
id, user_id, company, title, location, date_applied, status, salary_range,
job_link, contact_person, contact_email, applied_via, match_rating, notes,
last_updated, job_desc_link, rejected, company_domain
```

`GET /api/export` writes exactly these columns as a CSV header, so the export format is the table
definition. D2's file upload has a known shape.

### Finding 1 — the `rejected` flag is a live inconsistency, not a hypothetical one

FR-016 forbids importing `rejected` as an independent source of truth. The source confirms why in
its own dashboard query:

```sql
SELECT COUNT(*) FROM applications
 WHERE user_id=:uid AND (rejected IS TRUE OR status='Rejected')
```

It **ORs the boolean with the status** because the two can disagree, and the active-applications
query has to defend the same way (`status NOT IN (...) AND (rejected IS NOT TRUE)`). Two fields
encoding one fact, reconciled at every read site. This is the exact failure docs/03 §14 anticipated.

**The reconciliation rule**, which loses nothing:

| Source | CareerHQ label | CareerHQ normalized |
|---|---|---|
| `status = 'Rejected'` | `Rejected` | `rejected` |
| `rejected IS TRUE`, status anything else | **the original status preserved** | `rejected` |
| otherwise | the status | derived from the status |

Row 2 is the interesting one. `rejected=true, status='Interview Round 2'` becomes the label
"Interview Round 2" with normalized status `rejected` — the label records *how far they got*, the
normalized status records *the outcome*. That is strictly **more** information than JobTracker
could express, obtained by removing a field rather than adding one.

### Finding 2 — JobTracker has no job description text. At all

`grep -c description backend/app.py` → **0**. There is only `job_link` and `job_desc_link`, both
URLs. Imported applications therefore arrive **without anything for slice 004 to tailor against**.

This promotes a plan assumption to a fact: "US1 + US2 is the smallest combination that unblocks
slice 004" is not a judgment call — US3 *cannot* unblock it, because the data does not exist in the
source. The spec and docs/05 both need to say so, since docs/05 §5.3's stated benefit of the import
("makes the tailoring demo realistic") is only half right: it supplies **history** for the slice 007
Career Advisor, not tailoring inputs.

### Finding 3 — statuses and source options live in `localStorage`, not the database

`useSettings.js` keeps the vocabulary in the browser:

```
Pre-Applied, Applied, Online Assessment, Phone Screen, Interview Round 1,
Interview Round 2, Interview Round 3, Final Interview, Offer Received,
Rejected, Ghosted, Withdrawn
```

Because they are client-side, a user's **customised** statuses never reach the database — but the
strings they produced are in `applications.status`. An export can therefore contain any label at
all, and for anyone who customised, it will.

So an unrecognised status is the **common case, not an edge case**. It must not reject the row:
the label is preserved verbatim, the normalized status falls back to `other`, and the row is listed
in the import report as needing attention. FR-018's "cannot be mapped" is reserved for rows missing
something structural — a company or title — not for an unfamiliar label.

### Finding 4 — dates are day-first text

Written as `%d/%m/%Y %H:%M` and stored as `TEXT`. `03/04/2026` is **3 April**, not 4 March. Parsed
day-first explicitly; an ambiguous or unparseable value is preserved raw and reported rather than
silently guessed, because a wrong date is worse than an absent one for a Career Advisor reasoning
over timelines.

### The mapping

| JobTracker | CareerHQ | Note |
|---|---|---|
| `id` | `import_source_id` (with `import_source='jobtracker'`) | The idempotency key for constraint C3 |
| `user_id` | **discarded** | Ownership comes from the session (FR-019). Importing a foreign user id is exactly the vulnerability that rule exists to prevent |
| `company`, `company_domain` | `Company.name` / `.domain` | Deduplicated by `normalized_name` (C2) |
| `title`, `location`, `notes` | direct | |
| `date_applied`, `last_updated` | parsed day-first | Finding 4 |
| `status` + `rejected` | `status` label + `normalized_status` | Finding 1. **No `rejected` column is created** |
| `salary_range` | `salary_text` — **free text** | Not min/max/currency. `"90-110k"`, `"competitive"` and `""` all occur; parsing it into numbers would invent precision |
| `job_link`, `job_desc_link` | `job_url`, `job_description_url` | Both URLs. Neither is a description (Finding 2) |
| `contact_person`, `contact_email` | `contact_name`, `contact_email` | |
| `applied_via` | `source` | Also localStorage-customisable — same treatment as status |
| `match_rating` | preserved as `imported_match_rating` | Integer, `0` meaning unset. Kept rather than dropped so slice 004's MatchAnalysis (docs/03 §14) can build on real data; discarding a user's own ratings on import would be silent data loss |

## R9 — No embeddings, no vector retrieval

**Decision**: none in this slice. Structured profile facts are retrieved relationally
(docs/03 §7.5). Embedding them and asking a model to retrieve them yields approximate answers to
questions the database answers exactly. The Knowledge Context, chunking and pgvector retrieval
arrive with slice 004.

The `vector` extension is already installed (migration `0001_extensions`), so nothing is blocked
later by deferring it now.
