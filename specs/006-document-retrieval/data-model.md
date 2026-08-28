# Data Model: Document & Retrieval (Phase 1)

Schema deltas only. Existing entities are named where this slice touches them.

---

## Knowledge Context

Adopts the names `docs/03` §7 already defines — `KnowledgeDocument`, `KnowledgeChunk`,
`ChunkMetadata` — rather than inventing parallel ones. Two fields the domain model does **not**
currently have are added, both surfaced by the corpus research.

### `KnowledgeDocument`

One authored corpus file. Curated only in V1 (R1).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `slug` | str, unique | Stable natural key from the filename, e.g. `israel-personal-details` |
| `source_type` | enum | `resume_best_practices`, `ats_guidelines`, `domain_specific`, `seniority`, `integrity`, `israel_market` |
| `title` | str | |
| `version` | int | Bumped on content change; prior citations stay resolvable (FR-012) |
| `market` | enum | **NEW dimension** — `global` \| `israel` (semantics below). No field for this exists today |
| `trust_level` | enum | **NEW, values defined** (below) |
| `origin_source_ids` | str[] | Register IDs (`S-002`, …) this document's rules derive from |
| `is_active` | bool | Archived documents are excluded from retrieval |
| `created_at` / `updated_at` | timestamptz | |

**`trust_level` values** — previously undefined in `docs/03`:

| Value | Meaning |
|---|---|
| `internal` | CareerHQ-authored product rule. Integrity rules are **always** this |
| `institutional` | Derived from a government, academic or equivalent body (S-001, S-002) |
| `vendor_documented` | Derived from a vendor documenting its own product (S-006/7/8) |
| `industry` | Credible industry practitioner or publisher |

Community and SEO-tier material does not reach the corpus at all, so has no value here.

**`market` values — semantics are load-bearing and must not be inferred** (FR-038):

| Value | Means | Does **not** mean |
|---|---|---|
| `global` | The supporting **evidence** is global | ❌ *Not applicable to Israel.* Global guidance remains applicable to Israeli-market CVs |
| `israel` | The evidence specifically supports the Israeli market | — |

**Precedence.** Where authoritative Israeli evidence conflicts with global guidance, the Israeli
guidance takes precedence **for Israeli-market CVs**. Absent such a conflict, global guidance
stands. No Israeli distinction is manufactured where evidence does not support one.

**Why this is written down.** ATS rules ship `market: global` because every ATS source found is a
global vendor or a US university career centre (R12). That records the *evidentiary* claim only —
reading it as "ATS guidance does not apply in Israel" would be wrong and would suppress correct
guidance for exactly the users this product targets.

### `KnowledgeChunk`

One authored rule. **A rule and a chunk are 1:1 by design in Corpus V1** (FR-037), and a rule's **qualifications and exceptions are part of its own text** (R5) — never a sibling chunk.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `document_id` | UUID FK | |
| `content_hash` | char(64), unique per document | SHA-256 of normalised text — the citation identity |
| `text` | text | The rule *including* its conditions |
| `chunk_order` | int | Position within the document |
| `token_count` | int | Enables the FR-014 budget to be enforced without re-tokenising |
| `embedding` | `vector(384)` | MiniLM-L6-v2 (R4). Dimension is a schema commitment |
| `metadata` | jsonb | `ChunkMetadata` below |
| `created_at` | timestamptz | |

**`ChunkMetadata`** — the subset of `docs/03` §7.4 that an authored corpus can actually fill,
plus the market dimension: `market`, `trust_level`, `role_family` (or `any`), `seniority` (or
`any`), `resume_section`, `source_title`, `source_type`, `origin_source_ids`.

`docs/03` §7.4 is a **"may contain"** menu of fourteen fields written before this slice existed,
several of which do not apply here at all — `User ID`, `Company ID` and `Application ID` describe a
per-user corpus that D1 explicitly rejected, and `Publication date` / `Retrieval date` describe
ingested third-party material rather than rules CareerHQ authored. It is a superset to draw from,
never a contract.

**Two fields this enumeration named and no longer does (T025):**

- **`source_url` — removed.** An authored rule has no URL; the rule is ours and the URL belongs to
  the evidence it derives from. Unfillable rather than merely empty: a document may cite several
  sources at once (`ats-fields-and-sections` cites three vendors, so a scalar cannot hold them),
  **22 of 79 rules are product judgement with no register entry**, and S-018's register entry
  carries a file path rather than a URL. `origin_source_ids` is the resolvable pointer and the
  source register resolves it.
- **`topic` — deferred to T027**, which owns the market-precedence rule that is its only consumer.
  See *Precedence* above.

Neither field appears in the citation model below, in
[contracts/guideline-retrieval.md](contracts/guideline-retrieval.md), or in any consumer. Nothing
reads chunk metadata today.

**Invariants**
- Every chunk belongs to exactly one document.
- A chunk's text must be self-contained: retrievable and correct **without** its siblings.
- Re-ingestion of unchanged text reuses `content_hash`; edited text becomes a new chunk.
- No profile content is ever embedded (Constitution VI, ADR-008).

### Recorded citation

Persisted per run, extending what `tailoring_runs.guidelines_used` already stores:

`{document_slug, document_version, content_hash, locator, text, market, trust_level}`

*(Corrected 2026-08-28: this line said `chunk_hash`, a name that exists nowhere else. The column,
the unique constraint, the loader, `RetrievedGuideline` and
[contracts/guideline-retrieval.md](contracts/guideline-retrieval.md) all say **`content_hash`**.
A prose restatement of a schema, drifted. No code or schema changed — only this name.)*

`text` is snapshotted — the same pattern `ResumeVersionItem.original_text` already uses, so a later
corpus edit cannot rewrite what a past run was advised.

---

## Export and submission

### `VersionStatus` — amend

Add `EXPORTED` and `SUBMITTED`, which the enum's own docstring reserved for this slice.

```
DRAFT → REVIEWING → AWAITING_APPROVAL → APPROVED → EXPORTED → SUBMITTED
```

Terminal: `SUBMITTED`. No transition leaves it.

### `SubmittedResume` — new, insert-only

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `resume_version_id` | UUID FK, unique | One submission per version |
| `application_id` | UUID FK | Satisfies Constitution IV's Applied-or-later requirement |
| `storage_key` | str | Object-storage locator for the rendered bytes |
| `checksum_sha256` | char(64) | Over the **stored bytes** (R11) |
| `byte_size` | int | |
| `submitted_at` | timestamptz | |

**Invariants**
- Insert-only. No `UPDATE` path exists; modification attempts are refused explicitly, not ignored.
- Immutable under later profile or version change (FR-023).
- An application in `Applied` or later references one (FR-024, Constitution IV).
- Revising after submission creates a **new version** (FR-025).

### `ExportedDocument`

Recorded at export, before submission: `resume_version_id`, `storage_key`, `checksum_sha256`,
`exported_at`. Submission promotes an existing export rather than re-rendering, so the checksum
travels rather than being recomputed over different bytes.

---

## What is deliberately absent

- **No per-user corpus tables.** D1 resolved to a single curated corpus.
- **No `section` on the retrieval query.** D2 keeps one query per run; the field stays unused.
- **No embedding of profile, application or version data.** Constitution VI.
- **No demonstrative-example entity in V1.** Before/After examples remain research artifacts;
  representing them requires a before/after/transformation triple, which is a different shape and
  a separate decision.
