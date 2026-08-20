# Quickstart — proving Match Analysis works

Run this **as written**. Slice 001's T069, slice 002's T052 and slice 003's T095 each found real
errors by walking their quickstart literally rather than approximating it.

The suite proves the logic. This proves the feature — and slice 003 established that every display
bug it shipped was found by a person looking at real data, never by the suite.

---

## Prerequisites

```bash
docker compose up -d
docker compose ps            # all healthy
```

A signed-in user with an **approved profile**. If the profile is empty there is nothing to score
against and every requirement will read `missing` — correct behaviour, useless as a test.

**Use a scratch user, never your real profile.** A slice 003 test run against live data merged a
fictional CV into it and replaced the contact block. Seed scratch users `@example.com` — pydantic's
`EmailStr` rejects `.test` and `.invalid`, and the resulting 500 reads as a white-screen app bug.

**Rebuild the backend after code changes.** The backend mounts nothing and runs the baked image, so
`docker compose up -d backend` restarts happily with the old code:

```bash
docker compose build backend && docker compose up -d backend
```

---

## 1. Confirm the model is configured — before spending anything

```bash
docker compose exec backend python -c "
from careerhq.config import get_settings
s = get_settings()
print('match_analysis ->', s.model_for_task('match_analysis'))
print('fallback       ->', s.llm_provider_model)
"
```

**The two must differ.** If they match, `llm_model_match_analysis` is unset and every analysis will
run on Opus at 2.5× the price with no quality gain — silently. This check costs nothing and has
already caught the same fallback once, on CV extraction.

## 2. Add a job with a real posting

At http://localhost:3000, add an application from a posting URL. If the URL path fails — it often
does, which is why the fallbacks exist — paste the posting text instead.

**Expected**: the form returns immediately. The applications table shows the job with a **pending**
indicator in the Match column, not a blank and not a zero.

## 3. Watch the score arrive

Within about 20 seconds the Match column shows a percentage.

```bash
docker compose exec backend python -c "
import asyncio; from sqlalchemy import text
from careerhq.infrastructure.database import session_factory
async def main():
    async with session_factory()() as s:
        for r in (await s.execute(text('''
            SELECT status, overall_score, band, direct, transferable, adjacent, impact,
                   criteria_version, model, input_tokens, output_tokens, cost, is_fixture
            FROM match_analyses ORDER BY created_at DESC LIMIT 1'''))).all():
            print(r)
asyncio.run(main())
"
```

**Expected**: `ready`, a score in 0–100, **the four dimensions it is the weighted sum of**
(`direct*0.4 + transferable*0.3 + adjacent*0.2 + impact*0.1`, rounded — check it),
`criteria_version = v2-importance`, `anthropic/claude-sonnet-5`, real token counts, a real cost,
and **`is_fixture = false`**.

The band is **not** simply the score bucketed: an unmet requirement the model rates 70 or above
caps it. So a score inside `moderate`'s range showing `stretch` is correct, not a bug — and the
Match tab names the requirement responsible.

`is_fixture = true` here means the fixture adapter answered and nothing was really scored.

## 4. Check the grounding rule against real output

```bash
docker compose exec backend python -c "
import asyncio; from sqlalchemy import text
from careerhq.infrastructure.database import session_factory
async def main():
    async with session_factory()() as s:
        print((await s.execute(text('''
            SELECT count(*) FROM match_requirements
            WHERE (verdict = 'unverified') <> (evidence IS NULL)'''))).scalar())
asyncio.run(main())
"
```

**Expected: `0`.** Any other number means AI-008 is being violated in stored data, and the database
constraint that should have made it impossible is missing.

Then open the job's **Match** tab and read the evidence. Each supported requirement must quote text
you recognise **from your own profile**. A plausible sentence that is not in your profile is the
failure this whole feature is built to prevent, and no automated check will catch it — only you
reading it will.

**Then read the gaps, which is the newer risk.** Every `gap` must quote profile text showing you
actually fall short. A requirement your CV simply never mentions must read **unverified**, not gap.
If the system tells you that you lack something your profile is merely silent about, it has
invented a negative fact about you — the same fabrication as inventing experience, pointed the
other way (R9/D1).

```bash
docker compose exec backend python -c "
import asyncio; from sqlalchemy import text
from careerhq.infrastructure.database import session_factory
async def main():
    async with session_factory()() as s:
        for r in (await s.execute(text('''
            SELECT verdict, count(*) FROM match_requirements
            GROUP BY verdict ORDER BY 2 DESC'''))).all():
            print(r)
asyncio.run(main())
"
```

