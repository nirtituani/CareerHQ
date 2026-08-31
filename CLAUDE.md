# CareerHQ

AI-powered career intelligence platform. Import a CV, track applications, and have an agent tailor
your resume to a job description — with your approval on every change.

Built solo as a course project on a four-to-six-week budget. That constraint is real and shapes
the plan: see `docs/05_Implementation_Plan.md` §2.

**This file holds what stays true.** Status, open tasks, measurements, implementation history and
what has already failed live in [`HANDOFF.md`](HANDOFF.md). If the two disagree about state,
HANDOFF.md wins.

---

## Read these first

**Resuming work? Read [`HANDOFF.md`](HANDOFF.md) first** — current status, what failed, and the
exact next steps. Then the five below, in order. The whole project is legible from them.

1. **`docs/07_Capabilities.md`** — what CareerHQ is and what each capability does. One page.
2. **`docs/08_Technical_Spec.md`** — the full technical spec in one document. Every capability
   carries a status marker, so it is also the fastest way to see what is actually built.
3. **`.specify/memory/constitution.md`** — the seven non-negotiable principles. Violations of
   II–IV are release blockers.
4. **`docs/05_Implementation_Plan.md`** — the slice roadmap and why it is ordered that way.
5. **`specs/00N-<slice>/tasks.md`** — the current slice's tasks, showing where work stopped.

Supporting detail lives in `docs/01` (requirements), `docs/02` (ADRs), `docs/03` (domain model),
`docs/04` (architecture), `docs/06` (stack). Original source material — the course requirements,
the author's design notes, the resume-builder reference — is in `docs/reference/`.

**Repo location**: `/Users/nirtituani/Developer/CareerHQ`. It was moved out of
`~/Documents/AI Workshop/` because iCloud syncs that folder and generated 69 conflict copies of
source files. `.gitignore` excludes the `* 2.*` pattern, but the real fix was leaving iCloud.
**Do not move it back.**

---

## Architecture

### Layering

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 async, layered as
  `api/ → application/ → domain/`, with `infrastructure/` implementing what the inner layers
  declare. `domain/` imports no framework code — that is what keeps Principle V enforceable.
- **Business invariants belong in the schema.** A UNIQUE constraint cannot be raced or forgotten;
  an application-level check can be both.
- **Ownership comes from the session, never from the request.** No endpoint accepts a
  client-supplied user or profile id. A test enumerates every route and asserts non-public ones
  return 401.

### The structured completion seam

`specs/003-data-foundation/contracts/extraction-seam.md` is the artifact to understand first. One
call in, one validated object out: `complete(task, schema, prompt) -> Completion[T]`.

A schema is required, so unvalidated text cannot come back; the model is chosen by **task name**,
which is what lets model-per-node be configuration rather than branches; and usage is returned so
the audit record Principle V requires is written in the same transaction as the work.

**The enforced boundary is an import-graph rule, not a claim about call sites.**
`tests/unit/test_architecture.py::test_the_application_layer_imports_no_provider_sdk`: **no module
under `application/` may import a provider SDK or an embedding runtime**, so nothing above the seam
can reach a model except through it. Call sites *may* loop, react to their own output and revise —
the tailoring graph does, because that is what a self-critique workflow is. It does so by calling
`complete()` repeatedly, holding the state itself, because the seam has no memory, no conversation
and no tools to offer it.

**`llm_model_<task>` must be set for every new task.** `model_for_task` falls back to
`llm_provider_model`, which is **Opus** — so a task with no entry silently runs at 2.5× the price
for no gain. `docs/08` §3.2.3 fixes the model per workflow node; it is expressed by task name,
never by a branch.

### The `GuidelineSource` boundary

`application/guidelines.py` is the 005/006 boundary and its docstring is the argument. RAG is an
**input enhancement** through this port, not a redesign of the tailoring workflow: swapping
`StaticGuidelines` for a retrieval implementation changes no node, no state key and no
finalisation rule. The port deliberately has no `top_k`, no scores and no embedding parameters —
those are retrieval's vocabulary, and putting them in the port would choose the implementation.

`application/embeddings.py` (`EmbeddingSource`) makes the same refusal for embedding: no model
name, device, cache directory or batch size.

**The swap has happened and the claim held.** `RetrievedGuidelines` is behind the port,
`build_guideline_source()` in `api/routes/tailoring.py` is the one `if`, and `run_tailoring` was
**not edited** — it already called `guidelines_for` once before the graph, so FR-029 needed a test
rather than a change. `static` is not dead code: it is the documented FR-009 fallback and the only
way to take a cost baseline in the same session as a retrieval run.

### The `ResearchProvider` seam (slice 010)

`application/ports.py` → `ResearchProvider.research(company_name, domain, role_title,
posting_text) -> ResearchOutcome`. One call in, one validated sections-shaped result out, with
sources and an explicit cost basis. The role and posting come **from the application** —
`scoreable_posting()` is the single answer, its third caller — and never from the profile; a
sentinel test (`test_research_no_profile_leak.py`) asserts the assembled inputs stay clean.

- **Two adapters, chosen in `api/routes/research.py`** (the `build_guideline_source` pattern):
  `TavilyResearch` (primary; `POST /research`, `model="mini"`) and `BuiltinResearch`, which wraps
  the unchanged 008 pipeline as the configured fallback. Every snapshot records `produced_by`
  truthfully; a `legacy-company` value is derived at read time for 008-era rows and never stored.
