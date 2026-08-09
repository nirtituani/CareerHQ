# CareerHQ

AI-powered career intelligence platform. Import a CV, track applications, and have an agent tailor
your resume to a job description — with your approval on every change.

Built solo as a course project on a four-to-six-week budget. That constraint is real and shapes
the plan: see `docs/05_Implementation_Plan.md` §2.

---

## Read these first

In this order. The whole project is legible from four files.

1. **`docs/07_Capabilities.md`** — what CareerHQ is and what each capability does. Start here.
2. **`.specify/memory/constitution.md`** — the seven non-negotiable principles. Violations of
   II–IV are release blockers.
3. **`docs/05_Implementation_Plan.md`** — the slice roadmap and why it is ordered that way.
4. **`specs/00N-<slice>/tasks.md`** — the current slice's task list, with checkboxes showing
   exactly where work stopped.

Supporting detail lives in `docs/01` (requirements), `docs/02` (ADRs), `docs/03` (domain model),
`docs/04` (architecture), `docs/06` (stack). Original source material — the course requirements,
the author's design notes, the resume-builder reference — is in `docs/reference/`.

---

## Current state

**Slice 001 — Platform Foundation.** User Stories 1 and 2 complete and verified; 57 of 69 tasks
done. Remaining: US3 (`T057`–`T063`, CI pipeline) and polish (`T064`–`T069`).

Working: Docker Compose stack, Google sign-in end to end, per-user isolation, health checks
reporting each dependency by name. 46 tests, 89% backend coverage.

Branch: `001-platform-foundation`.

---

## How we work

**Spec-Driven Development** using GitHub Spec-Kit. Every slice runs
`specify → plan → tasks → analyze → implement → verify`. Artifacts live in `specs/` and are
version-controlled. Do not skip `analyze` — it has caught real gaps before code was written.

**Tests first.** Write the test, run it, confirm it fails for the right reason, then implement.
The failure message matters: `ImportError` because the module does not exist yet is a valid red;
a test that passes before implementation is a broken test.

**Verify in Docker, not just in pytest.** Every user story ends with a task that runs the real
stack. That step has caught bugs the suite could not: a missing dependency that existed only in a
local venv, an empty `SESSION_SECRET` being accepted, and an OAuth redirect URI pointing at an
internal Docker hostname.

**Update `tasks.md` as you go.** Tick boxes when tasks complete, and amend a task's text when the
implementation deviates — a task list that lies about what happened is worse than none.

**Commit messages explain why.** The what is in the diff.

---

## Conventions

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 async, layered as
  `api/ → application/ → domain/`, with `infrastructure/` implementing what the inner layers
  declare. `domain/` imports no framework code — that is what keeps Principle V enforceable.
- **Frontend**: Next.js 16 App Router, TypeScript 7, Tailwind 4 (configured in CSS via `@theme`;
  there is no `tailwind.config.js`), shadcn/ui.
- **Business invariants belong in the schema.** A UNIQUE constraint cannot be raced or forgotten;
  an application-level check can be both.
- **Ownership comes from the session, never from the request.** No endpoint accepts a
  client-supplied user or profile id. A test enumerates every route and asserts non-public ones
  return 401.
- **Quality gates**: `ruff format`, `ruff check`, `mypy` strict, `pytest` at ≥80% coverage.

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
.venv/bin/pytest              # 24 tests run without Docker; 22 skip without PostgreSQL
.venv/bin/ruff check .
.venv/bin/mypy src
```

---

## Gotchas already hit

Recorded so they are not rediscovered.

- **`docker compose restart` does not pick up `.env` changes.** Environment variables are injected
  when a container is *created*. Use `up -d`, which recreates it. Verify with
  `docker compose exec backend printenv VAR`.
- **`ModuleNotFoundError: No module named 'careerhq'` from an apparently correct editable
  install** is macOS setting the BSD `hidden` flag on the `.pth` file. Python 3.12's `site` module
  deliberately skips hidden `.pth` files, so the install looks perfect — right path, right
  contents, readable — and Python ignores it. Diagnose with `ls -lO .venv/lib/*/site-packages/*.pth`
  (look for `hidden`), fix with `chflags nohidden` on those files. `pytest` no longer depends on
  this at all, because `pythonpath = ["src"]` is set in `pyproject.toml`; anything else invoking
  the venv's Python directly still can. Recreating the venv also clears it, which is why an earlier
  diagnosis blamed venv nesting — that was wrong.
- **Host ports are configurable** in `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, …). Change those
  rather than editing `docker-compose.yml` when a port collides.
- **`request.base_url` is the internal hostname behind the proxy.** The frontend proxies `/api/*`
  to `http://backend:8000`, so anything browser-facing — OAuth redirect URIs especially — must
  come from `PUBLIC_BASE_URL`, not from the request.
- **Verify package versions against the registry before pinning.** Six versions in the original
  plan did not exist. Installing is faster than guessing.
- **A comment beginning `# noqa` is parsed as a blanket lint suppression.** Do not start an
  explanatory comment with that word.

---

## Deliberate non-goals for now

Do not build these without discussion — each was scoped out for a stated reason, recorded in
`docs/05` §7:

- The from-scratch resume builder and the presentation designer (≈40 settings, demonstrates none
  of the project requirements; import reaches the same data far faster — ADR-013)
- Multi-provider LLM routing (LiteLLM makes it configuration)
- A full WYSIWYG resume editor

And two things that are **not** optional despite being unbuilt: the Reviewer/evaluation layer
(slice 005) and deployment (slice 002). Both are graded requirements.