**Expected**: a spread across several verdicts. If everything is `confirmed` or `gap` with nothing
`partial`, `transferable` or `unverified`, the model has collapsed to a binary and P5 is not
holding — the score is inflated and the gap list is manufactured.

## 4b. Check the importance ratings against the posting

```bash
docker compose exec -T postgres psql -U careerhq -d careerhq -c "
  SELECT importance, kind, verdict, left(text, 46) FROM match_requirements ORDER BY importance DESC;"
```

**Expected**: the requirements the role is actually about sit at 75–90, and boilerplate sits low.
On the reference posting, *"excellent written and verbal communication in English"* rated **30** and
*"prior work in a fast-paced startup environment"* rated **15** — both of which the posting itself
listed under **Requirements**.

If ten requirements come back above 80, the model has taken the heading at face value instead of
judging, and the cap will fire on nearly every job — which makes the band useless in the opposite
direction from too generous.

## 4c. Confirm an abandoned run does not wedge the job

```bash
docker compose exec -T postgres psql -U careerhq -d careerhq -c "
  UPDATE match_analyses SET status='pending', created_at = now() - interval '2 hours'
  WHERE id = (SELECT id FROM match_analyses ORDER BY created_at DESC LIMIT 1);"
```

Reload the Match tab, then trigger a re-run.

**Expected**: the tab reads **failed**, not a spinner, and the re-run is **accepted**. A `pending`
row older than an hour is reaped rather than honoured — before that, the in-flight guard answered
409 and the only action that recovers the job was the one action refused.

## 5. Confirm the four states are distinguishable

All four, on screen, and **in greyscale** (macOS: System Settings → Accessibility → Display →
Colour Filters → Greyscale):

| state | how to produce it |
|---|---|
| running | add a job and look immediately |
| scored | wait |
| nothing to score | add a job **by hand** with no description |
| failed | set an invalid `ANTHROPIC_API_KEY`, rebuild, add a job |

**Expected**: four visibly different treatments. *Nothing to score* must read as muted and ordinary
— **not** as an error. Gap and unverified chips must not be red; red is reserved for things that
actually broke, and painting twenty-seven chips red makes an ordinary posting look like a disaster.

**The five requirement verdicts must also be distinguishable in greyscale**, which means the glyph
carries the meaning, not the colour. `transferable` must be distinguishable from `confirmed` at a
glance — showing adjacent experience as direct experience is the fabrication FR-011b forbids — and
`unverified` must be distinguishable from `gap`.

Restore the key and rebuild afterwards.

## 6. Confirm a failed analysis leaves the job usable

With the failure from step 5 still on screen: open the job, edit it, change its status.

**Expected**: everything works. The failure is reported and blocks nothing.

## 7. Re-run, and confirm the previous score survives

Edit your profile — add a skill. Reopen the job.

**Expected**: the tab says the profile has changed since scoring and offers a re-run. **No other
job was re-scored automatically** — check the table.

Trigger the re-run and watch the Match column *while it runs*.

**Expected**: the previous score stays visible throughout. It must not blank to a spinner — that is
FR-015, and it is the difference between a re-run and a gamble.

```bash
docker compose exec backend python -c "
import asyncio; from sqlalchemy import text
from careerhq.infrastructure.database import session_factory
async def main():
    async with session_factory()() as s:
        print((await s.execute(text('SELECT count(*) FROM match_analyses'))).scalar(), 'analyses')
asyncio.run(main())
"
```

**Expected**: 2 or more. The first analysis still exists — append-only means the old score was not
overwritten.

## 8. Confirm a legacy row is not scored as a posting

Any job added before this slice has `requirements IS NULL` and a `job_description` holding a
joined requirements list, not a posting (R1).

**Expected**: it shows *nothing to score against yet* with an offer to re-add the job — **not** a
score. A number here means a legacy row was scored with the requirements-only methodology the
design reversed, and it would look completely normal.

## 9. Confirm nothing was written to the profile

Open the profile. **Expected**: unchanged. No new facts, no altered provenance. The analysis
observes and writes only to its own tables (FR-012).

---

## On the deployed system

Repeat steps 2, 3 and 4 at the deployed URL. The local run proves the logic; only this proves the
configuration, and slice 002 established that a green health check is not evidence — `ai_provider:
ok` is a construction check that a present-but-wrong key still passes.

```bash
railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway \
  -c \"SELECT status, overall_score, model, is_fixture FROM match_analyses
       ORDER BY created_at DESC LIMIT 3;\""
```

The `PGHOST`/`PGPORT` override is **not optional** — the running container carries a stale pointer
to a recycled proxy port that now serves another tenant's database, which answers the PostgreSQL
protocol and rejects your credentials.

**Expected**: a real model, a real cost, `is_fixture = false`.
