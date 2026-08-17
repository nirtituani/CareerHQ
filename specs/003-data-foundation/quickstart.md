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
2. Reach the import screen and upload a real PDF CV. **There is no Import item in the sidebar** —
   docs/09 §6.0 defines six destinations and importing is an action, not one of them. Use
   **Dashboard → Import a CV**, or **Profile → Import my CV** on an empty profile. (An earlier
   version of this line said "Go to Import", which is not followable.)
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

1. **Applications → Add Application.** The modal opens on the automatic route: paste a posting URL
   and press **Fetch**. Confirm the company, title, location and requirements come back filled in,
   and that nothing was saved yet — the extraction populates the form and waits for you.
2. Press **Enter the details manually** on a fresh modal and confirm the same form appears empty,
   so the manual path does not depend on the automatic one.
3. Save. Confirm it stores with no submitted resume and a pre-submission status (FR-011), and that
   **Applied Via and Date Applied were never asked for** — both are meaningless before you apply.
4. Try a URL from a client-rendered board (any `comeet.com` posting will do). Confirm it either
   resolves through the vendor adapter or refuses with an offer to paste the text — and that no
   `{{position.name}}` placeholder ever reaches the form.
5. Change its status. Confirm a history row was written (FR-012):

   ```bash
   docker compose exec postgres psql -U careerhq -d careerhq -c \
     "SELECT count(*) FROM application_status_history;"
   ```

6. **Confirm no rejected column exists anywhere** — the release-blocking invariant (FR-016):

   ```bash
   docker compose exec postgres psql -U careerhq -d careerhq -c \
     "SELECT table_name, column_name FROM information_schema.columns
       WHERE column_name ILIKE '%rejected%';"
   ```

   Expect **zero rows**. This is an absence, so it has to be checked rather than observed — and
   check the tables exist first (`\dt applications`), because the query is vacuously satisfied by a
   database that has no applications schema at all. That is not hypothetical: the same assertion
   passed against a deliberately added column locally, because `create_all` had never rebuilt the
   test database.

7. Press the ✕ on a row to mark it rejected, then the undo arrow. Confirm the status returns to
   what it was **and** that the history still records the rejection — the undo appends, it does not
   erase.

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
   `ai_provider: ok` means a client could be *built*, not that the key works; step 3 is what
   settles that.
2. Import a CV on the deployed site and confirm the file landed in the bucket.
3. Confirm the model, tokens and cost were recorded for that extraction (FR-026):

   ```sql
   SELECT model, input_tokens, output_tokens, cost, is_fixture FROM imported_resumes
    ORDER BY created_at DESC LIMIT 1;
   ```

   `is_fixture` must be `false` on the deployed system — if it is `true`, the deployment is
   serving canned content and every extraction so far has been fictional.

4. Confirm the applications schema deployed, not just the code (T090). Reaching the deployed
   database needs the `PGHOST`/`PGPORT` override — the running container still carries a stale
   public-proxy address, and without the override `psql` authenticates against a stranger's
   database (CLAUDE.md):

   ```bash
   railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway -tAc \
     \"SELECT version_num FROM alembic_version;\""
   ```

   Expect `0005_applications`, both `uq_` constraints present, and zero `rejected` columns.

5. Record a job on the deployed site. **The slice is not done until the deployed system holds both
   of slice 004's inputs** — a populated profile *and* an application carrying real description
   text. The profile half alone does not meet it (T089, SC-010).
