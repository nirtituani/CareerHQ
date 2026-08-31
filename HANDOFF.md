# HANDOFF

**Last updated:** 2026-08-31 · **`main` @ `32f5be2`** · **every number below was measured by a
command run this session, not carried forward**

**`origin/main` is `32f5be2`** — the merge of PR #17. Production readiness answers **HTTP 200**:
`database ok (18.5 ms) · cache not_configured · object_storage ok (178 ms) · ai_provider ok`.
**Nothing is unpushed anywhere** — `git log --branches --not --remotes` is empty.

Merged this session: **#15** (the Slice 008 handoff, written by a session that has since been
cleared), **#16** (three small follow-ups plus this file's correction), **#18** (the tailor
model-attribution test flake) and **#17** (**T083**, the JobTracker import screen). Earlier: **#8**
(Slice 003 JobTracker import), **#9** (Slice 006 item D), **#10** (the frontend healthcheck),
**#11** (documentation reconciliation), **#13** (per-worktree test databases) and **#14** (Slice
008).

> ⚠️ **The last deployment observed was at `c904380`** (`railway deployment list`, `SUCCESS`,
> 2026-08-30T21:17:35Z). `32f5be2` adds a frontend screen and two documentation changes; **whether
> it has deployed was not checked this session.** Read it from the commit, never the deployment id.

> ## Slice 003 is complete, and so is Slice 005
>
> **T083** shipped in PR #17 and **T084**, **T088** are ticked. All three were verified rather than
> assumed: T084 and T088 against the deployed database on 2026-08-31, T083 in a browser.
>
> **The `tasks.md` disagreement recorded in the previous revision is resolved.** `003` is now
> **109 / 109** and `005` is **101 / 101**. T084's tick had been lost by §4's *"replace-script that
> asserts before writing"*; T088's had been **withheld on purpose** pending a paid production run,
> which is a different thing and is recorded as such in its task. **T047 is now the only open task
> in the project.**

> ## The Railway frontend blocker is FIXED
>
> It had blocked every frontend release since 2026-08-26. The fix was to give the healthcheck a
> target that answers 200 without redirecting: production now probes **`/healthz`** rather than
> `/`, which had been answering 307. The deployment succeeded **on the first healthcheck attempt**.
>
> Verified publicly: `/healthz` -> **200 with zero redirects**, `/` -> **307 to /login** (correct),
> `/api/health/ready` -> **200** with `database ok - cache not_configured - object_storage ok -
> ai_provider ok`.
>
> **Treat this as closed.** No further investigation, no support ticket. The earlier analysis stays
> in §4B as history rather than as an open problem. **The frontend is live**, so every user-facing
> change from slices 006 and 007 has finally shipped.

> ## T088 is COMPLETE — the first real paid production run
>
> Slice 005 is now **101 / 101**. Run `f116683f`, **`succeeded`**, `is_fixture = false`,
> **3m 15.9s**, **$0.312825** — 35,785 input / 18,808 output tokens across three calls. Plan and
> Draft on `claude-sonnet-5`, Review on **`claude-opus-5`** (its configured model, not an
> escalation). **No revision**: `attempts = 0`, confidence 84, one `overstated` and six `uncovered`
> findings, and **no `ungrounded`** — so the discard path still has no production exercise.
>
> **The first production proof that retrieval works.** `guidelines_used` holds **28 real corpus
> citations across 9 documents**, not the `StaticGuidelines` constant, and **all 28 content hashes
> resolve to live `knowledge_chunks`** — FR-012's resolvability verified against real data. 15 of
> the 28 rules come from integrity documents (the mandatory inclusion working), and the Israeli
> market rules were hoisted for an Israeli employer.
>
> ⚠️ **The interface reports one model for a run that used two.** The UI showed
> `anthropic/claude-sonnet-5` while the Review call ran on Opus at 5x the input price. Cosmetic,
> but it understates cost attribution.

> ## Slice 006 item D is COMPLETE
>
> `verify_corpus_ingested()` re-reads the corpus files and re-queries the database after ingestion,
> refusing an empty or incomplete result. The existing pre-deploy exit code now gates the
> **outcome** as well as the ordering, with **no Railway configuration change**. Confirmed in
> production's own pre-deploy log: `chunks_expected=79 chunks_present=79 changed=false`.
>
> Before this, that log read `0/0/0/0` — indistinguishable from the `75cd8ea` failure where the
> corpus was empty. **It does not catch ingestion never running at all**; that remains what T048's
> configuration test is for.

> 🔴 **Paid evaluation evidence still lives in two local Docker volumes** — $3.562567 from slices
> 004–006 and $4.925403 from the Slice 007 benchmark, plus **$0.352047 now in production** (the
> match analysis and the T088 run). The local backup is dated 2026-08-29, **predates the two T052
> arms and the whole Slice 007 benchmark**, and sits **on the same machine**. See §5A.
>
> **Slice 007's results are the exception and are safe**: they are committed *files* under
> `specs/007-evaluation-benchmark/results/`, so they survive `docker compose down -v`. The
> tailoring rows behind them do not.

> ## Slice 008 is COMPLETE, merged and production-validated
>
> Merged as **PR #14**; `origin/main` is **`e6335bc`**. Not "locally validated", not "unbacked" —
> it is on `main`, deployed, and has produced real research against a real company in production.
> The earlier ownership fence around `research_*`, `citation_check.py` and `ports.py` is **gone**;
> those files are ordinary `main` code now.
>
> **The whole chain works, end to end:**
>
> ```
> Tavily search -> SearchHit (url/title/snippet, no body) -> SourceFetcher
>   -> the shared SSRF-guarded fetch -> Gemini synthesis -> verify_excerpts -> persistence
>   -> API -> the Company tab
> ```
>
> **`gemini/gemini-3.6-flash` is the production default, deliberately** (OQ-J). Chosen on
> measurement across four frozen fixtures with `verify_excerpts` as judge, not on price: its
> citation rejection rate is **1.7%**, against 18% for Step 3.7 Flash and **42%** for GPT-OSS-20B,
> whose fabrications only the verbatim check caught. Claude Sonnet 5 stays denser and is **one
> setting away** — `llm_model_research_synthesise_company` — with nothing provider-specific
> anywhere above `infrastructure/`.
>
> **`v2-dense` is the shared synthesis prompt**, for every model rather than for Gemini. Density
> was a prompting problem: the old text said "summarise" and never said how much to extract. The
> extraction block and the anti-fabrication block were validated **together** and must not be
> separated — the first raises density, the second is why that did not become invention. Exact text
> in `specs/008-company-research/contracts/optimised-synthesis-prompt.md`.
>
> **Production validation, 2026-08-30, against Cloudflare:** 22 claims (20 `fact`,
> 2 `interpretation`), 5/5 sections, 25 evidence entries, **0 uncited facts and 0 unknown source
> ids**. Six source rows persisted — **three retrieved and three recorded as failed** (GlobalData,
> Yahoo Finance, Gartner all refuse automated access), which is FR-009 holding on real data: the
> brief is honest that half of what it consulted could not be read. Citations render in the browser
> as verbatim quotes with clickable links, and failed sources are shown as unreadable rather than
> hidden.
>
> **Reuse verified in production and it does not spend again.** A second request returned the same
> `snapshot_id` with `reused: true`; snapshot count, total cost and source-row count were all
> byte-identical afterwards. That is FR-013's economics — Layer 1 paid for once per employer —
> confirmed on the ledger rather than from the response body.
>
> **Layer 2 role research remains built-but-unwired.** `research_role.py`, its schemas and
> `role_research_snapshots` all exist and are tested against doubles. **There is no route and no
> UI**, and nothing in production reaches it.

> **Implementation priority: Correctness → Simplicity → Efficiency → Course requirements.** Do not
> add agent/ReAct complexity to look more agentic.

---

## 1. Core goal

CareerHQ is an AI-powered career intelligence platform. A user imports a CV, tracks applications,
and an agent tailors the resume to a specific job description — **with the user's approval on
every change**.

Built solo as a course project on a four-to-six-week budget. Two things are graded requirements and
are not optional: **deployment** (slice 002, done) and the **evaluation harness** (slice 007, not
started).

The seven non-negotiable principles are in `.specify/memory/constitution.md`. Violations of II–IV
are release blockers.

### The roadmap was renumbered on 2026-08-22

Build order now matches slice numbers. **Counts measured this session** with
`grep -cE '^- \[[xX]\]'` — see §2 for the case trap that makes the obvious command wrong.

| | Slice | State |
|---|---|---|
| 005 | **Resume Tailoring** | **100/101 — built, exercised on real jobs, deployed.** T088 open on purpose |
| 006 | **Document & Retrieval** — RAG over guidelines, PDF export, submit-and-lock | **50/56 — built and green; undeployed** |
| 007 | **Evaluation & Benchmark** — harness, synthetic benchmark, metrics, judge, paid pass | **50/50 built; 48 ticked, 2 partial. GRADED. Paid benchmark RUN: $4.925403 of a $10 ceiling** |
| 008 | Company Research | In progress in a **parallel session**; droppable (`docs/08` §11) |
| 009 | Career Advisor | Not started. Droppable |

**Evaluation has been deferred twice and two slices stand in front of it.** If the budget runs
short, 008 and 009 are what get dropped. Recorded in `docs/05` §5.7 in those words.

**The 005/006 boundary is structural and it held.** RAG is an *input enhancement* via the
`GuidelineSource` port, not a redesign of the tailoring workflow. Slice 006 swapped
`StaticGuidelines` for a retrieval implementation and changed **no node, no state key and no
finalisation rule** — `run_tailoring` was not edited at all, so FR-029 needed a test rather than a
change. `application/guidelines.py`'s docstring is the argument; it also explains why the port
deliberately has no `top_k`, no scores and no embedding parameters.

---

## 2. Current implementation status

**Everything here was measured on 2026-08-29 by a command run in this session.**

### Slice task counts

