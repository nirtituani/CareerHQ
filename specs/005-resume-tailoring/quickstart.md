# Quickstart — validating slice 005

How to prove tailoring works. Read [`contracts/http-api.md`](contracts/http-api.md) for payload
shapes and [`data-model.md`](data-model.md) for what is stored; neither is repeated here.

**The rule this slice inherits**: every display bug in this project was found by a person looking
at real data, and none were found by the suite. §4 is not optional.

---

## Prerequisites

```bash
docker compose up -d
docker compose ps                     # all healthy
```

A signed-in user with an **approved profile** and **at least one job carrying a current match
analysis**. Tailoring refuses without one (FR-001), which is itself the first thing to check.

**Use a scratch user, never your real profile.** A slice-003 test run against live data merged a
fictional CV into it and replaced the contact block. Seed the scratch user `@example.com` —
pydantic's `EmailStr` rejects `.test` and `.invalid`, and the resulting 500 reads as a white-screen
application bug.

---

## 1. The gates, on the host

Not in the container: `backend/.dockerignore` excludes `tests/`, so an in-container pytest collects
nothing — which looks much like a pass when skimming.

```bash
cd backend
.venv/bin/pytest                      # ≥80% coverage, gate enforced
.venv/bin/ruff format --check . && .venv/bin/ruff check .
.venv/bin/mypy src

cd ../frontend
npm run lint && npm run typecheck && npm test && npm run build
```

---

## 2. The workflow, without a provider

These run against the fixture gateway and prove the mechanics FR-013, FR-018 and FR-035 depend on.

```bash
cd backend
.venv/bin/pytest tests/integration/test_tailoring_workflow.py -v
```

What must be demonstrated, each as a named test:

| Path | Asserts |
|---|---|
| Clears review first time | 3 calls, one usage record each, no revision |
| One revision then clears | 5 calls; the second draft is what persists |
| Full budget exhausted | 7 calls; **the second revision used the escalated task name**; finalisation still ran |
| An `ungrounded` finding | The proposal is **absent from every row**; `original_text` stands; the finding persists |
| Every proposal rejected | Version content equals the master, saved without error (SC-005) |
| Invalid output at each node | Run `failed` with a reason; version readable at `draft`; no partial rows; a retry is accepted |
| Profile mutated after a version exists | Version content and `source_profile_updated_at` unchanged, read in a fresh session |
| Any run outcome | Every owner-owned profile table byte-identical before and after |

The exhausted-budget and escalation paths need the fixture gateway to return a **sequence** per
task name (research R10). Until it does, those rows are unprovable — and they carry the
release-blocking requirements.

**Watch the guard fail** before trusting it:

```bash
# Add `import anthropic` to a node, then:
.venv/bin/pytest tests/unit/test_architecture.py -k provider_sdk   # must name the file
# Remove it.
```

Same for the absence tests — the `rejected`-column precedent (T067) passed against a database that
had the column until `conftest.py` dropped before creating.

---

## 3. Through the API

```bash
# Refusal first — the precondition, not the happy path
curl -sX POST localhost:3000/api/applications/$APP_WITHOUT_ANALYSIS/tailor -b cookies.txt | jq
# → 422, naming which of the two causes

curl -sX POST localhost:3000/api/applications/$APP_ID/tailor -b cookies.txt | jq
# → 202 {version_id, status: "tailoring", run_id}

curl -sX POST localhost:3000/api/applications/$APP_ID/tailor -b cookies.txt | jq
# → 409 while the first is running

watch -n2 "curl -s localhost:3000/api/versions/$VERSION_ID -b cookies.txt | jq '.status'"
# tailoring → reviewing → awaiting_approval
```

Then check the database directly — the API can be right while persistence is wrong:

```bash
docker compose exec postgres psql -U postgres -d careerhq -c \
  "SELECT status, confidence_score, tailoring_run_id FROM resume_versions ORDER BY created_at DESC LIMIT 1;"

docker compose exec postgres psql -U postgres -d careerhq -c \
  "SELECT kind, count(*) FROM reviewer_findings GROUP BY kind;"

# FR-011: the analysis must be untouched
docker compose exec postgres psql -U postgres -d careerhq -c \
  "SELECT id, updated_at FROM match_analyses ORDER BY created_at DESC LIMIT 1;"
```

**Rebuild after backend changes.** The backend mounts nothing and runs the baked image, so
`up -d` restarts happily with the old code:

```bash
docker compose build backend && docker compose up -d backend
```

---

## 4. In a browser, on a real job

**The step that finds what the suite cannot.** Use `localhost`, not `127.0.0.1` — Next.js dev mode
403s its own chunks on the latter and the page renders without hydrating, with no console error.

Take a real posting and a real CV, and check:

1. **Every stored value reaches the screen.** Items, decisions, findings, confidence, cost, model,
   the fixture flag. Four display bugs in slice 003 were extracted correctly and dropped by the
   renderer.
2. **The five states are distinguishable** (SC-004) — and specifically that *the agent is
   reviewing* reads differently from *it is your turn* (FR-040). This is the state that did not
   exist before this slice; if it looks like the one before it, the amendment bought nothing.
3. **Confidence score and match score are not confusable** (FR-043). Different labels, and it must
   be obvious they measure different things.
4. **A finding sits next to the item it concerns** (FR-042), not in a banner.
5. **Reject, then edit, then approve.** Reopen and confirm the edited item is still identifiable as
   yours.
6. **Reduced motion**: any progress animation must land on the finished state when removed.
   `prefers-reduced-motion` collapses animations to 0.01ms — put the final value in the element's
   own style and let the keyframe supply only the start.
7. **Read the drafted resume as a person.** Does it claim anything you did not do? That question is
   FR-017 and no test answers it.

---

## 5. Measure, then record

SC-006's $0.30 ceiling and SC-001's timings are **targets awaiting measurement** (research R5).

```bash
docker compose exec postgres psql -U postgres -d careerhq -c \
  "SELECT attempts, input_tokens, output_tokens, cost,
          finished_at - started_at AS elapsed
   FROM tailoring_runs ORDER BY started_at DESC LIMIT 5;"
```

Record both paths — first-pass clear and full budget — in `research.md` the way slice 004's R8
recorded its own. **If the ceiling is missed, mark it missed in `spec.md`** rather than adjusting
the number. Slice 004 did exactly that with SC-004, and the honest record is worth more than a
green table.

---

## 6. On the deployed system

A slice is not done until it works deployed.

```bash
railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway -c \
  'SELECT count(*) FROM resume_versions;'"
```

The `PGHOST`/`PGPORT` override is **not optional**: the running container carries a stale host from
a deleted public proxy, Railway recycles those ports, and the address now serves another tenant's
database — which answers the protocol and rejects your credentials, reading as a password problem
when it is a wrong-server problem.

Confirm on the deployed site: a real tailoring run, `is_fixture = false`, a real model name, real
token counts, a real cost.
