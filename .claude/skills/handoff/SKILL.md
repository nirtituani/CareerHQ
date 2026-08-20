---
name: "handoff"
description: "Use when wrapping up a work session, before /clear or /compact, when context is running low, or when the user asks to save state, write a handoff, or record where to pick up."
argument-hint: "Optional focus, e.g. a slice number or 'quick'"
compatibility: "Requires HANDOFF.md at the repository root"
metadata:
  author: "careerhq"
user-invocable: true
disable-model-invocation: false
---

# Handoff

Regenerate `HANDOFF.md` so the next session — with no memory of this one — can resume without
re-deriving anything.

## The split

- **`HANDOFF.md`** — what is true *right now*: status, open tasks, next steps. Rewritten every time.
- **`CLAUDE.md`** — what stays true: conventions, gotchas, architecture. Rarely touched.

If the two disagree about status, HANDOFF.md wins. **Never put status in CLAUDE.md** — that is the
drift this file exists to prevent.

## Measure, don't copy

**Every number in HANDOFF.md must come from a command run in this session.** Do not carry a figure
forward from the old HANDOFF.md, from CLAUDE.md, or from memory — that is exactly how the file
starts lying. This is not hypothetical: CLAUDE.md claimed "93 of 109" while the real count was 97,
and listed four documentation tasks as outstanding that had already shipped.

Run these first, then write:

```bash
# Repo state
git log --oneline -1 && git status --short && git branch --show-current

# Task counts — per slice, and what is actually open
for f in specs/*/tasks.md; do
  echo "$f: $(grep -c '^- \[x\]' $f) / $(grep -c '^- \[[ x]\]' $f)"
done
grep -rn '^- \[ \]' specs/*/tasks.md | cut -c1-120

# Tests — run them, do not quote them
(cd backend && .venv/bin/pytest -q 2>&1 | tail -3)
(cd frontend && npm test -- --run 2>&1 | tail -5)

# Files changed this slice (<first-commit> = the slice's first commit)
git diff --name-status <first-commit>~1..HEAD -- backend/src frontend/src

# Deployed reality — the source of truth for anything "is it live"
railway ssh --service pgvector "PGHOST=localhost PGPORT=5432 psql -U postgres -d railway \
  -c \"SELECT (SELECT count(*) FROM users) || '|' || (SELECT count(*) FROM professional_profiles) \
  || '|' || (SELECT count(*) FROM applications);\""
```

If a blocker is "waiting on something external", **check whether it arrived** rather than repeating
that it hasn't — `gh issue list`, `gh pr list`, `git ls-remote --heads origin`, and look for the
file. Record the finding with the date you checked it.

## Required sections

HANDOFF.md has six sections, in this order. Fill every one; an empty section is a signal, so say
"none" rather than deleting the heading.

1. **Core goal** — the product in a few sentences, plus constraints and any non-optional
   requirement. Nearly static; carry it forward.
2. **Current implementation status** — slice table with task counts, live-system state, measured
   test numbers. **All measured this session.**
3. **Files modified** — grouped by layer, not a flat dump. Include a *"read these first"* table of
   the 3–5 files that matter most, and the `git diff` command to regenerate the list.
4. **What failed** — **append-only. Never delete an entry.** Approaches tried that did not work,
   grouped by area. This is the most expensive knowledge in the repo and the whole reason the file
   pays for itself. Add what this session learned; keep everything already there.
5. **Exact next steps** — lettered options, each marked with what blocks it and who owns it, with
   the verify command inline. A next step nobody can act on without asking a question is not
   finished.
6. **Process reminders** — the SDD loop, tests-first, verify-in-Docker. Nearly static.

Update the header line — date, commit, branch — every time.

## Before finishing

- Re-read the diff. Did any *durable* fact get cut that belongs in CLAUDE.md instead? Move it.
- Does §5 name a blocker without saying who owns it? Fix it.
- Did any number get written without a command behind it? Go run the command.