- **Provider quirks are measured, not assumed, and both cost a real run to learn**: the endpoint
  400s any schema property without a `description` **and** anything but `properties`+`required`
  at the top level (so the adapter inlines pydantic's `$ref`/`$defs`); and it answers
  `status: "pending"` in under a second — the result is polled by request id.
- **`cost_basis` is `recorded` or `estimate`, never blank and never mixed.** The provider returns
  no usage and its usage API lags by hours, so provider runs record a documented-rate estimate
  (currently the mini-tier midpoint, ~4× above the ~14 credits/run actually observed — a
  deliberate overstatement, never presented as billing). Failed runs record what they plausibly
  spent; a run that reads as free is worse than one that reads as unrecorded.
- **Research is per application** (measured: company-level reuse would have saved ~3% of calls),
  reuse window 30 days, `aging` between 30 and 90, `stale` past 90 — all derived at read time.
- **A wrong entity is visible, not silent**: `company_identification.how_identified` is required
  and shown first. A no-posting application gets honest company-only research — and on a
  collided name the entity is then a coin flip, which the tripwire exposes (measured: "Pango"
  with no posting resolved to the wrong Pango; with the posting, the right one).
- **One Tavily key serves both adapters**, so a broken key downs the fallback too — the fallback
  protects against research-endpoint failure, not key failure. The failure is still honest:
  recorded reason, last success still served.
- **`research_sources.excerpt` non-null means verified verbatim** by a path that fetched the page
  itself; provider sources carry `NULL` and render as attribution. Do not blur these (FR-010).

### The tailoring workflow

`Plan → Draft → Review → Revise`, one conditional edge, bounded at two revisions, orchestrated by
LangGraph in `application/agents/tailoring/graph.py`, each node calling `complete()`.

| Stage | Reads | Returns | Responsibility |
|---|---|---|---|
| **Plan** | posting, match analysis (read-only), profile, guidelines | `TailoringPlan` | What to emphasise, de-emphasise, which gaps must **not** be misrepresented, and a strategy paragraph. Persisted (FR-009); Draft executes it rather than re-deciding it |
| **Draft** | plan, posting, profile, guidelines | `TailoredDraft` | Rewrites, reorders, drops. **Returns only changed/dropped items, by id** |
| **Review** | profile (grounding), posting, **the composed resulting resume** | `ReviewResult` | `ungrounded` / `overstated` / `uncovered`, plus a confidence 0–100 |
| **Revise** | findings, plan, profile, composed resume | `TailoredDraft` | Fixes what the Reviewer named. Escalates Sonnet→Opus on the second attempt **by task name**, never by a branch |

**Invariants that are easy to break and expensive to rediscover:**

- **Draft and Revise must return only changed items.** Output is 57–86% of cost and the slow half
  of a completion. Showing a model the whole resume and letting it hand one back is the cost
  problem, not a fix. A test asserts `_DRAFT` still says so.
- **The Reviewer judges the *resulting* resume, not the diff.** `compose_resume()` applies the
  draft over the master; `uncovered` is a question about the document and cannot be answered from
  a diff. The master still travels whole, separately, because grounding asks whether a claim
  traces to anything in the profile — including facts no draft touched.
- **Every profile line the model may propose against carries `[id: <uuid>]`.** `_render_master`
  renders them; `DraftedItem.source_item_id` maps a proposal back to a master row. Without ids
  nothing maps, and a "successful" run persists a diff with zero changes.
- **The severity split runs in the use case, before any row is written.** An `ungrounded` finding
  discards its proposal and restores the owner's wording, so a fabricated claim has no persisted
  representation and can never reach an approve button. A terminal `finalize` node would satisfy
  every other rule and break this one.
- **LangGraph orchestrates and owns nothing.** The test of it: deleting every LangGraph import and
  rewriting the graph as a loop must require no schema change and no change to any use case.
- **A validator's rules must be visible in the JSON Schema.** `model_validator(mode="after")` does
  **not** serialise, and the schema is the whole contract the gateway sends. A conditional
  requirement has to live in `Field(description=...)`, which does serialise.

### The export and submission path

`READY → EXPORTED → SUBMITTED`, and each arrow is a use case that refuses before it acts.

| Stage | Module | Rule |
|---|---|---|
| **Export** | `application/export.py` (guard) + `export_resume.py` (use case) | Render, **store the bytes, then write the row**; SHA-256 over the **stored bytes**, not the document model |
| **Submit** | `application/submit_resume.py` | **Re-read the stored bytes and re-hash them**; compare with the recorded checksum; only then insert and transition |
| **Read back** | `application/submissions.py` | `submission_for(application_id)` is the single answer to "what did this application send" |

- **The recorded checksum is not evidence about the bytes.** It says what the export *believed* it
  stored. Submission re-reads the object and hashes what came back, because a copy operation
  verifies nothing — it would succeed identically against an object that had been replaced,
  truncated or lost. **A mismatch refuses and repairs nothing**: not by re-rendering (the version's
  items may have moved on, so a re-render is a *different* document wearing the same record) and
  not by rewriting the export's checksum, which would launder corruption into a row that then
  looks verified for ever.
- **Bytes are stored before the row is written.** Object storage is outside the transaction, so one
  failure direction has to be chosen: an orphan object is garbage, while a record whose checksum
  refers to bytes that do not exist fails re-verification on a document the user believes they have.
- **Every export gets a fresh storage key.** Re-export is legitimate — a download that failed, a
  second copy — and `ExportedDocument` has no unique constraint on the version for exactly that
  reason. A reused key would overwrite the bytes an earlier submission recorded a checksum for.
- **Two refusal types, and they must not be one.** A wrong-state refusal is the person's to resolve
  (export first, revise as a new version); a checksum mismatch is not. They are deliberately
  unrelated classes so a handler cannot collapse them, and the route logs the mismatch as well as
  returning it — an integrity failure whose only trace is a 409 in a browser is invisible.
- **`submission_for` returning `None` is an answer.** An application that reached `Applied` outside
  CareerHQ — every imported row — has no document here. A fallback to "the latest export" would
  answer confidently about something no employer received.

### The Match/Tailor scoreability rule

`application/scoreability.py` → `scoreable_posting(application) -> str | None` is the **single**
answer to "is there posting content to send". Both Match and Tailor ask it; nothing spends a
completion when it returns `None`.

Order: a `requirements IS NULL` legacy row is refused outright; then the `job_description` when it
has content; then the requirements, composed one per line, when it does not. **Composition
reformats and never adds** — a test walks every line and asserts it traces to a stored value.

**Two different questions, and conflating them breaks FR-006.** Whether *scoring is meaningful* (a
posting that yielded no requirements is "nothing to score against, not a zero") and whether *there
is anything to send* are separate checks in `create_pending_analysis`. Collapsing them into one is
a mistake that has already been made and caught once.

---

## Product invariants

Decisions that must not be re-litigated. Each was tried the other way first; HANDOFF.md §4 records
what that cost.

- **There is no `rejected` column, and its absence is a release blocker.** Rejection is a value of
  `normalized_status`. An imported row with `rejected=true` and status "Interview Round 2" keeps
  the label — how far you got — and normalizes to `rejected` — the outcome. Asserted against
  `information_schema` locally **and** on the deployed database, because an invariant enforced by
  an absence has nothing else to catch its return.
- **Mark-as-rejected moves the status**, so there is one source of truth, and undo restores the
  previous status *from history* rather than clearing a flag.
- **`date_added` and `date_applied` are separate**, so "this sat in Pre-Applied for 46 days" is
  computable. One field overwritten at the transition loses exactly that signal.
- **Applied Via and Date Applied are asked only once the status is Applied or later.** Both are
  meaningless on a job nobody has applied to.
- **A second import merges, it does not append.** Keys are conservative — a role is company plus
  title plus start date — so a duplicate can be discarded by hand rather than an incorrect merge
  being undoable. A value the **user corrected** is never replaced by a later import.
- **Approval has two modes**, chosen by what the user did. An untouched review adds everything not
  discarded; explicitly adding any item narrows it to those.
- **The profile is editable and removable** — per item, per section, and entirely — behind an
  explicit edit mode. Correcting there marks the fact `user_corrected`, which then protects it
  from a later import.
- **`EXTRACTED` is not labelled.** Every fact carries it straight after an import, so the label
  said nothing; only `CORRECTED` and `ADDED` are marked.

- **Two states are locked, and `READY` is not one of them.** A version's *content* is frozen at
  `EXPORTED` and `SUBMITTED` (`application/immutability.py`); `READY` **remains editable**, because
  FR-029 says so and `docs/03` §10.1 says approval *"is not a one-way door until export"*. Locking
  `READY` is the most plausible way to get this wrong while every immutability test still passes.
- **The lock is about content, not about the row.** A locked version's status still moves forward —
  `EXPORTED → SUBMITTED`, and re-export — because a guard that refused every write would strand a
  version at `EXPORTED` for ever, which is worse than what it prevents.
- **Revising after submission creates a new version, and this already works by accident of one
  line.** `create_pending_version` reuses an existing version **only when it is a `DRAFT`**;
  widening that filter by one status would let a revision overwrite a document somebody sent.
  An unfinished `DRAFT` *is* reused, deliberately — that is the retry rule, and it is why there is
  no `failed` version status.
- **A `SubmittedResume` is insert-only, and the claim is enforced by a gate rather than by care.**
  `test_a_submitted_resume_is_insert_only` whitelists every mention of the class in `src/` —
  construction, column reference, `select`, annotation — and fails on anything else, including
  handing the class to a helper whose body it never reads. A second gate walks module-level
  containers at run time, because `api/routes/profile.py` writes through a registry and no syntax
  at the point of that write names any model at all.

### Match analysis

- **Five verdicts, not three, and the fifth is the point.** `confirmed`, `partial`,
  `transferable`, `gap`, `unverified`. AI-008 forbids inventing experience the profile lacks; a
  single evidence-free `missing` verdict would leave the model free to invent its **absence**,
  which is the same fabrication pointed the other way. Every verdict except `unverified` must
  quote the profile — **including `gap`, which quotes the shortfall** — and `unverified` is the
  only evidence-free one because it is the only one that asserts nothing.
- **A silent profile still costs you.** `unverified` is weighed like a gap, because a recruiter
  reads exactly the profile the model reads and draws the same conclusion from silence. The
  *claim* stays honest; only the weighing changed. The two are shown differently and only
  `unverified` is recoverable — add it to your profile and re-run.
- **Importance is judged, never read off the heading.** A posting's "must have" list is routinely
  a wishlist, so each requirement carries an `importance` 0–100 and the band caps at 70. The
  prompt tells the model that requirements stated **earlier** matter more.
- **Criteria are versioned and the version is stored.** Changing a weight, a band threshold or the
  cap rule is a **new version**, never an edit — otherwise every historical score silently becomes
  incomparable. The band is stored too, not derived at render time: re-banding history rewrites
  what a person was told.
- **Never tell a model how to distribute its answers.** *"Most real profiles are mostly
  `partial`…"* made the model push verdicts down to comply.

### Reading a job posting from a URL

Three steps, tried in order, because the first two fail often and the third always works:
**URL** → **paste the posting text** → **fill it in by hand**.

- **Structured data is metadata only.** Never return early on a schema.org `JobPosting` block —
  it routinely holds company blurb while the page holds the requirements. Where the employer *did*
  state a field it still wins over a model reading a page; the body always comes from the page.
- **Never ask the model to retype the description.** Output is the slow half of a completion and
  57–86% of the cost. Metadata only. This is the cost lever as well as the latency one.
- **A page that ships its template must be refused, not read.** Client-rendered boards serve
  `{{position.name}} @ {{company.name}}`, and a model will "extract" that into placeholders —
  which reads as a broken feature rather than an unreadable page.
- **Comeet needs a vendor adapter** (`infrastructure/jobs/comeet.py`) because it renders
  client-side and dominates Israeli tech hiring.
- **LinkedIn works fine** with a plain fetch. Repeated assumption to the contrary was wrong.

**Reading the source app is cheaper than guessing at it.** `nirtituani/job-tracker-web` is public
and settled the status vocabulary, the Applied Via options and `match_rating * 20` — twice, both
times replacing a guess.

---

## Security and privacy

**This repository is PUBLIC.** Treat every path as publishable unless it is proven ignored.

- **`testing files/` holds real CVs and is gitignored**, as is
  `specs/006-document-retrieval/corpus-research/examples/`. A CV carries a home address, a phone
  number and an employment history. Both sat untracked for a while with `git add -A` in regular
  use, one keystroke from permanent publication. **Before any `git add -A`, run `git check-ignore -v`
  on the sensitive paths.** The only documents ever committed are the synthetic fixtures in
  `backend/tests/fixtures/`, whose subject is fictional precisely so they can be.
- **`infrastructure/jobs/fetch.py` is the only place a user-supplied URL is requested**, which
  makes it the one place SSRF is possible: `169.254.169.254`, `backend:8000` and the database are
  each one request away. The guard resolves the hostname and refuses any non-global address,
  re-checks every redirect hop, allows only http/https, and **never names what it found** —
  otherwise it doubles as a way to map the network.
- **Configuration errors name the field, never the value.** `get_settings()` catches
  `ValidationError` and rebuilds the message, because pydantic puts rejected input in its own
  error text. Secret fields are detected from their `SecretStr` annotation, so a new secret is
  covered automatically.
- **`str(ValidationError)` embeds `input_value=`.** Logging it reinstates exactly the model output
  the gateway strips. `safe_validation_errors()` in `application/ports.py` is shared by both
  layers; it keeps `msg` only for `value_error`, where the text is ours.
- **Unauthenticated endpoints disclose the kind of failure, not the detail.** Readiness returns
  `OperationalError`; the driver's text — which names the internal IP, port, and database user —
  goes only to the log. The same rule applies to any error a route returns: **the detail goes to
  the operator, the type goes to the browser**, never inverted.
- **`SecurityHeadersMiddleware` sets `nosniff`, `DENY`, and `no-referrer` on every response**,
  including errors. HSTS is production-only; sending it from plain-HTTP localhost pins a scheme
  that does not work there, and browsers cache the pin. **Both halves of the origin must send
  them** — the middleware never sees page responses, so `frontend/next.config.ts` sets the same
  four with the same values, and they must stay in step.
- **Use high-entropy secrets even in development.** A low-entropy value cannot be scanned for:
  local `POSTGRES_PASSWORD=careerhq` collides with the project name in 2000 log lines, which makes
  secret-scanning the logs meaningless.

A full `/security-review` of the branch diff has **not** been run.

---

## How we work

**Spec-Driven Development** using GitHub Spec-Kit. Every slice runs
`specify → plan → tasks → analyze → implement → verify`. Artifacts live in `specs/` and are
version-controlled. **Do not skip `analyze`** — it has caught real gaps before code was written.

**Tests first.** Write the test, run it, confirm it fails for the right reason, then implement.
The failure message matters: `ImportError` because the module does not exist yet is a valid red;
a test that passes before implementation is a broken test.

**Verify in Docker, then in a browser.** Every user story ends with a task that runs the real
stack. That step has caught bugs the suite could not: a missing dependency that existed only in a
local venv, an empty `SESSION_SECRET` being accepted, and an OAuth redirect URI pointing at an
internal Docker hostname.

**Update `tasks.md` as you go.** Tick boxes when tasks complete, and amend a task's text when the
implementation deviates — a task list that lies about what happened is worse than none.

**Commit messages explain why.** The what is in the diff.

**`/handoff` before `/clear`.** It does not run automatically.

---

## Testing philosophy

Beyond "tests first", the rules this project actually runs on:

1. **Drill the old behaviour.** A gate nobody has watched fail is not a gate. Break the
   implementation, confirm the test names the exact violation, restore. When implementation
   predates a test, ticking the task on inspection is a lie; break it instead.
2. **A gate with nothing to examine passes forever.** This has shipped **four** times: a route
   enumeration examining zero routes, a Tailwind theme scan that never existed, an AST walk
   finding zero call sites, and a `-k` selector matching no tests and printing a cheerful pass.
   **Assert the count of what you examined**, and read the `N deselected` line.
3. **Assert an absence against the right scope.** A prompt contains the master *and* the composed
   resume; searching the whole prompt for text that is in both proves nothing. Radix portals break
   this the same way in the frontend — "no toggle on the form" passed against a form that had one,
   because the dialog rendered into a portal and `container` was empty.
4. **A test double is fed by someone who read the code; a model is not.** Where a model must read
   something out of a prompt, make the double read it out of the prompt too — otherwise the suite
   proves the plumbing works when values are supplied, never that a model *could* supply them.
5. **Keep measured facts separate from interpretation**, in tests, in commits and in research
   notes. "Eight `uncovered` findings exist" is measured; "the agent declined to invent" is a
   reading.
6. **The suite has never once caught a display bug.** Contact fields, bullet attribution, skill
   categories, project URLs, and every default button in the application were all found by a
   person looking at real data. A fixture only contains the fields whoever wrote it thought to
   include, so it cannot catch an omission.
   `tests/integration/test_profile_content.py` reads the models' own columns and requires every
   stored value to reach the API.
7. **Test against a scratch user, never the real profile.** A test run against live data merged a
   fictional CV into it and replaced the contact block. Seed with `@example.com`, and delete
   anything seeded by hand afterwards.
8. **A test double that repeats its last answer** would make an unbounded loop look convergent.
   `ScriptedSeam` raises instead.
9. **A second render path costs an affordance every time.** Grouping skills created one, and Edit,
   then Add, then Remove each went missing from it.
10. **`conftest`'s truncation reaches only what a user owns.** `_TABLES` is
    `("professional_profiles", "users")` and relies on `CASCADE`, so the **knowledge tables are
    never cleared** — the corpus is deliberately not owned by a user. Any test that ingests the
    real corpus and *commits* must clean up after itself, or its rows become the silent fixture
    for every retrieval test that runs afterwards.
11. **Assert on the record your code emitted, not on any record.** A gate for "the command logs its
    report in `extra`" passed against a command that interpolated it into the message, because the
    *use case underneath* logged the same fields. Filter by logger name.
12. **A measurement harness needs the same drills as production code**, and its assertions are
    where they live. A measurement that cannot refuse a mocked arm, an empty corpus or a fallback
    is a number with no claim attached.

---

## Conventions

- **Frontend**: Next.js 16 App Router, TypeScript 7, Tailwind 4 (configured in CSS via `@theme`;
  there is no `tailwind.config.js`), shadcn/ui.
- **Frontend tooling**: **oxlint**, not ESLint — `typescript-eslint` refuses to run against
  TypeScript 7 and `eslint-config-next` imports it at load time, so the whole Next lint preset is
  unusable. Rules live in `.oxlintrc.json`; the rules of hooks are enforced. Type correctness is
  `npm run typecheck` (tsc), which was always more accurate than lint rules approximating it.
  Vitest config is `vitest.config.mts` (ESM); Playwright is separate and needs the stack running.
- **Quality gates**: `ruff format`, `ruff check`, `mypy` strict, `pytest` at ≥80% coverage;
  frontend `lint`, `typecheck`, `test`, `build`. CI runs all of them with `if: !cancelled()` so a
  push surfaces every problem at once rather than one per round trip.
- **Backend gates run on the host, never in the container.** `backend/.dockerignore` excludes
  `tests/`, so an in-container pytest collects nothing and looks like a pass. The frontend's
  production build fails in the container for the same class of reason and succeeds on the host.
- **A gate nobody has watched fail is not a gate.** When adding one, prove it catches something —
  push a deliberate break, confirm the failure is named, then remove it.
- **Verify package versions against the registry before pinning.** Nine versions across this
  project did not exist when first written down. Installing is faster than guessing.
- **A comment beginning `# noqa` is parsed as a blanket lint suppression.** Do not start an
  explanatory comment with that word.

---

## Running it

```bash
cp .env.example .env          # fill SESSION_SECRET and the Google OAuth values
docker compose up -d
```

Then http://localhost:3000. API docs at http://localhost:3000/api/docs.

```bash
docker compose ps                     # what is running and healthy
docker compose logs -f backend        # follow one service
docker compose up -d backend          # apply a .env or compose change
docker compose build backend          # after changing dependencies or the Dockerfile
docker compose down                   # stop; data survives
docker compose down -v                # stop and delete the database
```

Backend checks (from `backend/`, with the venv active):

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy src
```

`pytest` needs PostgreSQL: without it a block of tests skip, skipped tests cover nothing, and the
coverage gate trips. `pytest --no-cov` for a quick unit-only check.

**Two checkouts running the suite at once will corrupt each other unless one is redirected.** The
session fixture runs `DROP SCHEMA public CASCADE`, so a shared database means each run erases the
other's schema mid-flight. The symptom is a scatter of unrelated integration failures whose
**count changes between runs of identical code** — which reads as a flaky suite and has already
cost a wrong conclusion about an innocent change. Give each worktree its own:

```bash
CAREERHQ_TEST_DATABASE_URL=postgresql+psycopg://careerhq:careerhq@localhost:5432/careerhq_test_myworktree \
  .venv/bin/pytest
```

The database is created on demand, so a new name needs no setup. **Unset, nothing changes** —
local runs and CI keep using `careerhq_test`.

**It is deliberately not `DATABASE_URL`.** That name already means "the database this application
talks to" and `.env` points it at the *development* database, which holds evaluation evidence that
exists nowhere else; reusing it would let an exported variable drop real data by running `pytest`.
A database whose name does not contain `test` is refused rather than dropped.

---

## Deployment

Railway project `CareerHQ`, three services:

| Service | Role | Public? |
|---|---|---|
| `frontend` | Next.js. Serves pages, proxies `/api/*` to the backend | **Yes** — the only public door |
| `backend` | FastAPI. Reached at `backend.railway.internal:8000` | No |
| `pgvector` | PostgreSQL 18.4 + `vector` 0.8.6. `pgvector.railway.internal` | No — TCP proxy deleted |

Deployment config is version-controlled: `backend/railway.toml` (pre-deploy `alembic upgrade
head`, healthcheck `/api/health/ready`) and `frontend/railway.toml`. Railway reads them from each
service's root directory — **not** from the repository root.

**Environment variables are documented in `README.md` → Deployment.** Three are easy to get wrong
and each failed at least once:

- `DATABASE_URL` must use **`postgresql+psycopg://`** — a bare `postgres://` will not build the
  async engine — and **`PGHOST_PRIVATE`/`PGPORT_PRIVATE`**, not `PGHOST`, which is the public
  proxy. Compose it from `${{pgvector.*}}` references so a password rotation propagates by itself.
- **`PORT=8000` is set explicitly** on the backend. The entrypoint honours whatever a platform
  assigns, which is correct — but the frontend reaches the backend at a *fixed*
  `backend.railway.internal:8000`, so the assigned port has to be pinned or the two disagree.
- `BACKEND_URL` on the frontend is consumed at **build** time. Changing it needs a rebuild, not a
  restart.

**`NEXT_PUBLIC_*` and `BACKEND_URL` are inlined when the frontend is *built*.** Setting one on a
running service is too late — the value is already in the bundle. It needs a declared `ARG`
referenced *inside* the `RUN` line (or a build changing only that variable reuses the cached layer
and ships the previous value), and on Railway it must exist *before* the build. The failure is
silent: the feature does nothing, or every `/api/*` call 500s while pages serve perfectly.

**The corpus is ingested pre-deploy, not at startup**:
`preDeployCommand = "alembic upgrade head && python -m careerhq.ingest"`. The `&&` is the ordering
— `knowledge_chunks` must exist before anything writes to it. **Pre-deploy means once per deploy,
not once per replica**: a startup hook would pay a model load on every container start and let two
replicas booting together race `uq_knowledge_chunks_document_content`, and both failures scale with
replica count, so the configuration that produces them is a scaling change nobody would connect to
ingestion. It is not in `entrypoint.sh` either — a stale *schema* breaks the application, a stale
*corpus* does not (retrieval falls back to the static rubric and records that it did). Locally:
`docker compose exec backend python -m careerhq.ingest`. **Re-run it after editing anything under
`backend/corpus/`**, or the files and the database disagree about what guidance exists — which is
the drift `content_hash` exists to detect, arriving by process rather than by bug.

**`EMBEDDING_MODEL` and the model baked into the image must agree, and today they do not.**
`.env.example` sets MiniLM while the Dockerfile bakes `bge-small`, so the configured model is
downloaded at first warm-up. **Both are 384-dimension**, so nothing raises — ingesting with one
model and querying with the other returns confident nonsense. Changing either side alone breaks
retrieval invisibly.

**Redis is not deployed.** Readiness reports `database ok, cache not_configured, object_storage
ok, ai_provider ok`. Nothing reads a cache yet, and a placeholder would make the application
believe it has one and fail at first use.

**`ai_provider: ok` does not mean extraction works.** It is a construction check by deliberate
design: probing the provider properly would bill a completion on every health check, and this
endpoint is the platform's healthcheck. A key that is present and wrong still reports `ok`.

**Object storage is a Railway bucket**, `careerhq-uploads` in `sjc` — **billable**, and living on
the account rather than in this repository, so it survives between sessions. Credentials:
`railway bucket credentials`; removal: `railway bucket delete`.

**To query the deployed database**, an SSH key is registered as `careerhq-dev-machine`
(`~/.ssh/railway_careerhq`, no passphrase, revoked with
`railway ssh keys remove careerhq-dev-machine`):

```bash
railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway -c '…'"
```

The `PGHOST`/`PGPORT` override is **not optional** — see the `psql` gotcha below.

**Operating rules:**

- **Read which version is live from the commit, never the deployment id.** A rollback creates a
  **new** id carrying the **old** commit.
- **`railway deployment redeploy` is not a rollback.** It redeploys the *latest* deployment, so
  during an incident it restarts the broken version.
- **Deployment status, not CI status, is the honest signal.** A blocked deployment reads
  `SKIPPED`, which is visible only from the deployment record; Actions alone shows a red run
  without saying whether anything shipped.
- **Railway blanks the `message` field** of parsed JSON logs. Structured fields survive; the
  human-readable text does not, with or without `--json`, and the same code logs messages fine
  locally. **Put anything you will need to debug a production problem in `extra={…}` fields.**
  This is silent: the records look well-formed.
- **A passing health check is not evidence the proxy works.** The frontend's check probes `/`,
  which never traverses `/api/*`. Three separate proxy misconfigurations all deployed green.
- **For any "is X exposed" check, speak X's protocol and include a control.** `nc -z` reported the
  database port open because Railway's proxy edge is shared and accepts connections regardless.
- **Declining Google consent cannot be tested without revoking access first.** The OAuth request
  sends no `prompt=consent`, so an already-authorised account is signed straight in. Revoke at
  `myaccount.google.com/connections`.
- **If you change anything in the production Docker stages, build them**:
  `docker build --target runner frontend/`. Compose builds `target: dev` and stops, so the
  `runner` stage was first exercised on the deployment platform — where it failed.

---

## Gotchas already hit

Recorded so they are not rediscovered. Every one of these passed a green suite or a clean-looking log.

### Database and SQLAlchemy

- **`is` against an enum silently never matches a value read from the database.** These are
  `String` columns, so a row loaded in a *fresh* session returns a plain `str`. Tests miss it
  because they pass the session that created the row, whose identity map still holds the enum
  member. **Use `==`, and test any such path through a second session.** Shipped twice; nothing
  raises either time, and the feature simply does nothing.
- **A lazy relationship on a freshly added object raises `MissingGreenlet`.** Async SQLAlchemy
  cannot fetch it outside an awaited context, and it surfaces as a 500 during serialisation.
  Assign collections at construction; routes need `selectinload`.
- **`session.expire_all()` before re-reading** makes the next attribute access do IO
  synchronously, which async SQLAlchemy answers with `MissingGreenlet`. Use an awaited
  `session.refresh(obj)`.
- **`func.now()` is transaction-scoped in PostgreSQL.** Every row written inside one transaction
  gets the same `updated_at`. It is also why an in-flight background task is invisible to other
  sessions: **a status change is not observable until it commits**, so any "what is it doing now"
  display needs a committed transition.
- **A data-modifying CTE's INSERT is invisible to an UPDATE in the same statement.** The UPDATE's
  targets come from the snapshot taken before the statement ran, so it matches zero rows and
  reports success. Use two statements.
- **`create_all` does not reconcile an existing table**, and **`drop_all` emits statements from
  the metadata, not from the database**. `conftest.py` drops the schema for both reasons. **Any
  test that asserts an absence must be watched failing** — one passed against a deliberately added
  column until this was fixed.
- **A `use_alter` foreign key must be named**, or it cannot be dropped.
- **Alembic does not diff check constraints.** A widened enum in Python with the database still
  refusing the new values passes every gate and fails at the first real write. Write constraint
  changes by hand.
- **Postgres 18 images mount at `/var/lib/postgresql`, not `/var/lib/postgresql/data`.** Mounting
  the pg17 path makes the container **exit 1 on startup**; compose reports only `dependency failed
  to start` and the real message is in `docker compose logs postgres`. Changing the tag from
  `pg17` to `pg18` is therefore not a one-line edit.
- **`psql` in the deployed pgvector Console talks to a stranger's database.** The container still
  carries `PGHOST`/`PGPORT` from before the public TCP proxy was deleted, and Railway recycles
  proxy ports, so that address now serves **another tenant's** database. It rejects your
  credentials, which reads as a password problem when it is a wrong-server problem — and **sends
  an authentication attempt to a third party**. Override *both* variables; `su` without a dash
  preserves the environment, so that does not help.

### The agent runtime

- **Any LangGraph state key that a later node returns partially must have an explicit merge
  reducer, or the node must be proven to return the complete value.** A key with no reducer is
  **overwritten**, and nothing raises. Proved twice: `usage` without a reducer kept one record of
  seven — an incomplete audit under Principle V and a cost figure wrong by up to 7× — and `items`
  without one let a Revise delta *replace* the draft's list, silently erasing its drops. A "return
  only what you changed" prompt creates exactly such a partial return.
  `Annotated[list, operator.add]` is required.
- **Usage is lost if it is only summed after the graph returns.** A graph that raises does not
  return. `ExtractionFailedError` carries the usage it was billed for and `UsageRecorder` wraps
  the seam, so a failed run records what it spent rather than reporting `$0` — which reads as free.
- **`dataclasses.replace()` on a Pydantic model** does not work; use `model_copy(update=...)`.
- **`Model.__new__()` to build an unsaved SQLAlchemy instance** bypasses instrumentation; the
  first `setattr` fails with `'NoneType' object has no attribute 'set'`.
- **The retrieval token ceiling budgets rule text, not the rendered block.**
  `KnowledgeChunk.token_count` counts the rule; `prompts.py` renders `- {text}  [{source}]`, and
  the citation (`slug · locator · hash`) is uncounted. Measured: a ceiling configured at 1,500
  reaches the model at **~2,190 tokens**, of which **667 are citations**. This was the whole of why
  **SC-008 (006)** first missed, at 2.12%; T052 removed the citation from the prompt and the
  numerator fell 21%, yet the criterion is **still MISSED, now at 3.22%** — because the denominator
  nearly halved when that session's baseline did not revise. An accounting discrepancy rather than a
  retrieval defect; see T052 before changing either side, because FR-012's resolvability rests on
  the citation.
  **Write it `SC-008 (006)`.** Slice 007 has an `SC-008` of its own asking a different question —
  whether the measurement can resolve its own threshold — and the two are one careless sentence
  away from reading as an old figure and a corrected one. Slice 006's threshold is unchanged at
  ≤2% and its result is 3.22% MISSED.
- **Run cost is dominated by whether the Reviewer revises**, which is a step function worth an
  extra Sonnet call plus an extra Opus call — roughly a third of a run. Measured spread across
  runs of the same pipeline: **$0.295 to $0.548, 85%**. **A single A/B on total cost cannot
  resolve a small percentage**, and one that appears to is measuring the revision loop. Compare
  the controlled part instead: the `tailor_plan` call differs between two arms only in what you
  changed.
- **`langgraph-checkpoint` is a hard transitive dependency.** What is declined is
  `langgraph-checkpoint-postgres`, a **separate** package.

### Frontend

- **An undeclared Tailwind theme colour generates no rule and no warning.** `bg-primary` computed
  to `rgba(0,0,0,0)` and every default `<Button>` rendered as bare text for three slices — a
  passing build, tsc, lint and the whole suite ask whether a class name exists, never whether it
  *resolves*. **`@theme inline` is required, not `@theme`**, or values freeze at compile time and
  dark mode never applies.
- **An undefined CSS custom property fails silently and differently per property.** `var(--fg)`
  written for `--foreground`: three uses were `color:`, which inherits, so they looked correct by
  accident; the fourth was `fill:` and rendered black text on a dark ground.
  `frontend/src/components/__tests__/tokens.test.ts` requires every token to be declared.
- **Build a CSS reveal so that *removing* the animation lands on the finished state.** The
  reduced-motion rule collapses animations to 0.01ms. If the base style is the empty state and the
  animation draws it in, every user who reduces motion sees zero. Put the final value in the
  element's style and let the keyframe supply only the start. **The inverse applies to
  indeterminate progress**: a full ring resting still reads as a finished run, so it must rest on
  a partial arc.
- **Local component state survives a route change.** React keeps a component across a navigation —
  same component, same position, different record. Key polled tabs on the record id.
- **Next.js dev mode 403s its own chunks when the browser is on `127.0.0.1`.** The page renders and
  nothing hydrates, with no console error. Use `localhost` in a browser. This is the *opposite* of
  the Playwright rule below, and both are real.
- **Playwright must target `127.0.0.1`, not `localhost`.** Node resolves `localhost` to `::1`
  first while Docker publishes IPv4 only, which surfaces as `ECONNREFUSED ::1:3000` against a
  stack that is demonstrably running.
- **A stale "not built yet" marker is worse than a missing one.** A disabled button titled
  "arrives in the next release" sat directly above the working feature.

### API and routes

- **`app.routes` no longer contains included routers.** FastAPI 0.141 wraps them as
  `_IncludedRouter` with no `path`. Enumerate from `app.openapi()["paths"]`, which is what a client
  can reach — **and assert how many you examined**.
- **A stuck run must stay recoverable.** An in-flight guard that answers 409 to the one action that
  recovers it needs hand-written SQL to clear, three times.
- **A pointer written only on success hides a run in flight.** Prefer an in-flight row — but
  **only while it is plausibly in flight**, or an abandoned row replaces a good result with
  `failed` for a run nobody will finish.
- **`api/routes/__init__.py` is not where routers are registered.** It is empty; every router is
  included in `main.py`'s `create_app`.

### Environment and tooling

- **`docker compose restart` does not pick up `.env` changes.** Environment variables are injected
  when a container is *created*. Use `up -d`, which recreates it. Verify with
  `docker compose exec backend printenv VAR`.
- **`docker compose up -d backend` does not pick up backend *code* changes.** The frontend mounts
  its source and hot-reloads; **the backend mounts nothing** and runs the baked image. Use
  `docker compose build backend && docker compose up -d backend`. The symptom is nasty because
  everything looks healthy — readiness passes, the API answers, and only the *new* behaviour is
  missing.
- **Every checkout of this repo shares one set of Docker volumes.** `docker-compose.yml` pins
  `name: careerhq`, so cloning into a new directory does *not* give a clean database.
  `docker compose down -v` for genuinely empty state.
- **Host ports are configurable** in `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, …). Change those
  rather than editing `docker-compose.yml` when a port collides.
- **`docker compose logs --since` reads host-local time; the app logs UTC.** A silent offset that
  returns the wrong lines and looks like an empty log.
- **A hardcoded listening port is invisible locally and fatal when deployed.** `entrypoint.sh`
  reads `${PORT:-8000}`. Hosting platforms assign a port and probe *that*; the symptom names
  nothing, because the application is healthy and merely unreachable.
- **`request.base_url` is the internal hostname behind the proxy.** Anything browser-facing —
  OAuth redirect URIs especially — must come from `PUBLIC_BASE_URL`.
- **`ModuleNotFoundError: No module named 'careerhq'` from an apparently correct editable
  install** is macOS setting the BSD `hidden` flag on the `.pth` file; Python 3.12's `site` module
  deliberately skips hidden `.pth` files. Diagnose with `ls -lO .venv/lib/*/site-packages/*.pth`,
  fix with `chflags nohidden`. `pytest` no longer depends on this (`pythonpath = ["src"]`), but
  anything invoking the venv's Python directly still can.
- **pydantic's `EmailStr` rejects reserved TLDs**, `.test` and `.invalid` among them. A scratch
  user seeded `someone@example.test` makes `/api/auth/me` return **500**, which surfaces as a
  white-screen page and reads like an application bug. Use `example.com`.
- **A Python replace-script that asserts before writing drops *all* edits when one string misses.**
  A `tasks.md` update was lost this way while the code commit went through. Write each edit
  independently, or verify the file afterwards.
- **A killed `next build` leaves workers behind** that make the next build take minutes and then
  fail on a vanishing temp file. `pkill -f "next-build|processChild"` and `rm -rf .next`.
- **A one-shot `python -m` command needs `run()` split from `main()`.** `asyncio.run` cannot be
  called from inside a running loop, so a command whose only entry point is synchronous can be
  tested *only* by spawning a process — and a suite that spawns one per claim tests almost none of
  them. Put the behaviour and the exit code in an awaitable `run()`, leave `main()` as
  `configure_logging(...)` plus `asyncio.run(run())`, and make the guard `raise SystemExit(main())`
  — a guard that discards the return value exits **0** on every failure.
- **`brew install pango` is necessary and not sufficient on Apple Silicon.** Homebrew's prefix is
  off the dynamic linker's search path and WeasyPrint `dlopen`s GObject at import;
  `tests/conftest.py` sets `DYLD_FALLBACK_LIBRARY_PATH` so a bare `.venv/bin/pytest` works.
- **`gh` is installed but may not be authenticated.** Check `gh auth status` first; an
  unauthenticated `gh` fails in ways that look like a missing repo. Log in with
  `gh auth login -s workflow` — **pushing anything under `.github/workflows/` needs the `workflow`
  scope** or the push is rejected outright. Git itself works independently over HTTPS.
- **`json.load` in strict mode against the GitHub Actions API** breaks on control characters in
  commit messages. Use `strict=False`.

---

## Deliberate non-goals

Do not build these without discussion — each was scoped out for a stated reason, recorded in
`docs/05` §7:

- The from-scratch resume builder and the presentation designer (≈40 settings, demonstrates none
  of the project requirements; import reaches the same data far faster — ADR-013)
- Multi-provider LLM routing (LiteLLM makes it configuration)
- A full WYSIWYG resume editor
- **Automatic retry on a validation failure.** A failed node ends the run. Whether to retry is a
  recovery-behaviour decision, deliberately separated from correctness work.
- **Tuning the Plan or Draft prompts**, until there is a distribution to judge rather than a
  handful of samples.
- **Making `de_emphasise` measurable.** It holds free text with no ids, so "did the draft drop what
  the plan named" is not computable. Fixing that means changing the Plan schema and therefore the
  Plan prompt.

And two things that are **not** optional despite being unbuilt: the evaluation layer (slice 007)
and deployment of the current slice. Evaluation is a graded requirement.
