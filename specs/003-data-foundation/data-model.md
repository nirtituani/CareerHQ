# Phase 1 Data Model: Data Foundation

Entities this slice adds, and the constraints that make its invariants unraceable. Existing
entities from slice 001 (`User`, `ProfessionalProfile`) are unchanged.

The governing convention, from CLAUDE.md and already stated in `domain/models.py`: *a check in
Python can be raced, forgotten by the next endpoint, or bypassed by a migration script; a UNIQUE
constraint cannot.*

---

## 1. Staging — content that is not yet profile data

The whole point of these two entities is that they are **not** the profile. They hold what
extraction produced until a human approves it (FR-003, FR-007, Principle II).

### ImportedResume

One upload and its extraction attempt.

| Field | Notes |
|---|---|
| `id` | |
| `user_id` | FK → `users`, NOT NULL. Ownership from the session, never the request (FR-019) |
| `storage_key` | Object-storage key for the retained original (FR-006). Not read by any downstream feature |
| `filename`, `content_type`, `byte_size` | As uploaded; `content_type` verified against content, not trusted |
| `status` | `pending` → `extracted` \| `failed` → `approved` \| `discarded` |
| `extraction_error` | Set when extraction failed or produced nothing (FR-008) |
| `model`, `input_tokens`, `output_tokens`, `cost` | The audit record Principle V requires (FR-026) |
| `is_fixture` | True when produced by fixture mode, so labelled data can never be mistaken for real extraction (R3) |
| `created_at` | |

### ExtractionItem

One extracted fact, carrying provenance. This is what the review interface renders.

| Field | Notes |
|---|---|
| `id`, `imported_resume_id` | FK, NOT NULL, cascade delete |
| `kind` | Which profile entity it becomes — `work_experience`, `bullet`, `skill`, … |
| `payload` | The structured value, schema-validated before it was stored (FR-025) |
| `confidence` | Per item, not per document — review is only useful if the doubtful values are identifiable |
| `source` | `extracted` \| `user_corrected` \| `user_added`. FR-004's distinction, kept after approval |
| `decision` | `pending` \| `accepted` \| `discarded` — the user's choice |
| `ordinal` | Preserves CV order so review reads like the source document |

**No confidence threshold auto-accepts anything** (FR-029). `decision` defaults to `pending`
regardless of `confidence`; a high score changes what the interface *suggests*, never what it
*does*.

---

## 2. Professional content — created only on approval

Children of `ProfessionalProfile`, populated from accepted `ExtractionItem`s in one transaction.

- **WorkExperience** — company name, title, location, start/end, `is_current`
- **ExperienceBullet** — FK → `WorkExperience`, text, ordinal. Separate rows because slice 004
  tailors, approves and diffs at bullet granularity; a text blob would make item-level approval
  impossible
- **Skill** — name, category, optional proficiency
- **Education**, **Certification**, **Project**, **Language** — as docs/03 §4.6
- **ContactInformation**, **ProfessionalTitle**, **SummaryBlock** — as docs/03 §4.6

Every one carries `source` (`extracted` | `user_corrected` | `user_added`), so FR-004's
distinction survives into the profile rather than being discarded at approval.

### ResumeProfile (the Master Resume)

A career-focused view created from the approved import (FR-005). It **references** profile facts
and does not duplicate them (Principle I, docs/03 §4.3).

| Field | Notes |
|---|---|
| `id`, `profile_id` | FK → `professional_profiles`, NOT NULL |
| `name` | "Master Resume" initially |
| `is_master` | Exactly one per profile — see C4 |

---

## 3. Applications

### Company

| Field | Notes |
|---|---|
| `id`, `user_id` | Companies are per user; two users naming the same employer own separate rows |
| `name` | As entered |
| `normalized_name` | Lowercased, trimmed, punctuation folded — the dedup key (C2) |
| `domain`, `careers_url`, `notes` | Optional |

### Application

| Field | Notes |
|---|---|
| `id`, `user_id` | FK, NOT NULL (FR-019) |
| `company_id` | FK, NOT NULL — exactly one company (FR-014) |
| `job_title`, `location` | |
| `job_description` | The text slice 004 tailors against — the reason US2 exists |
| `job_url`, `job_description_url` | Optional |
| `status` | User-facing label |
| `normalized_status` | The analytics category (FR-013) |
| `date_added`, `date_applied` | |
| `source` | How it was applied for |
| `salary_min`, `salary_max`, `salary_currency` | Optional |
| `contact_name`, `contact_email` | Optional |
| `notes` | |
| `import_source`, `import_source_id` | Provenance for idempotency (C3). NULL for manual entries |
| `archived_at` | Nullable; history survives archiving |

**There is no `rejected` column.** Rejection is a value of `normalized_status` (FR-016,
docs/03 §14). A column that does not exist cannot drift out of sync with the status that does.
This is the release-blocking invariant, and its enforcement is an **absence** — which is why the
review question is "does a rejected flag exist anywhere?" rather than "is it kept in sync?".

There is deliberately **no `submitted_resume_id`** either: Submitted Resumes arrive in slice 004,
and an application in a pre-submission status must be valid without one (FR-011).

### ApplicationStatusHistory

Insert-only (Constitution IV, FR-012).

| Field | Notes |
|---|---|
| `id`, `application_id` | FK, NOT NULL |
| `from_status`, `to_status`, `normalized_to_status` | |
| `changed_at`, `note` | |

---

## 4. Constraints (FR-020)

Each is a database constraint because the application-level equivalent can be raced or forgotten.

| | Constraint | Enforces |
|---|---|---|
| **C1** | `UNIQUE (user_id)` on `professional_profiles` — *already exists* | Principle I, FR-009. One profile per user |
| **C2** | `UNIQUE (user_id, normalized_name)` on `companies` | FR-014. Also what makes import dedup correct under concurrent retry |
| **C3** | `UNIQUE (user_id, import_source, import_source_id)` on `applications`, partial `WHERE import_source IS NOT NULL` | FR-017. Re-running the import conflicts and the database refuses. An application-level check must read-then-write and can be raced |
| **C4** | `UNIQUE (profile_id) WHERE is_master` on `resume_profiles` | FR-005, SC-004. A double-clicked approve cannot create two Master Resumes |
| **C5** | `FOREIGN KEY` + `NOT NULL` on every `user_id` and owner reference | FR-019. Orphaned or unowned rows are unrepresentable |
| **C6** | No update or delete path to `application_status_history`, plus a test asserting none exists | Constitution IV. A trigger remains available if it later needs enforcing against direct SQL |

**C3 is the one to write a test for first.** Idempotency is the requirement most likely to be
quietly satisfied in the happy path and broken under retry, and a `UNIQUE` violation surfacing as
a clean "already imported" is the difference between a correct importer and one that looks correct.

---

## 5. State transitions

**ImportedResume**

```
pending ──extract──> extracted ──approve──> approved
   │                     │
   └──fail──> failed     └──discard──> discarded
```

`approved` is terminal and is the only transition that writes profile data. `failed` carries
`extraction_error` and is shown as a failure, never as an empty review form (FR-008).

**Application** — user-defined labels mapped to normalized categories (FR-013); every transition
writes a history row (FR-012). Rejection is one of those normalized categories and nothing else.

---

## 6. What this slice deliberately does not model

- **SubmittedResume, ResumeVersion, and immutability locking** — slice 004
- **Embeddings, chunks, or any vector column** — slice 004 (R9). The `vector` extension is already
  installed, so nothing is blocked by deferring it
- **MatchAnalysis, company research, recommendations** — slices 004 and 006
