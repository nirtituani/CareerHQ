# Corpus Research Workspace — Slice 006

**Status: research only. Nothing here is corpus content, and nothing here has been ingested.**

This directory is the durable home for the decision *"what knowledge should the Slice 006 RAG
corpus contain?"* — a product and content question that must be answered before the retrieval
architecture is planned, so the design follows the real corpus rather than generic RAG practice.

## What lives here

| File | Purpose |
|---|---|
| `README.md` | This file — vocabularies, conventions, and what is forbidden |
| `source-register.md` | **The canonical register of every candidate source.** Append-only |

## What this workspace is *not*

- Not the corpus. No rule text is authored here.
- Not ingested. No embedding, chunking, retrieval or database work has happened.
- Not a licence grant. A source appearing here says nothing about whether we may use it.

## Product constraints these decisions must respect

- **English-language CVs only.** Hebrew CV generation and language selection are out of scope.
  Israeli sources written about Hebrew CVs may still contribute — structure, length, what
  employers expect, military service — but the artifact CareerHQ produces is English.
- **Israel-first, where a difference is real.** Israeli guidance takes precedence *only* where a
  genuine market-specific difference is demonstrated. Universal guidance stands everywhere else.
  **Israeli origin alone does not confer authority** — see the four dimensions below.
- **Two layers.** A general, company-independent resume-writing layer, plus role- and
  seniority-specific guidance.
- **Normative and demonstrative knowledge are different things.** Rules say what to do.
  Before → After CV examples show it. They are tracked in the same register under different
  `kind` values, and they will not be retrieved or cited the same way.

## Four independent dimensions

Kept separate on purpose; conflating them is how "an Israeli blog said so" becomes "authoritative".

| Dimension | Values | Where it will live |
|---|---|---|
| **Market relevance** | `global`, `israel`, `both` | ❌ no field exists in `ChunkMetadata` — must be added |
| **Authority / trust** | `institutional`, `vendor_documented`, `industry`, `community`, `internal` | `KnowledgeDocument.trust level` exists; values undefined |
| **Role relevance** | role family, or `any` | ✅ `ChunkMetadata.Role family` |
| **Seniority relevance** | junior → principal, or `any` | ✅ `ChunkMetadata.Seniority` |

## Claim taxonomy

**Not every sentence in a source is a rule.** Each contribution is classified as one of:

| Claim type | Meaning | Corpus eligibility |
|---|---|---|
| `authoritative_fact` | Documented by a body with standing to know (a government employment service on its own process; an ATS vendor on its own parser) | Eligible |
| `recommendation` | Reasoned professional advice from a credible source, not a documented fact | Eligible, attributed |
| `example` | A demonstrated before/after or worked case | Eligible as **demonstrative**, never as a rule |
| `community_opinion` | Widely repeated practitioner belief, no evidence given | Supporting evidence only |
| `unsupported_claim` | Asserted with no evidence and no standing ("ATS always rejects X") | **Never** corpus content |

## Dispositions

- **`corpus`** — should become corpus content, in CareerHQ's own words, citing the source.
- **`evidence`** — informs our thinking; never retrieved. Hypotheses to verify sit here.
- **`rejected`** — excluded, with the reason recorded permanently so it is not re-proposed.

## Verification status

Recorded per source, because "found in a search result" and "read the page" are not the same
claim and this project has been burned by that difference before.

- `read` — fetched and read directly
- `summary_only` — seen via search-result summary; primary page not individually verified
- `unexamined` — identified but not opened
- `dead` — URL does not resolve

## Rules for adding a source

1. **IDs are permanent and append-only.** `S-001` onward. Never renumber, never reuse. A rejected
   source keeps its ID and its rejection reason.
2. **Record licensing before disposition.** A source with unresolved licensing cannot be
   `corpus`; it stays provisional.
3. **Do not paste source text into this repository.** Describe what a source contributes. The
   working model is that CareerHQ authors rules in its own words and *cites* sources, which
   resolves licensing, keeps rules atomic, and makes a citation mean "this rule derives from X"
   rather than "here is X's paragraph."
4. **State overlap.** A source contributing nothing another already covers is `evidence` at best.
