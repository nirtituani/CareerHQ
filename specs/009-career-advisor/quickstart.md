# Quickstart — validating Slice 009 end to end

The lifecycle demo, runnable against the local Docker stack. This is the SC-002 walk: a
memory counts as agent-managed only if a later run retrieved it, reasoned over it, and
dispositioned it — each step observable below.

## Prerequisites

```bash
docker compose build backend && docker compose up -d     # backend mounts nothing; build is required
docker compose exec backend alembic upgrade head          # must show 0021_career_advisor
```

Sign in via Google OAuth at http://localhost:3000. **Use a scratch user** (`@example.com`
— never `.test`, which 500s `/api/auth/me`), and delete everything seeded by hand
afterwards (testing rule 7). Real LLM calls: set the Anthropic key in `.env`; the two
advisor tasks bill roughly a match analysis per run (SC-007).

## 1 — Honest empty state (Story 1, scenario 4)

Open **Career Advisor** in the nav (the entry that was marked *Soon*). With no
applications: the empty state names what the advisor needs; `POST /api/advisor/runs`
answers 409; no run row exists and nothing was billed.

## 2 — First run over Tier 1 data (Story 1)

Seed ~10 applications for the scratch user with varied statuses (several `rejected`), a
spread of `date_added`/`date_applied`, and 2–3 distinct title shapes. No match analyses
yet.

Click **Analyze**. Expect: immediate in-progress state; on completion (well under two
minutes, SC-006):

- Active memories with claims, every number carrying a denominator, ordered by priority.
- The coverage line: skill patterns unavailable — "0 of 10 analysed" (FR-011).
- No skill-gap memory exists (nothing analysed), and no claim uses causal language.

Verify groundedness (SC-001) for one memory: open it, take a cited fact's
`record_ids`, and recompute in the database:

```bash
docker compose exec postgres psql -U careerhq -d careerhq \
  -c "SELECT normalized_status, count(*) FROM applications WHERE user_id = '<scratch-id>' GROUP BY 1;"
```

The claim's numerator/denominator must match your count exactly.

## 3 — The lifecycle (Story 2 — the requirement)

Change the history in three directions: add 3–4 more rejected applications in the same
role family (confirms a pattern); move several applications so a previously claimed
pattern reverses (contradicts it); and make one memory's subject moot if one exists
(e.g. the last application of a claimed status moves away).

Run again. Expect, on the run detail and the page:

- **Confirmed**: same memory id, `last_confirmed_at` advanced, an `evidence_delta` with
  the fresh figures ("was 6/10 → now 9/14"); frozen evidence unchanged.
- **Superseded**: a new memory stating the change, linked to the old one; the old one
  readable under history with its original evidence intact.
- **Retired**: reason shown.
- The run's dispositions cover **every** previously active memory —
  `SELECT count(*) FROM memory_dispositions WHERE run_id = '<run-2>'` equals the active
  count before the run, and no action is missing.

That the run *received* the prior memories is asserted by the integration suite from the
rendered prompt (not re-checkable by eye here — but `ops` on the run and the disposition
log are its user-visible shadow).

## 4 — Tier 2 growth (Story 3)

Paste a real-ish job description into 5+ applications and run match analysis on each
(this is the existing per-application path — no backfill). Run the advisor again. Expect
skill-pattern memories whose denominators say "of the N analysed postings", whose
evidence includes the grouping (which requirement rows were read as which skill), and —
with N ≥ 5 — full-confidence status; with fewer, `tentative` marking.

## 5 — Dismissal (Story 4)

Dismiss one active memory. It moves to history as "dismissed by you". Run again on
unchanged data: the claim does not reappear (run detail may show a discarded proposal —
that is the deterministic layer working). Then change the underlying data materially and
run once more: if the agent re-proposes it, it appears as **new** with the dismissal
history visible on the memory.

## 6 — Failure honesty (SC-005)

Break the key (`ANTHROPIC_API_KEY=broken` — the verified settings field name — via
`docker compose up -d backend`; `restart` does not reread `.env`, and confirm with
`docker compose exec backend printenv ANTHROPIC_API_KEY` that the broken value took), run: the run reads `failed` with a kind-of-failure message, cost
recorded for anything spent, and the memory page still serves the previous state,
unchanged. Restore the key.

## 7 — Cleanup

Delete the scratch user's data (their applications, runs, memories, dispositions cascade
from the user row). Confirm the real profile's counts are untouched — count before and
after, the 008-verification discipline.

## Gates to run before calling it done

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy src
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

(Host, not container — the container excludes `tests/`. Worktree DB:
`CAREERHQ_TEST_DATABASE_URL=…/careerhq_test_009`.)
