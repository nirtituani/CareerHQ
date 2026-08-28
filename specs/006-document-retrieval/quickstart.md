# Quickstart: Validating Document & Retrieval

How to prove this slice works end to end. Validation guide only — implementation belongs in
`tasks.md` and the implementation phase.

## Prerequisites

```bash
docker compose up -d          # postgres carries the `vector` extension already (migration 0001)
cd backend && .venv/bin/alembic upgrade head
```

Embeddings are local, so **no API key is needed** for retrieval. A provider key is still required
to run a real tailoring job.

> `docker compose up -d backend` does **not** pick up backend code changes — the backend mounts
> nothing and runs the baked image. Use `docker compose build backend && docker compose up -d backend`.

## 1. Corpus ingestion

```bash
docker compose exec backend python -m careerhq.ingest
```

**Expect**: one `KnowledgeDocument` per corpus file, one `KnowledgeChunk` per authored rule
(1:1, FR-037), every chunk with a 384-dimension embedding and a `content_hash`.

**Then re-run it.** Expect **zero** new chunks — unchanged text keeps its hash, which is the
FR-012 property that lets a past run's citation still resolve.

The command exits non-zero if ingestion fails, and logs what it did in structured fields
rather than in the message. In production the same command runs **pre-deploy**, after the
migration — `alembic upgrade head && python -m careerhq.ingest` in `backend/railway.toml` —
so a corpus that will not load blocks the deploy instead of reaching production silently.
It is deliberately **not** in `entrypoint.sh`: a stale schema breaks the application, a
stale corpus does not.

## 2. Corpus integrity gates

Asserted over the real corpus, not a fixture:

- every rule is self-contained — no rule refers to "the rule above" or "see also";
- every conditional rule carries its condition **in its own text** (FR-037);
- **no rule instructs estimation, quota-filling, or adding unsupported claims** (FR-030) — the
  Principle III gate;
- only authored normative guidance is present — no digests, no examples (FR-036);
- every `market: israel` rule cites a source justifying the tag; integrity rules are all
  `trust_level: internal`.

**Drill it.** Add a rule saying "estimate a plausible figure where none exists", confirm the suite
names that rule, remove it. A gate nobody has watched fail is not a gate.

## 3. Retrieval

**Expect**: two postings in different disciplines return **different** guidance; every returned
guideline carries a citation resolving to document and chunk; **integrity rules appear in both
regardless of similarity** (retrieval contract); total tokens stay **under 1,500** (D5/FR-014).

**Citation verbatim check**: recompute `content_hash` over the recorded text and match it against
the corpus. A mismatch means drift and must fail loudly.

**Then empty the corpus and re-run**: the run still completes on the static fallback and records
that it fell back (FR-009/FR-010).

## 4. A real tailoring run

Sign in at http://localhost:3000 (use `localhost`, not `127.0.0.1` — dev-mode chunks 403 otherwise),
add a job, and tailor against it.

**Expect**: the run completes; `guidelines_used` holds retrieved guidance with citations; the
workflow is otherwise unchanged — same nodes, same review, same approval.

**Measure, do not derive**:
- **SC-007** — retrieval duration ≤500ms steady state, from the FR-039 timing. Model-load time is
  startup overhead and excluded.
- **SC-008** — cost per run within 2% of a `StaticGuidelines` baseline. **Run both arms in the same
  session** so pricing and model conditions match.

## 5. Export

Runs the six ATS assertions from [contracts/export.md](contracts/export.md) against a real
WeasyPrint-rendered PDF, verified with `pdfplumber` — an independent extractor, not the renderer
attesting to itself.

**Assertion 6 by hand**: export the same version twice and compare checksums. Identical, or FR-031
is not satisfied and FR-021's "stable checksum" is unenforceable.

## 6. Immutability

**Expect**: submission creates the record; editing the profile afterwards changes nothing about it;
every modification attempt is **refused with an error**, never silently ignored.

**Drill it**: remove the refusal, watch the test name the violation, restore it.

## What "done" looks like

- [ ] Ingestion idempotent — re-running adds no chunks
- [ ] Corpus lint passes, and has been watched failing
- [ ] Retrieval varies by posting, cites everything, always includes integrity rules, ≤1,500 tokens
- [ ] Citation hashes verify against corpus content
- [ ] A real run completes with citations recorded, workflow unchanged
- [ ] SC-007 (≤500ms) and SC-008 (≤2%) **measured**, both arms same session
- [ ] Six ATS assertions pass; byte-determinism confirmed by two exports
- [ ] Submitted records refuse modification, drilled
- [ ] `ruff format`, `ruff check`, `mypy src`, `pytest` ≥80%, frontend gates — green **on the host**
