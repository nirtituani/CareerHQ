# Contract: Guideline Retrieval

**The port is not changed by this slice.** `GuidelineSource` was defined in slice 005 as the
005/006 boundary; this slice supplies a second implementation behind it.

```python
async def guidelines_for(self, *, context: GuidelineQuery) -> Sequence[Guideline]: ...
```

## Invariants this implementation must satisfy

1. **Signature unchanged.** No `top_k`, similarity score, or embedding parameter appears in the
   port, in `TailoringState`, or in any prompt (FR-003).
2. **Called once per run, before the graph** (FR-029, R3). Plan and Draft share the result.
3. **Every returned `Guideline` carries a resolvable citation** in `source` (FR-006). The
   citation identity is the one defined in [data-model.md](../data-model.md) — there is no second
   citation model:

   | Field | Purpose |
   |---|---|
   | `document_slug` + `document_version` | Which corpus document, at which revision |
   | `content_hash` | The chunk's identity; recomputing it over the recorded text verifies the guidance existed unaltered |
   | `locator` | Human-readable position, for display |
   | `text` | The rule as retrieved, **snapshotted** so a later corpus edit cannot rewrite what a past run was advised |

   `content_hash` is what makes a citation *checkable* rather than merely present: a match proves
   the guidance was in the corpus; a miss proves drift, loudly (FR-012).
4. **Bounded output.** Total tokens across returned guidelines respect the configured ceiling
   (FR-014); `KnowledgeChunk.token_count` makes this checkable without re-tokenising.
5. **Never fails a run.** Retrieval error or timeout falls back to the static rubric and records
   that it did (FR-009, FR-010).
6. **Empty corpus behaves as failure**, not as "no guidance": same fallback, same record.
7. **Selection is Israel-first only where marked.** A chunk tagged `market: israel` outranks a
   `global` chunk *on the same topic*; it does not outrank on unrelated topics.

   **"Same topic" is a declared list, not a similarity score (T027, 2026-08-28).** Each corpus
   document carries `topic: [...]` from a 16-value vocabulary (`domain/models/knowledge.py::Topic`)
   derived only from the 79 shipped rules. Two chunks are on the same topic when their declared
   lists intersect — a set operation, with nothing to tune.

   **Cosine similarity was tried first and measured insufficient** (`research.md` R13): it ranked
   the one true same-topic pair 326th of 504 cross-market pairs, below the median, while ranking a
   pair known to be *complementary* first of all. No threshold ordered the labelled cases correctly.

   **Outranks, never replaces.** Precedence reorders and suppresses nothing. Two documents may
   address one subject and remain complementary — the volunteering pair does, one governing
   inclusion and the other presentation — and FR-038 is explicit that global guidance remains
   applicable to Israeli-market CVs.

   **`GuidelineQuery.market` is the other half.** Precedence is scoped *"for Israeli-market CVs"*,
   so retrieval that cannot tell which market it serves cannot apply it. Defaults to `global`, in
   which case precedence is inert.

## Ordering contract

Returned in the order the prompt should render them: integrity rules first, then market-specific,
then general. Integrity rules are **always included regardless of similarity** — they are product
safety, not retrieved advice, and must not be crowded out by a close semantic match.

## Fallback contract

`StaticGuidelines` remains in the codebase as the documented fallback (FR-009). It is not dead
code and must not be deleted.

---

# Contract: Embedding

```python
class EmbeddingSource(Protocol):
    async def embed(self, *, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...
```

1. Lives in `application/`; **no implementation detail crosses that boundary**. The architecture
   test continues to forbid provider SDK imports there.
2. Returns vectors of the configured dimension (384 for MiniLM-L6-v2). A dimension mismatch against
   the stored column is an error at ingestion, not a silent truncation.
3. Deterministic for identical input, so re-ingestion of unchanged text is a no-op.
4. Usage is recorded per Principle V.