| Slice | Done / total | Open |
|---|---|---|
| 001 platform-foundation | 69 / 69 | none |
| 002 deployment | 52 / 52 | none |
| 003 data-foundation | **109 / 109** | none — **T083 and T084 done 2026-08-31**, see the header |
| 004 match-analysis | 89 / 89 | none |
| 005 resume-tailoring | **101 / 101** | none — **T088 ticked 2026-08-31** against the deployed run |
| 006 document-retrieval | **57 / 57** | none |
| 007 evaluation-benchmark | **49 / 50**, T047 marked `[~]` | **T047** — built and isolated, deliberately unpopulated |
| 008 company-research | **no `tasks.md`** | **COMPLETE and merged** (PR #14). Never went through `/speckit-tasks`, so it cannot be counted — a process gap, not open work. **Layer 2 is built and tested against doubles but has no route and no UI**, and is deliberately *not* scheduled |
| **Total** | **526 / 527** | **1 — T047**, and it is open by choice rather than by omission |

**The two totals the previous revision carried are now one.** It recorded "as ticked" and "in
reality" separately because `T084` and `T088` were done but unticked; both are ticked, so the
figures agree again. That entry is kept in §4 rather than deleted — the reason they diverged is
worth more than the fact that they did.

> ⚠️ **Count these with `grep -cE '^- \[[xX]\]'`.** Slice 005 marks **100** of its 101 done tasks
> `- [X]` with a **capital X** while every other slice uses lowercase, so `grep -c '^- \[x\]'`
> reports **1 / 101** for a slice that is complete. The one lowercase entry is **T088**, ticked on
> 2026-08-31 — so the file is now mixed-case, and the trap is easier to fall into, not harder.

### Live system — deployed and verified

**All measured 2026-08-31** — production over `railway ssh --service pgvector`, local over
`docker compose exec postgres`.

| | Production | Local |
|---|---|---|
| Commit | **`c904380`**, backend *and* frontend `SUCCESS` | `c904380` |
| Alembic head | **`0019_company_research`** | **`0018_corpus_embedding_model`** — one behind |
| knowledge documents / chunks | **18 / 79** | 18 / 79 |
| Readiness | **HTTP 200** — `database ok 18.5 ms · cache not_configured · object_storage ok 178 ms · ai_provider ok` | — |
| users | **1** | 24 |
| applications / companies | **97 / 90** | 33 / — |
| match analyses | **1** | 31 |
| resume_versions | **1** | 31 |
| company research snapshots | **0** — and that is correct, see below | 0 |

**Local is one migration behind production.** `0019_company_research` shipped with Slice 008 and
has not been applied locally. Run `docker compose exec backend alembic upgrade head` before
trusting any local research work; nothing else is affected.

**Local counts are inflated by benchmark rows and are not comparable to production.** The Slice 007
harness seeds users under `google_sub LIKE 'benchmark|%'`; the 24 users and 31 versions are mostly
those. §5A's protected records are the subset that matters.

**Production's 0 research snapshots is not a failure.** Slice 008 *was* validated end to end
against Cloudflare; the verifying session then deleted its temporary user and that user's snapshot
and source rows, per §6's *"delete anything seeded by hand"*. Its note records the real account's
**97 applications and 90 companies** counted before and after and unchanged — **independently
re-measured this session and matching exactly**. Read the 0 as the cleanup rule working, not as
the feature failing.

**Local and production disagree about the embedding model, and that is expected.** Local `.env`
sets MiniLM, the image bakes and production uses `bge-small`. The local corpus was embedded with
MiniLM (measured: cosine **1.000000** to MiniLM, **0.345992** to bge-small) and records NULL,
because it predates migration `0018`. T053's guard treats NULL as *unknown*, warns once and
proceeds. **Every local measurement — SC-007, SC-008, retrieval quality — was taken on MiniLM.**

### Tests — run this session

| Suite | Result |
|---|---|
| Backend, local on `c904380` | **1,232 passed**, coverage **87.52%** (gate 80%) |
| Frontend, local on `32f5be2` | **207 passed**, 14 files |
| CI on `32f5be2` | **success** — Backend and Frontend both |
| `ruff format` / `ruff check` / `mypy` | clean — 273 files / all checks / 102 source files |

**The backend figure is from `c904380` and still stands**: nothing since has touched `backend/`,
which was verified byte-identical rather than assumed. The frontend gained 12 tests with T083.

**The old 831-vs-785 gap is gone**: it was Slice 008's untracked test files, which are now on
`main`. Local and CI measure the same tree again.

**The frontend suite is no longer flaky.** `tailor.test.tsx > "names every model a run used"` had
been failing **5 runs in 20** — it waited for the version fetch and then asserted on the *run*, two
effects that resolve independently. PR #18 wrapped the assertion in `waitFor`: **0 in 20** after.
No production code changed.

### Success criteria

| | Result |
|---|---|
| **SC-007** | **MET** — p50 12.1 ms / max 24.8 ms against 500 ms (T044, not re-measured today) |
| **SC-008** | **MISSED — 3.22%** against the unchanged **≤2%** threshold |

**SC-008, re-measured at T052 on current code**, two fresh paid arms, one application
(`2c36feee`), one process, one pricing window, neither revising:

| | static `aae6f565` | retrieval `1070657e` |
|---|---|---|
| total cost | **$0.233124** | **$0.245262** |
| `tailor_plan` | 7,221 | 8,936 → **+1,715** |
| `tailor_draft` | 7,816 | 9,855 → +2,039 |

**+3,754 tokens × $2.00/MTok = $0.007508 ÷ $0.233124 = 3.22%, MISSED against ≤2%.** Paid this
session: **$0.478386**.

**Two arms were needed, not one.** T052 removed the citation from the *static* rubric too, so the
old baseline `e70ecd76` sent guidance current code does not — a **207-token** provider-measured
difference. A one-arm comparison would have credited retrieval with that saving.

**The 1.68% against `e70ecd76` is not a pass.** That run revised (5 calls); both arms here did not
(3 calls). It is not the same-session measurement and must not be recorded as one.

**The fix worked and the metric still does not resolve.** The numerator fell 21% and is now
provider-measured on both sides, yet the same-session verdict worsened 2.12% → 3.22% — missed
before the fix and still missed after it — because the
denominator nearly halved. SC-008 divides a fixed per-run overhead by a total run cost that varies
2.7× with revision behaviour, so it cannot establish the overhead's position relative to the
threshold **independently of revision count**. **No target was adjusted and no metric redefined.**

**Re-derived free at R16 (2026-08-31), and the miss is robust.** `specs/006-document-retrieval/`
`research.md` §R16 reads both arms back out of the database, spending nothing. It settles three
things. The retrieval ceiling **is** honoured — 1,497 rule tokens against a configured 1,500 — so
there is **no implementation defect** behind the number. `tailor_review` grew **+670** input tokens
while consuming no guidance at all, so the numerator was already mixing overhead with the
*downstream effects* of better guidance. And the recorded **3.22% MISSED** figure is the narrower
`plan+draft` input-token proxy, where SC-008 (006) as written says *cost per run* — directly
observable as `$0.245262 − $0.233124`, which is **5.21%** of the same-session baseline.
**Both figures miss the ≤2% threshold**, so correcting the accounting makes the verdict worse
rather than rescuing it. The target was itself calibrated against `spec.md`'s estimate of *"+1,000
input tokens across the two calls"*, against a measured guidance delta of **1,165 per call — 2,330
across the two**, roughly 2.3× the arithmetic the threshold was set on.
**No metric redefined, no threshold moved, no test altered, no production behaviour changed.**

---

## 3. Files modified

### This session (2026-08-31) — `e6335bc..32f5be2`

Regenerate with:

```bash
git diff --name-status e6335bc..32f5be2
git log --oneline e6335bc..32f5be2
```

**Thirteen files across four PRs** — **#15** (docs only), **#16** (three small follow-ups),
**#18** (one test assertion) and **#17** (T083). The seven below came from #15/#16; T083 added six
more, listed with the slice-003 work rather than here.

| File | Why |
|---|---|
| `api/routes/imports.py`, `api/routes/applications.py` | `HTTP_413_CONTENT_TOO_LARGE`. One line each; they **must** move together because the second imports `MAX_UPLOAD_BYTES` from the first |
| `tests/unit/test_architecture.py` | The new gate. Reads `starlette.status.__deprecated__` **at run time**, so it covers all four deprecated names and any future one |
| `components/applications/tailor-tab.tsx` | `modelsUsed()` — the provenance line names every distinct model from `run.models` |
| `components/__tests__/tailor.test.tsx` | `renderTabWithRun` — the fixture that made the line testable at all |
| `specs/006-document-retrieval/research.md` | **R16**, the free re-derivation of SC-008 (006) |
| `HANDOFF.md` | This file |

**T083's six files** (PR #17), all frontend plus one task record:

| File | Why |
|---|---|
| `lib/api.ts` | `importJobtracker()`, `JobtrackerImportReport`, `MAX_IMPORT_BYTES`. Uses `fetch` directly rather than `request()`, because a `FormData` body must not carry a hand-set `Content-Type` |
| `app/applications/import/page.tsx` | The route. Under `/applications`, **not** beside `/import`, which is the CV extraction flow and shares nothing but the word |
| `components/applications/jobtracker-import.tsx` | The flow and the four-outcome report |
| `components/applications/applications-page.tsx` | The Import entry point, secondary to Add Application |
| `components/__tests__/jobtracker-import.test.tsx` | 12 tests |
| `specs/003-data-foundation/tasks.md` | T083 and T084 |

**Nothing under `backend/src/careerhq/domain/` or `application/` changed**, and no migration was
added — `backend/` was verified byte-identical to `main` at each step rather than assumed. The
deployed schema moved only because Slice 008's `0019` shipped in PR #14, before this session.

### Slice 006 (earlier) — regenerate with

```bash
git diff --name-status 1cf9a70~1..HEAD -- backend/src frontend/src
git log --oneline 1cf9a70~1..HEAD
```

`1cf9a70` is slice 006's first commit. **Twelve commits on the branch**, all pushed and CI-green:

| Commit | What |
|---|---|
| `01030f6` | **T052 docs** — SC-008 re-measurement recorded. **Not on `main`** |
| `2f0ba29` | **T048** — corpus ingestion in the Railway pre-deploy |
| `1c11ad5` | **T056** — the sent résumé, on the Details tab |
| `5601c3f` | **T055** — CI gets production's renderer |
| `94955af` | **T053** — the corpus records which model embedded it |
| `aad97a6` | **T052** — prompt citation decoupled from the recorded snapshot |
| `c64b9c9` | **T051** — role context snapshotted; grouped Experience |
| `941eac4` | **T054** — the tailor screen's dead controls and silent refusals |
| `bf4bbcd` | font timestamp pinned, so a re-export is byte-identical |
| `5d666fa`, `0c5ed56` | embedding-model test determinism; submission-refusal transaction |
| `1cf9a70` | retrieval, export and submission — the slice but deployment |

### Read these first

| File | Why |
|---|---|
| `backend/railway.toml` | The T048 fix and the reason it is `/bin/sh -c`. **`preDeployCommand` is a single command**; Railway's schema types it as a string or a one-element array, so a bare `&&` runs only the first half |
| `application/immutability.py` | The two locked states, and why `READY` is not one |
| `application/ingest_corpus.py` | T053's guard: refuses a model swap before embedding or writing anything; NULL means unknown |
| `application/export_resume.py` | `_role_groups` — role order is snapshotted `role_ordinal`, bullet order is `position` within a role |
| `agents/tailoring/prompts.py::_guidelines` | T052: rule text only; the citation lives in `guidelines_used` |
| `specs/006-document-retrieval/tasks.md` | Every decision, drill and finding, per task |

### By layer

- **Backend application** — added `embeddings.py`, `export.py`, `export_resume.py`,
  `immutability.py`, `ingest_corpus.py`, `retrieved_guidelines.py`, `submissions.py`,
  `submit_resume.py`; modified `guidelines.py`, `tailor_resume.py`,
  `agents/tailoring/prompts.py`
- **Backend domain** — added `models/knowledge.py`, `schemas/document.py`; modified
  `models/tailoring.py` (role-context columns), `models/__init__.py`
- **Backend infrastructure** — added `corpus/loader.py`, `documents/render.py`,
  `embeddings/fastembed_source.py`, `ingest.py`; modified `config.py`, `main.py`
- **Migrations** — `0015` corpus, `0016` export/submission, `0017` role context, `0018` corpus
  embedding model. All four applied in production
- **Deployment** — `backend/railway.toml`, `.github/workflows/ci.yml`, `.env.example`, `README.md`
- **Frontend** — `tailor-tab.tsx`, `tailor-diff-item.tsx`, `detail-tabs.tsx`, `lib/api.ts`

### Not in this list, deliberately

`application/ports.py` and every `research_*` module were Slice 008's, and are **now on `main`**
(PR #14, `e6335bc`). The ownership fence is gone; they are ordinary code. Listed here only because
an earlier handoff fenced them off and someone reading that sentence out of context would still
avoid them.

---

## 3a. Slice 008 — open caveats that ship with the current default

Neither is a defect to fix in passing. Both are decisions someone must make deliberately.

**Gemini's free tier may use submitted content to improve Google's products.** That is acceptable
for Company Research **because that path reads public company web pages only** — no CV, profile or
application data reaches it, and the Layer 1 schema has no field one could arrive through. **This
must not be generalised.** Pointing anything profile-shaped at a free-tier key is a separate
decision with a different answer, not a configuration change.

**LiteLLM records Gemini's paid-rate equivalent, not the actual free-tier charge.** The production
Cloudflare run recorded `cost = 0.058972` against a bill of **$0**. That figure is the Principle V
audit record, written in the same transaction as the work, and the same number feeds slice 007's
spend ceiling — so a budget guard can refuse runs that cost nothing. **Left open on purpose**: it
needs a decision about whether `Usage.cost` should carry the amount billed or the paid-rate
equivalent, and either answer changes what historical rows mean.

---

## 4. What failed

The expensive part of this project's memory. **Append-only — never delete an entry.** Each of these
was tried and did **not** work; re-attempting any of them costs real time.

### Gates that were not gates (slice 005 — three of them, all shipping green)

- **`app.routes` stopped containing included routers.** FastAPI 0.141 wraps them as
  `_IncludedRouter` objects with no `path` attribute at all. `test_every_non_public_route_requires_a_session`
  walked `app.routes` and skipped any path containing `{`, so it matched only `/api/docs` and
  `/api/openapi.json` — both public, both skipped. **The gate was examining zero routes and
  passing**, and had been since slice 003 added the first parameterised route. Enumerate from
  `app.openapi()["paths"]`, which is what a client can actually reach, **and assert how many you
  examined** — the count is the only part that would have caught either failure.
- **An undeclared Tailwind theme colour generates no rule and no warning.** `src/components/ui/` is
  shadcn, written against `bg-primary`, `bg-accent`, `border-input`, `ring-ring`. None were declared
  in `@theme`, so `bg-primary` computed to `rgba(0, 0, 0, 0)` and **all twenty default `<Button>`s
  in the application rendered as bare text**, for three slices. It survived a passing build, tsc,
  lint, 130 tests and the existing `var(--token)` scan, because none of them ask whether a class
  name *resolves*. It survived human use because `outline` and `ghost` are *meant* to be
  transparent — two variants of three looked perfect. Found by opening the Tailor tab in a browser.
  `@theme inline` is required, not `@theme`, or the values freeze at compile time and dark mode
  never applies.
- **A `-k` selector that matches nothing reports a cheerful pass.** Drilling the disclosure gate
  with `-k leak` selected **zero** tests and printed no failure; it read as "the drill did not
  fire". The test name did not contain "leak" — a fixture argument did. **Read the
  `N deselected` count**, always.

### Slice 005 — the two paid failures, and what each cost

Both were the **same field** and **different root causes**, one below the other. Re-reading them in
order is the cheapest way to understand why the id plumbing looks the way it does.

- **Fixing a contract's *visibility* when the value never existed.** The first failure was
  `ReviewFinding` requiring `source_item_id` while the JSON Schema advertised it optional — real,
  and fixed by putting the rule in `Field(description=...)`. The second failure was the same
  field: the ids **never entered the prompt chain at all**. `_render_master` returned `(text,
  items)` and only `text` reached the state, so Draft was told to return items "by id" while being
  shown 2,801 characters of profile and zero ids. Cost: **$0.361819** for the second failure alone.
  The quieter consequence was worse — with no ids nothing maps back, so a run that *passed* review
  would have persisted a diff with **zero proposed changes**.
- **Believing a fix was complete because the layer I could see was fixed.** The lesson is not
  "check the prompt"; it is that a diagnosis which explains the symptom is not necessarily the
  bottom of the stack.
- **Showing the Reviewer the diff and asking a document-level question.** `uncovered` asks what the
  *resume* fails to address; it was handed only the changed items. On Zipher it reported eight
  requirements "never addressed" against bullets sitting untouched in the resume, naming the exact
  ids it believed had been omitted. That is what drove the run into a revision, and to $0.46.
- **Two of my own tests were wrong, both caught only by drilling.** One demanded a rewritten item's
  *original* wording, which another test correctly forbade. The other searched the whole prompt for
  text the master also contains, so it passed with the fix reverted.
- **Collapsing two questions into one guard.** Making `scoreable_posting` the sole gate for Match
  broke FR-006: a description with an empty requirement list became scoreable. "Is scoring
  meaningful" and "is there anything to send" are different questions. The existing suite caught it.
- **Asserting an equivalence where only an implication holds.** Content is *necessary* for an
  analysis to be reserved, not *sufficient*. Asserting `==` hid the FR-006 break for one commit.

### Slice 005 — the agent runtime

- **Assuming a LangGraph state key accumulates.** It does not. A key with no reducer is
  **overwritten**, measured against the installed 1.2.11. Applied to `usage` that keeps **one**
  record out of seven — an incomplete audit under Principle V, a cost figure wrong by up to 7×, and
  *nothing raises*. `Annotated[list, operator.add]` is required.
- **Believing the import guard covered the application layer.** It forbade exactly one package,
  `litellm`. Adding LangGraph made it actively worse: `langchain-core` arrives transitively, so
  `langchain_anthropic` became one install away, and the idiomatic LangGraph example binds a model
  *inside the node*. Now six packages.
- **Believing anything asserted "no call site loops".** Nothing executable ever did, and as of this
  slice the claim is **false** — the graph loops by design. Corrected in `ports.py` and `CLAUDE.md`
  (T081, T082). The real guard is the import-graph test.
- **Thinking the checkpointer could be avoided.** `langgraph-checkpoint` is a hard transitive
  dependency. What is declined is `langgraph-checkpoint-postgres`, a **separate** package.
- **`dataclasses.replace()` on a Pydantic model.** `DraftedItem` is a `BaseModel`; use
  `model_copy(update=...)`.
- **A table-driven loop over `(model, kind, accessor)` tuples** in `_render_master`. Three lines
  shorter and completely untypeable. Written out explicitly.
- **`TailoringRun.__new__()` to build an unsaved instance.** Bypasses SQLAlchemy's instrumentation;
  the first `setattr` fails with `'NoneType' object has no attribute 'set'`.
- **A module-level `pytest.mark.asyncio`** in a file that is half pure functions. It fails the sync
  tests outright — and warns rather than fails when the function is `async def` but not awaited.
- **`session.expire_all()` before re-reading.** The next attribute access does IO synchronously,
  which async SQLAlchemy answers with `MissingGreenlet`. Use an awaited `session.refresh(obj)`.
- **`json.load` in strict mode against the GitHub Actions API.** Control characters in commit
  messages break it. `strict=False`.
- **A delta contract executed as a replacement** (found by §5B, 2026-08-26). `_REVISE` instructs
  "Return only the items you are changing"; `state.items` has no reducer, so the Reviser's partial
  return *replaced* the draft's list and silently erased its drops — see §2 concern 7. The same
  reducer lesson as `usage` above, missed on a second key: any LangGraph state key a later node
  returns *partially* must either carry a merge reducer or be proven whole.

### Slice 005 — the routes and the interface

- **`is` against a `String`-column enum, again.** `approve_version` compared
  `item.decision is ProposalDecision.PENDING`. Items loaded by a route come from a session that did
  not write them, so `decision` is a plain `str` and the branch never fired: **approval silently
  accepted nothing.** This is the identical defect slice 004 shipped in `run_analysis`, invisible
  for the identical reason — the existing tests hold the session that created the row. Use `==`,
  and exercise the path through a second session.
- **Returning the stringified exception to the client.** `run_tailoring` wrote
  `f"{type(exc).__name__}: {exc}"` into two columns that two endpoints return verbatim and the
  interface renders in an alert, while logging only the class. **The detail went to the browser and
  the type went to the operator** — inverted from the T068 rule in `health.py`. A
  `psycopg.OperationalError` stringifies to the internal IP, port and database user. Found by T090.
- **A data-modifying CTE's INSERT is invisible to an UPDATE in the same statement.** Linking a
  freshly-inserted `tailoring_run` back to its `resume_version` inside one `WITH` chain matched
  **zero rows** and reported success — the UPDATE's targets come from the snapshot taken before the
  statement ran. Two statements.
- **Drilling a test can hit a database constraint before the assertion.** T064's first drill —
  misattributing a finding to an arbitrary row — was refused by
  `ck_reviewer_findings_uncovered_has_no_item`. A stronger answer than the test was asking for, but
  it does not drill the test. Flattening the attachment to `None` is the realistic regression.
- **A Python replace-script that asserts before writing drops *all* edits when one string does not
  match.** The `tasks.md` ticks for T083/T084/T090 were silently lost while the code commit went
  through, because a single em-dash phrase differed. Write each edit independently, or verify the
  file afterwards.
- **A stale "not built yet" marker is worse than a missing one.** The detail header carried a
  disabled `Tailor CV` button titled "arrives in the next release", directly above the working tab.
  The original reasoning — a button that looks live and does nothing is worse than one admitting it
  is not ready — was right while it was true.

### Slice 005 — assumptions about existing code that were wrong

- **`MatchAnalysis` has a `profile_id`.** It does not; only `application_id`.
- **`Application.current_analysis_id`.** It is `current_match_analysis_id`.
- **`MatchRequirement.text`.** The column is `text`, the Python attribute is **`text_`**.
- **A new `ItemDecision` enum.** `provenance.ItemDecision` already exists for the import reviewer.
  The tailoring one is `ProposalDecision`, and the vocabularies differ for a real reason: import
  review *discards*, tailoring *rejects* (the owner's wording stands).
- **`api/routes/__init__.py` is where routers are registered.** It is empty; every router is
  included in `main.py`'s `create_app`.

### Slice 004 — match analysis (every one passed a green suite)

- **`is` against an enum on a value read from the database.** See above; it recurred this slice.
- **A lazy relationship on a freshly added object** raises `MissingGreenlet` as a 500 when
  serialised. Assign collections at construction; the routes need `selectinload`.
- **Demanding a `shortfall` on `unverified`.** A real completion failed validation and the model was
  right: the profile's silence gives no basis for choosing one. The same trap was avoided in advance
  in slice 005 — an `uncovered` finding carries no item reference, enforced by a check constraint.
- **Reporting a cap that did not bite.** `capped_by` named a requirement whenever one *could* cap.
- **`var(--fg)` where the token is `--foreground`.** An undefined custom property fails silently and
  differently per property; three uses were `color:` and looked right by accident, the fourth was
  `fill:` and rendered black on a dark ground.
- **Building a CSS reveal the natural way round.** Reduced motion collapses animations to 0.01ms, so
  a base of "empty" plus an animation that fills it shows **zero** to everyone who reduces motion.
  **Slice 005 needed the rule the opposite way round**: the tailoring spinner has no value yet, so a
  full ring resting still would read as a finished run and an empty one as a failure. It rests on a
  quarter arc and the step name carries the meaning.
- **Trusting `drop_all` against an existing test database.** It emits from the *metadata*, not the
  database. `conftest.py` drops the schema. A `use_alter` constraint must also be **named**.
- **Assuming a stuck run could be recovered.** The in-flight guard answered 409 to the one action
  that recovers it. Hit three times, each needing SQL by hand.
- **Estimating output tokens.** R8 projected ~1,500 and measured **2,811** — 87% low.
- **A score computed independently of the thing it summarises.** v2 asked for four abstract
  dimensions; a real job returned eight requirements addressed and a score of 48 against an honest
  84.
- **Telling a model how to distribute its answers.** *"Most real profiles are mostly `partial`…"*
  made the model push verdicts down to comply.

### Testing (all slices)

- **Trusting the suite to catch display bugs. It never once has.** Contact fields, bullet
  attribution, skill categories, project URLs, and now every button in the application — all found
  by a person looking at real data.
- **`create_all` against an existing test database.** It does not reconcile an existing table.
  `conftest.py` drops the schema first. **Any test that asserts an absence must be watched failing.**
- **Asserting an absence against the wrong scope.** "No rejected toggle on the form" passed against
  a form that had one, because Radix renders dialogs into a portal and `container` was empty.
- **A test double that repeats its last answer.** Would make an unbounded loop look convergent.
  `ScriptedSeam` raises instead.
- **A guard with nothing to examine.** `test_task_model_config.py`'s first AST walk found **zero**
  call sites. Without its own `assert used`, it would have passed forever while checking nothing.
  Three more instances of this class shipped in slice 005 — see the top of this section.
- **Running a test against the real profile.** It merged a fictional CV into it and replaced the
  contact block. **Always use a scratch user**, seeded `@example.com` — pydantic's `EmailStr`
  rejects `.test`/`.invalid` and the 500 reads as a white-screen app bug.

### Deployment

- **`railway deployment redeploy` as a rollback.** It redeploys the *latest* deployment. A rollback
  also creates a **new** id carrying the **old** commit, so read which version is live from the
  commit.
- **A healthcheck pointed at a path that redirects fails, and the failure names nothing.** The
  frontend probed `/`, which answers **307 to `/login`** for a signed-out request — and the
  platform reports that as `service unavailable`, which reads as the container being down. Eight
  consecutive deployments failed this way between 2026-08-26 and 2026-08-30 while the application
  was healthy the whole time. **A healthcheck target must return 200 without redirecting**;
  `/healthz` was added for exactly that and succeeded on the first attempt.
  The corollary is the one that cost the time: **a deployment failure that says nothing about
  cause is not evidence of an application fault.** Several plausible application-level fixes were
  tried and disproved first.
- **Reading Railway logs for a message string.** Railway **blanks the `message` field** of parsed
  JSON logs. Put anything needed to debug production in `extra={…}` fields. This is why T090's fix
  puts `str(exc)` in `extra`, not in the message.
- **`nc -z` to test whether the database was exposed.** The shared proxy edge accepts connections
  regardless. Speak the protocol and include a control.
- **Trusting a green health check to mean the proxy works.** The frontend's check probes `/`, which
  never traverses `/api/*`. **Three separate proxy misconfigurations all deployed green.**
- **Secret-scanning logs for a low-entropy password.** `careerhq` collides with the project name in
  2000 log lines.

### Reading job postings

- **Returning early on schema.org `JobPosting` metadata.** Wrong twice: 1,591 characters of company
  blurb against 9,447 on the page including the requirements.
- **Asking the model to retype the description.** 52 seconds and a proxy timeout, against 5.4s for
  metadata only. **Never ask a model to echo back text you already have.**
- **Reading a page that ships its own template.** Client-rendered boards serve `{{position.name}}`.
  Refuse, do not read.
- **A generic fetch for Comeet.** Needed a vendor adapter.
- **Assuming LinkedIn needs special handling — wrong, repeatedly.** A plain fetch returns 200.

### Product decisions tried the other way first

- **A `rejected` boolean beside the status.** There is no `rejected` column and its absence is a
  release blocker.
- **One overwritten date field.** `date_added` and `date_applied` are separate.
- **Labelling `EXTRACTED` provenance.** Every fact carries it, so the label said nothing. **The same
  reasoning governs the finding-attempt marker in slice 005**: it appears only when an item was
  flagged in more than one review pass.
- **A second render path for grouped skills.** It cost an affordance every time — Edit, then Add,
  then Remove each went missing. **This is why T077 was amended**: Edit is a peer of Accept and
  Reject rather than a field revealed by rejection, so there is one render path.

---

### Slice 006 — dependency and packaging (2026-08-27)

- **`sentence-transformers` is a 527 MB decision, not a library choice.** It was the obvious
  embedder and what `config.embedding_model` originally named. Its cp312 manylinux `torch` wheel is
  **527 MB**, on a backend image already measuring **1.01 GB** — roughly doubling it, for a
  component whose whole job is embedding ~35 short rules and one query string. Caught by checking
  PyPI metadata *before* installing. Replaced with fastembed/ONNX at **67 MB**, same 384 dimensions,
  same port, no migration.
- **"Pure Python" was wrong about WeasyPrint, and the failure is at import.** It binds Pango, Cairo
  and GObject through `cffi`. Without the native libraries, `import weasyprint` dies with
  `OSError: cannot load library 'libgobject-2.0-0'` — which reads as a code fault, not a missing
  apt package. Found by installing, not by reading. Fixed in the Dockerfile and verified **inside
  the built image**, because this project has repeatedly shipped things that worked on the host.
- **The `pgvector` Python package was never installed.** The *extension* has been enabled in the
  database since migration `0001`, which made it easy to assume the Python side existed. It did
  not; `from pgvector.sqlalchemy import Vector` fails.
- **A licence classifier can contradict the licence.** fastembed's PyPI classifier says
  `License :: Other/Proprietary License`; its repository `LICENSE` is Apache-2.0. The file governs.
  Worth knowing in a project that rejected PyMuPDF on licence grounds.

### Slice 006 — research and process (2026-08-27)

- **A "candidate source" arrived as byte-identical copies of a rejected one.** Three reference PDFs
  appeared under `corpus-research/examples/`; SHA-256 matched the assets of register entry S-017,
  rejected because its licence forbids derivative works and dataset use. Verified by hashing
  against upstream rather than trusting filenames.
- **Real CVs reached a public repository's working tree again.** 13 screenshots with real given
  names in the filenames, untracked and *not* ignored — one `git add -A` from publication. The same
  near-miss `CLAUDE.md` already records for `testing files/`. Now ignored.
- **The research digests would have poisoned the corpus if ingested.** They contain "defensible
  estimates when hard numbers are unavailable" and a "70–80% keyword coverage" quota — both direct
  violations of Principle III / AI-008. **Every fabrication-inviting claim traced to the
  SEO/resume-tool tier**; the institutional sources and the best practitioner source (Varun's
  MIT-licensed skill: *"Truth-preserving optimization… Never fabricate experience"*) said the
  opposite. Source authority and integrity correlate — that is itself a triage signal.
- **Thresholds that cannot fail are not gates.** SC-007/SC-008 were first written as 5 s and 10%.
  Retrieval *replaces* the 507-token rubric, so a 1,500-token ceiling adds ~1,000 input tokens
  across two calls ≈ **1.5%** of a $0.400 run, and latency tracks *output* tokens (~92 tok/s) so
  retrieval adds well under 500 ms. Both ceilings were 10–100× too loose. Re-pinned to **≤500 ms**
  and **≤2%**.
- **Four design decisions had no requirement behind them** until `/speckit-analyze` found it — the
  anti-fabrication corpus gate, byte-deterministic rendering, the four Israeli rules, and the
  `market` enum semantics. Tasks derive from FRs, so a decision with no FR becomes a feature nobody
  builds. Added append-only as FR-030–FR-039.
- **`quickstart.md` was never created.** A failed `cd` swallowed the heredoc while the shell still
  reported success, and `plan.md` referenced the missing file for two turns.


### Slice 006 — corpus, loader and retrieval (2026-08-28)

**Four drills passed when they should have failed. Every one meant the test was weaker than its
claim, not that the code was right.** This is now the most common failure mode in this project and
is worth expecting rather than discovering.

- **The chunker-scope drill (F10).** Removing the right-hand boundary — reading "everything after
  `## Rules`" — changed nothing, because prose paragraphs carry no `- ` items and the list-item
  pattern excluded them anyway. The fixture now carries a list item in the preamble **and** in the
  `## Removed` section, which is what makes either boundary load-bearing.
- **The tie-break drill.** Removing the `content_hash` tie-break left `test_retrieval_is_deterministic`
  passing, because PostgreSQL is incidentally stable across two calls in one process. **19 of 79
  chunks share a distance**, so the tie-break is real; a test now asserts tied chunks come back in
  hash order. Incidental stability is not a defined order and does not survive a vacuum or a replan.
- **The topic-intersection drill, twice.** Removing the intersection (hoisting *every* Israeli chunk)
  passed, because the test compared only the relative order of *global* chunks and inserting chunks
  between them does not reorder them. The second draft then demanded no Israeli chunk ever pass an
  unrelated global one — **which no implementation can satisfy**, since outranking a related chunk
  at position 25 means passing everything in between. The test now asserts the *justification*.

**Measurement and estimation**

- **`chars/4` overestimates by 23%.** The corpus measures 4,285 tokens by `cl100k_base` against a
  ~5,540 estimate. Every projection in the spec documents was built on the estimate. Use a real
  tokenizer for anything that feeds a budget.
- **The rubric was never a valid per-rule estimate for the corpus.** 42 tokens/rule came from bare
  imperatives; corpus rules carry their qualifications in-chunk (FR-037) and measure ~54–76. The
  extra tokens *are* the qualifications.
- **Embeddings cannot express "same topic".** See §2 and `research.md` R13. Semantic overlap and
  "makes a conflicting claim about the same decision" are different relations, and the corpus
  contains a clean counterexample to their being the same.

**Alembic and the schema**

- **Autogenerate emitted `pgvector.sqlalchemy.vector.VECTOR` with no import for it.** The generated
  migration raises `NameError` on first upgrade.
- **Autogenerate proposed 11 `server_default=None` strips** across five tables holding the paid
  evaluation data — pre-existing model/DB drift, out of scope, and silently behaviour-changing.
  **It will reappear on every future autogenerate.**
- **Alembic does not diff check constraints.** A widened Python enum with the database still
  refusing the values passes every gate and fails at the first real write. Write them by hand.
- **A new column named `storage_key` broke an unrelated architecture gate.**
  `test_the_uploaded_file_is_read_by_exactly_one_module` finds readers of the uploaded CV **by
  attribute name**. The new columns are `document_storage_key`; widening the gate's allow-list
  instead would have blinded it inside a growing file for ever.

**Dependencies**

- **fastembed's `lazy_load=True` does not defer the download.** Constructing `TextEmbedding` against
  an empty cache fetched 64 MB in 4.8 s. The first adapter therefore downloaded weights in its
  constructor and the unit suite pulled them twice — including a 768-dim model it then rejected.
  The suite was green; the only symptom was 14.75 s.
- **`pyyaml`, `tiktoken` and `types-PyYAML` were transitive-only.** Declared. Depending on somebody
  else's dependency tree is how a working install breaks on an unrelated upgrade.

**Sources and citations**

- **A register entry can be wrong about its own source, and the error creates the problem.** S-009
  was recorded as an *"aggregator of company ladders"* whose *"per-ladder licences differ"*,
  requiring resolution **per ladder before any is used**. It is one author's own three ladders, one
  repository, **MIT** (`sdras/career-ladders`). There was never a per-ladder question. The earlier
  check searched for Creative Commons, did not find it, and recorded absence as risk. **Read the
  licence file.**
- **Decorative citations make unsourced rules look sourced.** `universal-projects-and-education`
  cited S-018 while deriving nothing from it; `universal-structure-and-ordering` held two rules
  S-001 does not support, inheriting institutional standing they had not earned.
- **A sourced *fact* does not make an instruction sourced.** Two ATS rules were removed for this:
  the header/footer claim (S-007 documents which fields parse, never that a header fails) and the
  mixed-script claim (S-006 documents that non-English handling exists, never what to do about it).
  Both files record why, because both are among the most repeated claims in resume advice.
- **Per-document metadata makes the weakest rule wear the strongest tag.** Two practitioner-derived
  Israeli rules inherited `institutional` from sharing a file with S-002's guidance. The fix is a
  file split on trust level — which is why two documents now span two topics.


### Slice 006 — export, Phase 4 (2026-08-28)

- **`status.value` on a `String` column crashed every real refusal, and the unit tests could not
  see it.** `ensure_exportable` was tested only with `VersionStatus` members; a row loaded in a
  session that did not create it comes back as a plain `str`. Membership and `==` survive that
  because `VersionStatus` is a `StrEnum` — **`.value` does not**, and it was in the refusal
  message. The first real HTTP request found it. **This is the third appearance of the enum-vs-str
  trap in this project.** When a function takes a status, test it with the string a row actually
  carries.
- **An error state nobody renders reads as success.** The tailor tab set `error` on failure but
  only displayed it in the start view, so a 409 on the diff screen just stopped the button being
  busy. Silence after a click is indistinguishable from a completed action.
- **Ownership drilled on one route is not ownership.** The export POST had an ownership test; the
  document GET did not, and removing its `_owned_version` call changed nothing. The GET is the one
  that hands over somebody's résumé. **Drill each route, not each feature.**
- **A "no filled panels" assertion could not be written, because WeasyPrint paints a
  `border-bottom` as two filled rectangles spanning the whole element box.** No height threshold
  separates a hairline rule from a shaded panel. The decoration was removed instead, which turned an
  indefensible threshold into an exact property: the page carries no vector objects at all.
- **A single-column check that asserts "no word starts past the midpoint" fails on correct
  documents.** Running text crosses the midpoint on every line. Gutter detection — merge every
  word's x-extent and read the holes — is the property that actually distinguishes two columns; the
  boundary was then set by measurement (correct render 0.0pt, two-column render 39pt), not guessed.
- **A test that greps a whole Dockerfile for a package name passes when the package is deleted**,
  because the comment above the install line still names it. Strip comments and require the package
  to be its own instruction line.
- **Restoring a backup taken before a fix silently reverts it, and a partial test run stays green.**
  Happened during T035's drills. Snapshot *after* the fix, and re-read the source rather than
  trusting a subset run.
- **`session.expire()` then touching the object raises `MissingGreenlet`** — the documented gotcha,
  hit again while fixing a stale relationship in a test. Use an awaited `session.refresh(obj, [...])`.
- **A seeded object's collection is stale in the identity map**, so a use case that re-queries with
  `selectinload` still sees the empty list assigned at construction. The composed document came out
  **empty while two assertions passed anyway**.


### Slice 006 — verification, concurrency and determinism (added 2026-08-29)

- **A test that passes because two things happened in the same second.** The FR-031 byte-identity
  test rendered twice back-to-back with no delay. `fontTools` stamps the embedded font subset's
  `head.modified` with wall-clock time, whose resolution is **one second** — so the test passed
  whenever both renders landed inside one second, *whether or not the bug was present*. It was
  present on every Linux render: **five distinct hashes from eight consecutive renders** in the
  production image. Green on macOS for months, because macOS resolves a different font and
  preserves its original date instead of restamping. **T032 concluded "already byte-identical"
  from the one environment where that is true.** Any determinism test must cross the resolution of
  whatever clock could be involved.
- **The PDF's metadata was the wrong place to look.** `/CreationDate`, `/ModDate` and `/ID` are all
  genuinely absent at WeasyPrint 69 — T032 measured that correctly. The timestamp was one level
  down, inside the embedded font, reachable only by inflating a stream and walking an sfnt table
  directory. Three bytes differed; two were checksums derived from the third.
- **A concurrency test that tested a sequence.** Two `submit_version` calls under `asyncio.gather`
  ran to completion one after the other — the second was refused by the *guard* on an already
  `SUBMITTED` status, never reaching the constraint. Both paths return the same message on purpose,
  so every assertion passed while the raced code path was never entered. Fixed with a barrier in
  the storage double (a racer parked there has passed the guard and cannot have committed) plus
  `assert isinstance(loser.__cause__, IntegrityError)`, which is the only thing that distinguishes
  the two paths.
- **A refusal that poisoned the caller's transaction.** Converting the raced `IntegrityError` into
  `SubmissionRefused` left the session in a failed transaction, so the same exception type meant
  two different things depending on which branch raised it. **`session.rollback()` looked like the
  fix and is worse** — measured: it makes the session usable by destroying the caller's earlier
  uncommitted writes. A savepoint is correct, **but only with the `add` and the status change
  inside it**: wrapping just the `flush()` changes nothing, because writes registered beforehand
  belong to the outer transaction. That form passed every test until one was written for it.
- **A narrowing nothing defended.** Restricting the duplicate-detection predicate to an exact
  `diag.table_name` match broke no test, because the table has exactly one unique constraint and
  every real violation names it. The difference only shows on an input the schema cannot produce.
  Needed a unit test with a synthetic diagnostic, or the tightening was decoration.
- **`litellm` calls `load_dotenv()` at import.** It walks up from the working directory and injects
  the developer's `.env` as real environment variables — `_env_file=None` does not stop it. A
  config test asserting a *default* therefore asserted whatever the machine was configured for, and
  passed or failed on whether an earlier test had imported `litellm` first. Green in a full local
  run, red alone and red in CI, which has no `.env`. **Any test asserting a default must
  `monkeypatch.delenv` the variable.**
- **`docker compose restart` does not pick up a new image.** Cost a wrong conclusion: a verified
  fix appeared not to work because the running container was still the old build. `up -d`
  recreates. (The documented gotcha said `.env`; it applies to images too.)
- **A test fixture written into a table the code under test reads.** The caller's "earlier
  uncommitted write" was an `ExportedDocument`, which `latest_export` then selected as the document
  to submit — `KeyError`. Use a table the path does not consult.
- **`conftest`'s truncation does not reach the knowledge tables.** `_TABLES` is
  `("professional_profiles", "users")` with `CASCADE`, which covers what a *user* owns; the corpus
  is deliberately not user-owned. The first test to ingest the real corpus **and commit** would
  have left its rows as the silent fixture for every retrieval test after it.
- **The browser found three defects the suite could not (T047).** `Accept`/`Reject`/`Edit` render
  on a locked version where every click is a guaranteed 409; the 409 is **swallowed silently**
  because `decide()` has no `catch` while `exportPdf` and `markSubmitted` both do; and the
  submitted view instructs "tailor this job again" while offering no control to do it. The suite
  asserted the *export* controls were absent and that *export* errors render — never the item
  path. **The rule held again: the suite has never once caught a display bug.** Tracked as T054.
- **CI declares no system dependencies at all.** The Dockerfile explicitly declares
  `fonts-dejavu-core` because "which font resolves decides the rendered bytes", and CI installs
  nothing — so the ATS and determinism assertions run against a document production does not
  produce. Tracked as T055.


### Slice 006 — the tailor screen, T054 (added 2026-08-29)

- **A `disabled` prop existed on `TailorDiffItem` and no caller had ever passed it.** Its docstring
  said *"true once the version is `ready`"* — the **wrong** set — and because nothing used it, the
  wrong set was never exercised and never contradicted. A prop with no call site is not a feature
  with a default; it is an untested claim. Found only because T054 went looking for where to add
  the gate and discovered the gate already there, pointed at the wrong states.
- **Gating item controls on `approved` is the plausible over-fix, and it silently breaks FR-029.**
  `approved` is `ready || exported || submitted` and is what the *export* controls use, so reaching
  for it reads as consistency. It removes editing from a `ready` version, which FR-029 requires to
  stay editable and which `docs/03` §10.1 describes as approval *"not a one-way door until
  export"*. It passes any test written only against `submitted`. The guard is a test asserting the
  three controls are **still present** on `ready`; drilled, and it fails by name.
- **The three defects were each invisible to the half of the suite that could have caught them.**
  `tailor.test.tsx` asserted the *export and submit* controls are absent for a submitted version,
  and asserted an error renders for a failed **export** and a failed **submit** — never for a
  failed item decision, and never that the decision buttons were gone. The backend tests were right
  about the backend; the frontend tests were right about their own half. Neither half was wrong, and
  the defect lived exactly on the seam.
- **Fixing one defect exposed a fourth of the same family.** `tailor()` sets `refusal`, not
  `error`, and **only the start view rendered `refusal`**. Adding the re-tailor button to the diff
  view would therefore have shipped a button whose most likely outcome — `stale_analysis`, because
  the version was written against a match several actions old — set state nobody displayed. This is
  the *same* defect as the silent `decide()`, one action along, and it would have been introduced
  by the fix for a different one. **Adding an affordance means auditing every state its handler can
  set, not just the success path.**
- **A one-line UI gate is worth more than it looks, and less than the schema.** All four defects
  were frontend-only; the backend refused correctly with the right message throughout, the item
  never changed, and the submission was untouched. Nothing about data integrity was ever at stake.
  What was at stake is a person believing they changed a résumé they did not — which is Principle
  II's actual subject, and not something a 409 in a browser console addresses.

### Handoff and measurement (added 2026-08-29)

- **The handoff skill's own task-counting command reports 0 / 1 for a slice that is 100 / 101.**
  `specs/005-resume-tailoring/tasks.md` uses `- [X]`, capital, for all 100 of its done tasks;
  every other slice uses lowercase. `grep -c '^- \[x\]'` matches none of them and prints a
  confident zero. Use `grep -cE '^- \[[xX]\]'`. This is the fifth instance of the project's
  "a gate with nothing to examine passes forever" pattern, and the first one found in the tooling
  that exists to prevent drift rather than in a test.
- **A local test count is not the CI test count, and the difference is not a bug.** Local pytest
  reported **797 passed** while CI reported **751** on the same commit. The gap was exactly the 46
  tests in Slice 008's then-untracked files. Recording 797 as "the suite" in a handoff would have
  sent the next session hunting 46 missing tests in CI. **When a working tree is shared, measure
  the suite and say which tree you measured.** (Resolved by the PR #14 merge — both counts now
  describe the same tree.)
- **The previous HANDOFF disagreed with itself about spend, and the stale half was the detailed
  one.** Its header said $3.084181; its §5A said "$2.431522 across 7 runs". Measured today: 11 runs,
  $3.084181. The narrative section had been updated less recently than the summary, which is the
  opposite of the intuition that detail is more current than summary.

---


### Deployment — the pre-deploy that ran half of itself (added 2026-08-29, T048)

- **A version-controlled `preDeployCommand` was silently not the one that ran, and the deploy was
  green.** `railway.toml` said `alembic upgrade head && python -m careerhq.ingest`. Deployment
  `75cd8ea` migrated cleanly `0014 → 0018`, reported **SUCCESS**, passed every health check — and
  **never ran ingestion**. Production sat with an empty corpus while retrieval fell back to the
  static rubric, which is FR-009 working correctly and therefore invisible.
- **`preDeployCommand` is a *single* command.** Railway's published JSON schema types it as a
  string or a **one-element** array; there is no multi-command form. Under
  `builder = "DOCKERFILE"` nothing interprets a shell operator, so `a && b` runs `a` and stops.
  The fix is `'/bin/sh -c "…"'`, which Railway's own staff give as the remedy.
- **Three wrong hypotheses, each plausible, each disproven by evidence rather than argument.** A
  dashboard override — the service instance has `preDeployCommand: null`. The wrong config file —
  Railway reports `configFile: /backend/railway.toml`, the correct one. And argv splitting, which
  was "disproven" by reasoning that alembic would have errored on the extra arguments. **That
  third inference was the instructive one**: it assumed the only alternatives were shell
  evaluation or naive splitting, and missed the actual behaviour — the first command runs and the
  rest is discarded silently. A confident deduction from an incomplete set of possibilities.
- **The comment asserted a guarantee the platform never provided.** It read *"the `&&` is the
  ordering"*. A configuration file claiming a property it does not have is worse than one that
  says nothing, because it stops anyone checking.
- **Grepping deployment logs for the logger name found nothing, on a deploy that worked.** After
  the fix, the ingestion lines are present as `corpus ingested` and `corpus ingestion finished` —
  Railway had stripped the *logger names* while keeping the message text, the inverse of the
  documented "Railway blanks the message field" behaviour. Searching for `careerhq.ingest`
  returned **0** and would have been reported as a failure had the corpus counts not contradicted
  it. **Verify a deploy by its effect on the database, not by its log grep.**
- **A green deployment is not evidence the corpus loaded**, and nothing in the pipeline asserts
  it. `test_the_pre_deploy_command_migrates_before_it_ingests` checks the *configuration*; no
  check exists for the *outcome*. That gap is still open.

### Measurement — the T052 re-measurement (added 2026-08-29)

- **A one-arm comparison would have been wrong in the favourable direction.** The plan was a
  single retrieval arm against the existing baseline `e70ecd76`. But T052 removed the citation
  from the **static** rubric too, so that baseline sent guidance current code does not — measured
  at **207 provider tokens** on `tailor_plan`. The saving would have been credited to retrieval.
  **When a change touches both arms of an A/B, the old baseline is not a baseline any more.**
- **The offline estimate of that correction was 134 tokens; the measured value was 207.** The
  estimate used `cl100k_base` where the arms are provider-counted — the mixing R15 warns against.
  It was directionally right and numerically 35% low.
- **The numerator improved 21% and the metric got worse.** +4,727 → +3,754 tokens, yet
  same-session SC-008 (006) moved 2.12% → **3.22%**, missed at both, because this session's
  static arm did not revise
  and the denominator nearly halved. SC-008 divides a fixed cost by a variable one; the same
  overhead reads 1.37%–3.22% depending on the denominator chosen — and SC-008 (006) is recorded
  as missed at 3.22%. **A metric that moves when the
  thing it measures improves is measuring something else.**
- **The flattering denominator was available and was not taken.** $0.007508 ÷ $0.446391 = 1.68%,
  which reads as a pass. It is not the same-session pairing and is recorded in all three
  documents as explicitly not a pass.

---

## 4A. Slice 007 — built, and its benchmark paid for (2026-08-29)

**The evaluation harness exists, ran against real models, and produced measurements.**
Artifacts: `specs/007-evaluation-benchmark/`, results in its `results/` directory.

### Spend — $4.925403 of a $10 hard ceiling

| | |
|---|---|
| Benchmark tailoring runs (23) | **$4.335980** — exact, persisted |
| Judge calls, main pass (8) | **$0.395800** — exact, itemised |
| Judge calls, timeout-interrupted segment (3) | $0.163623 — derived from the guard's trace |
| Case 1's failed judge call | **$0.030000 — an agreed upper bound, not a measurement** |
| **Cumulative** | **$4.925403 · 49% of ceiling · $5.074597 unused** |

**81 model calls. 23 tailoring runs, 12 judge calls — exactly the approved number.**
22 of 23 runs succeeded; 9 judge calls validated, **3 unjudged** on one recurring
fault: `{"at": "dimensions", "type": "too_long"}`, the model returning more than the
five rubric dimensions. Not systematic, and **the schema was deliberately not
relaxed mid-measurement** — that would make the scores incomparable.

Runs cost **$0.183 mean against a $0.308 estimate**, because the synthetic profiles
are smaller than the real one (17,706 input tokens against 26,774). **Judge cost is
now calibrated at $0.049475 mean**; the plan guessed $0.070 and an offline
reconstruction said $0.021.

### SC-006 — the Principle III release-blocker, now measured

> **`persisted_ungrounded = 0` across all 23 paid arms.**

Preserved as evidence: **2 ungrounded claims caught and discarded before
persistence**, **28 overstated claims flagged**, `traceable` 1.0 everywhere. The two
caught claims mean the guardrail has fired on real model output, so SC-006 finally
has something to be a regression test *of*.

### SC-008 — two criteria, and they must never be conflated

**SC-008 (006) remains `MISSED — 3.22% against an unchanged ≤2% threshold`.**
Nothing in slice 007 reinterprets, replaces or supersedes it.
`backend/tests/unit/test_sc008_is_not_relabelled.py` is the gate; it scans every
slice-007 artifact plus `CLAUDE.md`, and asserts the count of files it examined.

**SC-008 (007) — a different criterion — is `unresolved`, which is a valid outcome
of it rather than a pass/fail claim about retrieval.**

| | |
|---|---|
| Numerator | **3,376.6 ± 225.8 tokens**, n = 5 pairs (6.7% relative spread) |
| `plan_share` | 0.454 – 0.555 on every pair — Plan and Draft each carry about half |
| Denominator | n = 18, mean $0.184185, range $0.104822 – $0.404111, revision rate 33.3% |
| **Interval** | **[1.67%, 6.44%]** — straddles the 2% position |

**The numerator is now well established; the uncertainty is entirely in the
denominator**, and the live data shows why: **static arms revised 4 of 5 while
retrieval arms revised 2 of 12.** A total-cost comparison would have credited
retrieval with that and reported a revision-behaviour artefact as a cost finding —
exactly the failure T052 diagnosed.

> ⚠️ **PRICING WINDOW. This result holds at Sonnet 5's $2.00/MTok input rate, valid
> through 2026-08-31 — LiteLLM's own table, and what the gateway billed. At the
> post-2026-08-31 rate of $3.00/MTok the interval becomes [2.51%, 9.66%] and
> resolves *above* 2%. Never quote the verdict without its window.**

### T057 — closed as measured, not as a demonstrated improvement

**Mechanism confirmed**: items now read `B.Sc. in Software Engineering · Software
Engineering · Ben-Gurion University of the Negev · 2014-2018 · 87` where pre-T057
they read the institution alone. The qualification reaches the model and the export.

**Quality: mean Δ +0.073, n = 5, range −0.20 to +0.40. No regression observed; no
improvement demonstrable. The noise floor is unmeasured**, because D3 approved one
paid pass and SC-001's repeat was the third — so the delta cannot be compared
against zero, and is not. What it delivers is a bound.

**The experiment ran backwards from the plan, deliberately**: T040 is the
**post**-T057 arm and T045 the **pre**-T057 arm, because T057 had already landed at
T044 before the benchmark existed. The temporary source revert was restored and
**SHA-256 verified** (`f218a263b985`).

### The persistence question — resolved without a migration

**`alembic` still ends at `0018`. Slice 007 needs no migration.** The plan proposed
two columns; building the harness eliminated both:

- **`guideline_source` — not needed.** Two drafts asked *what a run was configured
  with*, which the record genuinely cannot answer. That is the wrong question: a
  metric describes what a run **was advised by**, and `guidelines_used` states that
  exactly — a corpus citation or `StaticGuidelines`' constant. Measured across all
  ten real runs carrying a snapshot: seven rubric constants, three citations, no
  overlap. Fallback detection is *intent versus outcome* and needs no column.
  Reframing took reportable runs from **2 of 13 to 8 of 13**.
- **`benchmark_run_id` — withdrawn.** The result artifact already maps cases to runs.
- **`duration_ms` — the only remaining candidate**, and nothing in slice 007 needs it
  except SC-010, which exists only because M-001 was inherited. **Recommendation:
  drop SC-010 here, or let Slice 008 take `0019` and land this later.**

### Two defects the paid pass found, both fixed

1. **The spend guard did not charge for billed failures.** `ExtractionFailedError`
   carries the usage the provider billed; the guard recorded only successes, so a
   failing call read as free — **a hole in the ceiling**. Fixed by duck-typing on
   `.usage`, the pattern `UsageRecorder` already documents.
2. **A failed judge killed the pass**, after the tailoring run had already been paid
   for. The judge contract says the case is *unjudged* and the run *continues*.

### Where slice 007 stands

**48 of 50 tasks ticked; 2 partial and both are the author's.**

- **T047** — the real sanity set is built and provably isolated (outside the repo,
  gitignored, PII-scanned) but **deliberately unpopulated**: filling it means copying
  a real CV onto disk. It spends no money.
- **T049** — `CLAUDE.md` done; this file adopted and extended, and the primary
  worktree's copy still needs reconciling.

**Nothing is committed.** Slice 008, `ports.py`, production and the pre-existing
evaluation evidence were untouched throughout: the original 8 versions / 13 runs /
1 submission / $3.253255 are byte-identical, and benchmark rows sit alongside them
under `google_sub LIKE 'benchmark|%'`.

### The follow-up session (2026-08-31) — six things worth keeping

1. **A gate with nothing to examine, the fifth time — and this one guarded a real bug.**
   `renderTab` in `tailor.test.tsx` rejects `getTailoringRun` with a **404**, so `run` was `null`
   in **all 49** tailor tests. The provenance assertion therefore passed off `version.model` alone
   and could never have seen the two-model attribution bug it appeared to cover. **When a fixture
   stubs a dependency with a failure, every test in that file is blind to whatever that dependency
   feeds.** Check what a shared fixture *refuses*, not only what it supplies.

2. **A deprecation that is numerically identical cannot be caught at run time.**
   `HTTP_413_REQUEST_ENTITY_TOO_LARGE` and `HTTP_413_CONTENT_TOO_LARGE` are both `413`, so no
   request would ever have failed and no behavioural test could tell them apart. The rule had to
   live in the **source tree**. Written to read `starlette.status.__deprecated__` at run time
   rather than to match one string, so it covers the other three deprecated names too.

3. **Correcting an accounting error can make a metric worse, and that is a result.** SC-008 (006)
   was suspected of being an artefact. R16 re-derived it free from the recorded arms and found the
   ceiling **honoured** — 1,497 tokens against 1,500, so no implementation defect — but also that
   `tailor_review` grew **+670** input tokens while consuming *no* guidance, and that the recorded
   figure is a `plan+draft` proxy where the criterion says *cost per run*. **Do not assume an audit
   will exonerate.** The finding was worth more than a pass would have been.

4. **A handoff cannot describe the commit that lands it.** PR #15's handoff was written before the
   follow-ups existed and described them as open; PR #16's correction could not name its own merge
   SHA. **Every handoff is stale about its own merge** — check the header against
   `git rev-parse origin/main` before trusting it, which is exactly how this rewrite started.

5. **A test can wait for the wrong thing and pass most of the time.**
   `tailor.test.tsx > "names every model a run used"` failed **5 runs in 20**. `getTailoringRun`
   resolves in its **own** effect while `setLoading(false)` belongs to the *version* fetch, so
   waiting for "Loading…" to disappear said nothing about whether the run had landed; a bare
   `getByTestId` then sampled whichever won and saw the one-model fallback. **Adding an unrelated
   test file was enough to tip the scheduling**, which is how a latent race surfaced as someone
   else's problem. Proved by forcing the run to resolve one macrotask late — failure went to
   **100%** — rather than by re-running until it passed.

6. **Guessing a production URL produced a confident 404.** `curl` against an invented Railway
   hostname returned `Application not found`, which reads as an outage rather than as a wrong
   address. The real domain came from `railway domain --service frontend` and answered 200.
   **Ask the platform for the hostname; never pattern-match it.**

---
## 5. Exact next steps

**Nothing is blocked and nothing is unpushed.** `main` is `32f5be2` and
`git log --branches --not --remotes` is empty. Items **B** (the two ticks) and **C** (T083) of the
previous revision are **done** and deleted rather than kept — a next-steps list that mostly
describes finished work stops being read. What they achieved is recorded in §2, §3 and §4.

**The next significant work is A. Everything else here is small.**

### A — **Slice 009, Career Advisor** · owner: next session · **unblocked, but do not start with code**

The last planned slice and the clearest demonstration that the system reasons over accumulated
memory rather than answering one prompt (`docs/05` §5.9).

> ⚠️ **Its headline capability has no input data, and `docs/05` says otherwise.** §5.9 justifies
> putting 009 last because the JobTracker import supplies history "immediately rather than after
> months of use". That is true of statuses, dates and outcomes — **not of posting content.**
> `EXPORT_COLUMNS` carries `job_desc_link` (a **URL**) and `match_rating`; the write sets neither
> `job_description` nor `requirements`. So all **96** imported rows have `requirements IS NULL`,
> which `scoreability.py` **refuses outright** as legacy — they cannot be match-analysed either.
> *"Python appeared in 14 of 20 roles"* has nothing to count.
>
> Verify: `railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway`
> `-c \"SELECT count(*) FILTER (WHERE requirements IS NULL) FROM applications;\""`

**Start with `/speckit-specify` and make the spec resolve that**, not the implementation. Two
honest routes: scope 009 to what the data supports (role families, outcome and rejection rates —
**63 of 96** imported rows are `rejected`, time-in-status, `imported_match_rating` as
self-assessment), or make a **bounded posting backfill** its first user story. The backfill is the
expensive one: ~96 user-supplied URLs through the SSRF-guarded fetcher plus a completion each, many
links dead, and it **writes to real production rows** — so it needs idempotency and a dry run.

Own it in a **fresh worktree** with its own database:
`CAREERHQ_TEST_DATABASE_URL=…/careerhq_test_009`.

### B — **T047: populate the real sanity set** · owner: **the author only** · deferred by design

Built, isolated, gitignored and PII-scanned; `REAL_SET_DEFAULT_ROOT` is `~/CareerHQ-benchmark-real`,
which **does not exist**. **It cannot be completed with synthetic data** — its one question is
whether the synthetic set overstates the system, so a second synthetic set answers nothing. Filling
it means a real CV on disk. Spends no money.

Verify: `ls ~/CareerHQ-benchmark-real 2>/dev/null || echo "unpopulated, as intended"`

### C — **Off-machine backup of the paid evaluation evidence** · owner: the author · **largest unmanaged risk**

Unchanged and still the biggest one. The only backup is `~/CareerHQ-backups/2026-08-29/`, **on the
same machine as the volumes**, and predates both T052 arms and the whole Slice 007 benchmark.
Roughly **$8.49** of paid evidence: $3.562567 (004–006) + $4.925403 (007) + $0.352047 in
production. It lives in **two** volumes — `careerhq_postgres_data` for rows,
`careerhq_minio_data` for the exported PDF bytes a submission checksum refers to. Lose the second
and re-verification fails permanently, by design.

### D — **Delete the merged branches and stale worktrees** · owner: either · housekeeping

**Measured 2026-08-31: 18 local branches are merged into `main`** and still present, four of them
from this session — `handoff-post-008`, `fix/small-followups-pre-009`, `t083-jobtracker-import-ui`
and `fix/tailor-model-test-flake` — the last three also on the remote. **13 worktrees** exist,
including two created this session (`CareerHQ-t083`, `CareerHQ-flake`) that are finished with.

**Not urgent, and deliberately not done here.** A stale branch costs nothing; deleting one that
turns out to hold the only copy of something costs a great deal, and §4 records exactly that near
miss. Check `git log --branches --not --remotes` first — it is empty today.

Verify: `git branch --merged main --format='%(refname:short)' | grep -v '^main$'`
and `git worktree list`

### E — **The SC-008 gate does not scan `specs/006`** · owner: next session · small, recorded not fixed

`test_sc008_is_not_relabelled.py` scans `specs/007-*`, `HANDOFF.md` and `CLAUDE.md` — **not**
`specs/006`, where R15 and R16 live. So the slice's own SC-008 record is unchecked by the gate that
exists to protect it, and **three pre-existing verdict-rule violations sit in R15** (lines 534, 540,
546: `3.22` with no "missed" nearby). Widening `_artifacts()` would catch them. Deliberately not
done here, because changing that test was out of scope for the session that found it.

---
## 5A. Real data that must not be deleted or modified

The project's only evaluation evidence. It was paid for. **Tailoring-run counts measured
2026-08-29; production counts re-measured 2026-08-31.**

**Local totals: 8 versions, 13 runs, 8 analyses, spend `$3.562567`.** Production separately holds
**1 match analysis at `$0.039222`** — so "the evidence is local-only" is true of tailoring runs
and not of everything.

### The imported JobTracker history — 96 rows, irreplaceable

**T084's import is real personal history and the file it came from must never enter this
repository.** Re-measured against the production database on 2026-08-31 and matching the original
report exactly:

| | Measured |
|---|---|
| rows carrying `import_source='jobtracker'` | **96** |
| manual rows alongside them | **1** (the pre-existing Cellebrite application) |
| applications / companies total | **97 / 90** |
| `normalized_status` across all 97 | rejected **63**, applied **30**, wishlist **2**, other **1**, withdrawn **1** |
| `rejected` **column** in `information_schema` | **0** — the release-blocker invariant holds on the deployed database |

⚠️ **`rejected = 0` and `rejected = 63` are two different things and must never be collapsed.** The
importer rejected **nothing** — every row it was given was accepted. Separately, **63 rows
reconciled to `normalized_status = rejected`** under FR-016, which is an *outcome recorded on the
application*, not a failure of the import. Reading the 63 as import failures would make a clean run
look two-thirds broken; reading the 0 as "nobody was rejected" would erase the user's actual
history. This is exactly why FR-016 has no `rejected` **column** — the label says how far you got,
the normalised status says how it ended.

**The pre-existing Cellebrite application and its company were preserved**, not duplicated — the
conservative merge keys doing what they were designed for, on real data rather than a fixture. Its
`updated_at` did not move, and the T088 run's evidence attached to it was untouched.

**Re-import is safe and adds nothing**, resting on 96 distinct source ids with 0 duplicate
identities plus `uq_applications_import_identity`. Note that a **second production import was
never run** — that claim rests on the rehearsal and on
`test_jobtracker_route.py::test_re_uploading_the_same_file_reports_everything_as_skipped`, not on a
production observation.

| Record | Why it must survive |
|---|---|
| Version `a8f1e4b7` + runs `a76bd349`, `cd27b092`, `2615363e` | Cellebrite. Two failures and the first success on **one reused draft** — the evidence the retry-reuse fix works |
| Version `c582d938` + run `6356fb4e` | Zipher. The 0.167 adherence sample |
| Version `1bd5f20f` (**submitted**) | **The only export and the only submission.** 12,085 bytes, checksum `d77926480e3c…`; export and submission checksums match, which is FR-021's re-hash working on real bytes |
| Match `ad25de2c` (Voyantis, **0**) | The historical invalid analysis, **deliberately not deleted** — rendered as `nothing_to_score` |
| Match `1285d10a` (Voyantis, **84**) | The scoreability fix on real data, same posting |
| Runs `60263226` ($0.547891, 2 revisions) and `7c1d64d4` ($0.206268, 0) | The measured cost spread at its ends — 2.66× on one pipeline |
| **Runs `aae6f565` and `1070657e`** (T052, 2026-08-29) | **The SC-008 re-measurement.** The static and retrieval arms on current code; `$0.478386` |

### Backed up 2026-08-29 — and the backup is already behind

**`/Users/nirtituani/CareerHQ-backups/2026-08-29/`**, outside the repository.

| File | Size | Verification |
|---|---|---|
| `careerhq_postgres_data.tgz` | 54M | `tar -tzf` readable, 1,977 entries |
| `careerhq_minio_data.tgz` | 308K | 154 entries; contains the exported PDF object |
| `careerhq_logical.dump` | 320K | `PGDMP`; `pg_restore -l` lists 32 TABLE DATA entries |

**Two limits, both real.** It is **on the same machine** — protection against
`docker compose down -v`, not against losing the laptop. And it **predates the two T052 arms**,
so `aae6f565` and `1070657e` exist in no backup.

***It lives in TWO volumes, not one.*** `careerhq_postgres_data` holds the rows;
`careerhq_minio_data` holds the **exported PDF bytes** a submission checksum refers to. Lose the
second and re-verification fails permanently — by design, a mismatch refuses and repairs nothing.

**Keep backups outside the repo.** `./backup/` is **not** gitignored and there is no `*.tgz` or
`*.dump` rule; a dump carries the real profile — home address, phone, employment history — and
this repository is **public**.

Two rules already broken once each:

- **Never run a test against the real profile.** One merged a fictional CV into it. Seed
  `@example.com` — never `.test` or `.invalid`, which `EmailStr` rejects, producing a 500 that
  reads as an application bug.
- **Delete anything seeded by hand.** The counts above are the truth. Honoured again on
  2026-08-30: the Slice 008 production check seeded a temporary verification user with one
  application, one company, one snapshot and six source rows, and all of it was deleted after
  validation — scoped to that user's id, inside a transaction, with the real account's
  **97 applications and 90 companies** counted before and after and unchanged.

**Two checkouts running the suite at once will corrupt each other unless one is redirected** — the
session fixture runs `DROP SCHEMA public CASCADE`, so a shared database means each run erases the
other's schema mid-flight. **PR #13 fixed this**: set `CAREERHQ_TEST_DATABASE_URL` to give a
worktree its own database, created on demand, no setup needed. Unset, nothing changes and CI is
unaffected. It is deliberately **not** `DATABASE_URL`, which points at the development database
holding the paid evaluation evidence.

This cost a wrong conclusion before it was fixed: a suite run against a shared `careerhq_test`
reported **351 failures and took 12m47s**, and the same code run alone passed 1,219 in 70 seconds.
**A failure count that changes between runs of identical code is this, not a flaky test.**

---
## 6. Process reminders

- **Spec-Driven Development** via Spec-Kit: `specify → plan → tasks → analyze → implement →
  verify`. **Do not skip `analyze`** — it found the two invariant tests this slice, and all three
  documentation corrections (T080–T082).
- **Tests first**, and the failure message matters. `ModuleNotFoundError` because the module does
  not exist yet is a valid red.
- **Any test asserting an absence or an invariant must be watched failing** — and check the
  `deselected` count, because a `-k` filter that matches nothing looks exactly like a pass.
- **When implementation predates a test** (US1 built most of US2 and US3), ticking the task on
  inspection is a lie. Break the implementation, watch the test name it, restore.
- **Verify in Docker, then in a browser** on `localhost` — not `127.0.0.1`, which 403s its own
  chunks in Next.js dev with no console error. **Every display bug in this project was found by a
  person looking at real data, including all twenty invisible buttons.**
- **Seed test data against a scratch user, and delete anything fabricated afterwards.** Two hand-
  seeded versions were used for the browser walkthroughs this session and removed; the local count
  is back to zero.
- **Backend gates run on the host, never in the container.** `backend/.dockerignore` excludes
  `tests/`, so an in-container pytest collects nothing and looks like a pass.
- **`docker compose build backend && docker compose up -d backend`** after backend code changes.
  `up -d` alone recreates the container from the same baked image. The frontend hot-reloads.
- **Update `tasks.md` as you go**, and amend a task's text when the implementation deviates. Four
  were amended this slice — T054, T056, T072 and T077 — and each amendment records why.
- **Drill the old behaviour, and count what you examined.** A gate nobody has watched fail is not a
  gate, and a gate with nothing to examine passes forever — that has now shipped four times. Read
  the `N deselected` count; a `-k` selector matching nothing prints a cheerful pass.
- **Distinguish a test double from a model.** Fixtures are written by someone who read the code.
  Where a model must read something out of a prompt, make the double read it out of the prompt too.
- **Keep measured facts separate from interpretation** in tests, commits and `research.md`.
- **`/handoff` before `/clear`.** It does not run automatically.
