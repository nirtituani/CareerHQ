# Quickstart: validating Data Foundation

How to run this slice and prove it works. Written to be *followed*, not read — slice 001's T069
and slice 002's T052 both found real errors in documents that had never been walked as written.

## Prerequisites

The slice 001 stack, plus two things that are new and neither of which exists by default.

```bash
cp .env.example .env          # SESSION_SECRET and the Google OAuth values
docker compose up -d
```

### The provider key question

CV extraction is a model call (spec D1), so the import flow needs one of:

| Set this | Result |
|---|---|
| `ANTHROPIC_API_KEY=…` (and `AI_PROVIDER=anthropic`) | Real extraction |
| `AI_PROVIDER=fixture` | Canned structured content, **labelled as fixture data** in the interface |
| Neither | Stack runs; readiness reports `ai_provider: not_configured`; the import endpoint returns 503 naming the setting |

The third row is deliberate, not a gap. `docker compose up` still works on a clean clone with no
account anywhere — the property docs/06 §7 protects — and the import is the one thing that asks
for something. Fixture mode is never selected by the *absence* of a key, because that would mean
uploading a real CV and reviewing invented content.

### Object storage

Locally, MinIO is already in the Compose stack. Deployed, the bucket must exist:

```bash
railway bucket create              # none exists in production yet — verified
railway bucket credentials         # fills S3_ACCESS_KEY / S3_SECRET_KEY / S3_ENDPOINT_URL / S3_BUCKET
```

Until then readiness reports `object_storage: not_configured` and file retention (FR-006) is
unmet. That is why FR-021 makes it a requirement rather than an assumption.

## Validating User Story 1 — CV import

1. Sign in at http://localhost:3000.
2. Go to **Import**, upload a real PDF CV.
3. **Before touching anything, check the database.** This is the assertion, not a formality:

   ```bash
   docker compose exec postgres psql -U careerhq -d careerhq -c \
     "SELECT (SELECT count(*) FROM work_experiences) || '|' || (SELECT count(*) FROM skills);"
   ```

   Expect `0|0`. Extraction has run and **nothing is in the profile yet** (FR-003, FR-007).
4. Review the extracted items. Confirm each shows whether it was extracted or corrected, and its
   confidence (FR-004). Correct one deliberately.
5. Approve. Re-run the query — now populated, and the corrected value is stored rather than the
   original (Scenario 2).
6. Confirm exactly one Master Resume:

   ```bash
   docker compose exec postgres psql -U careerhq -d careerhq -c \
     "SELECT count(*) FROM resume_profiles WHERE is_master;"
   ```

   Expect `1`. **Then click approve again** — it must stay `1` (SC-004, constraint C4).
7. Upload a file that is neither PDF nor DOCX. Expect a message naming accepted formats and
   nothing stored (Scenario 5).
8. Upload a scanned/image-only PDF. Expect an explicit extraction failure, **not** an empty review
   form (FR-008) — the failure mode that would otherwise imply the CV was understood.
9. Start an import and abandon it. Confirm the profile is unchanged (Scenario 6).

## Validating User Story 2 — record a job

1. **Applications → New**. Add a company, title, and paste a real job description.
2. Confirm it saves with no submitted resume and a pre-submission status (FR-011).
3. Change its status. Confirm a history row was written (FR-012):

   ```bash
   docker compose exec postgres psql -U careerhq -d careerhq -c \
     "SELECT count(*) FROM application_status_history;"
   ```

4. **Confirm no rejected column exists anywhere** — the release-blocking invariant (FR-016):

   ```bash
   docker compose exec postgres psql -U careerhq -d careerhq -c \
     "SELECT table_name, column_name FROM information_schema.columns
       WHERE column_name ILIKE '%rejected%';"
   ```

   Expect **zero rows**. This is an absence, so it has to be checked rather than observed.

## Validating User Story 3 — JobTracker import

Requires a real export file (research R8 — the shape is not yet known, and the mapping is not
written against a guess).

1. Import the export. Check the report: imported, skipped, rejected-with-reasons.
2. Confirm normalized statuses match the source, and rejection arrived as a status value.
3. **Import the identical file again.** Expect zero new applications and zero new companies,
   reported as skipped rather than as errors (FR-017, SC-006, constraint C3).
4. Confirm one company row per real company, not one per record (FR-014, C2).

## Gates

Run from the host, never inside the containers — `backend/.dockerignore` excludes `tests/`, and a
container `next build` fails on a directory the dev server owns (CLAUDE.md).

```bash
cd backend && .venv/bin/ruff format --check . && .venv/bin/ruff check . \
  && .venv/bin/mypy src && .venv/bin/pytest
cd ../frontend && npm run lint && npm run typecheck && npm test && npm run build
```

`pytest` must pass **with no API key set** — that is FR-027, and it is worth confirming by
unsetting the key rather than assuming the fake was used.

## Deployed validation

Slice 002's lesson: a passing health check is not evidence the feature works, and three proxy
misconfigurations all deployed green.

1. `curl -sS https://frontend-production-02ac.up.railway.app/api/health/ready` — confirm
   `object_storage` and `ai_provider` both report `ok`, not `not_configured`.
2. Import a CV on the deployed site and confirm the file landed in the bucket.
3. Confirm the model, tokens and cost were recorded for that extraction (FR-026):

   ```sql
   SELECT model, input_tokens, output_tokens, cost, is_fixture FROM imported_resumes
    ORDER BY created_at DESC LIMIT 1;
   ```

   `is_fixture` must be `false` on the deployed system — if it is `true`, the deployment is
   serving canned content and every extraction so far has been fictional.
