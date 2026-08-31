# Quickstart: validating Role-Aware Company Research

End-to-end validation guide for the implemented slice. Prerequisites: the Docker stack up
(`docker compose up -d`), a real `TAVILY_API_KEY` in `.env`, and a **scratch user**
(`…@example.com` — never the real profile; testing rule 7). After any backend code change:
`docker compose build backend && docker compose up -d backend` (the backend mounts nothing).

## 1. Suite and gates (fast, no billing)

```bash
cd backend && .venv/bin/pytest            # needs PostgreSQL; ≥80% coverage gate
.venv/bin/ruff check . && .venv/bin/mypy src
cd ../frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Expected: green, including the new gates — the migration emptiness guard, the port-pairing
invariants (contracts/research-provider-seam.md #1–2), the architecture test still importing no
provider SDK under `application/`, the OpenAPI route enumeration asserting its count, and the
SC-007 sentinel test proving no profile data reaches research input.

## 2. The P1 journey (US1) — billable: one provider run

Seed (as the scratch user) an application whose posting names a **name-collided company** — the
Pango fixture from the POC is the reference case (company "Pango", the real Parking-Team JD).

1. Open the application → Company tab → "Research this company".
2. While running: tab shows progress; a second click answers 409 (FR-016).
3. On completion (expect ≤90 s; POC measured 32–53 s):
   - Entity identification visible, naming the Israeli parking company with reasoning (FR-007).
   - Seven sections render; **no fact/interpretation/inference labels anywhere** (SC-008).
   - "Relevant to Your Role" engages the posting's stack/team (SC-002 — human judgement).
   - Sources all concern the identified employer (SC-001); provider sources show as
     attributed, without verified-quote affordances (FR-010).
4. Re-request research → `reused: true`, instant, no spend (SC-004).
5. Verify the snapshot row: `status='succeeded'`, `produced_by='provider:tavily-research'`,
   `prompt_version='app-v1'`, `cost_basis='estimate'`, non-null cost (SC-006).

## 3. No-posting research (US2) — billable: one provider run

On a scratch application with no job description and no requirements:

1. Request research → run proceeds (no dead button).
2. Company sections populated; role sections **explain the missing posting** rather than
   guessing a role (FR-011, D7).
3. Paste a JD onto the application, refresh research → new snapshot, role-aware.

## 4. Provider down (US3) — not billable

1. Set an invalid `TAVILY_API_KEY` (or point the adapter at an unroutable host in config),
   `docker compose up -d backend`.
2. With `research_fallback_enabled=true`: request research → result arrives from the builtin
   pipeline, `produced_by='builtin'`, `shape='tiered'`, verified excerpts present, and the UI
   quietly shows the producing path.
3. With `research_fallback_enabled=false`: request research → run fails;
   `failure_reason='ResearchProviderUnavailable'`; the tab shows the failure; the previous
   successful snapshot (from step 2) is still what GET returns as current.
4. Restore the key and `docker compose up -d backend` (env changes need recreate, not restart).

## 5. Legacy coexistence (US4) — not billable

With a pre-change `company_research_snapshots` row present (seed one from a fixture if the
database has none):

1. GET research for an application of that company **before any new run**: `shape='tiered'`,
   `produced_by='legacy-company'`, renders in the legacy view.
2. Run new research → GET now returns the application snapshot as current.
3. Verify the legacy row's stored `sections` are byte-identical to before (SC-005):
   compare a `md5(sections::text)` taken before and after.

## 6. Migration drill (before merging)

On a disposable database: insert a fake row into `role_research_snapshots` **before** running
`alembic upgrade head` and confirm migration 0020 **refuses** (the emptiness guard is a gate that
must be watched failing). Remove the row, upgrade, confirm the reshaped table and the rewritten
`research_sources` constraint (`\d application_research_snapshots`, `\d research_sources`).

## 7. Cleanup

Delete everything the scratch user seeded. Two-checkout note: use
`CAREERHQ_TEST_DATABASE_URL=…_myworktree` if another checkout may run the suite concurrently.

**Cost expectation for the full pass**: two provider runs (mini tier, documented 4–110
credits each, inside the current plan) + one fallback run (~$0.04–0.08 LLM). Record actuals in
tasks.md as you go.
