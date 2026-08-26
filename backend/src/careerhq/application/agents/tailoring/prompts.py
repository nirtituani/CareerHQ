"""One prompt builder per node.

**No builder asks the model to echo back text it was given.** Draft and Revise
return item ids plus changed text only. Slice 003 measured what the other way
costs: a posting retyped once took 52 seconds and timed out the frontend proxy,
against 5.4 seconds returning metadata only. Output is also 57-86% of the cost,
so this is the cost lever as well as the latency one.
"""

from __future__ import annotations

import json
from typing import Any

from careerhq.application.agents.tailoring.state import TailoringState

_PLAN = """You are planning how to tailor a resume to one job posting.

You are NOT assessing fit. That has already been done, and its result is below —
treat it as given. Your job is to decide **how this resume should read**.

## The posting
{job}

## The existing match analysis (read-only)
{match}

## The profile, in full
{master}

## Resume-writing guidance
{guidelines}

## What to produce

- `emphasise`: what this resume should lead with, and which requirement each
  serves. Order matters; a reader spends seconds per role.
- `de_emphasise`: what is present in the profile but does not serve this posting.
- `protected_gaps`: every requirement the analysis judged `gap` or `unverified`.
  These must NOT be claimed, implied, or written around. Naming them here is how
  the drafting step knows where the edges are.
- `strategy`: one paragraph on how the resume should read and why.

Emphasis must point at something the profile actually contains. If the profile
does not support a requirement, that is a protected gap, not an emphasis."""

_DRAFT = """You are tailoring a resume to one job posting, following a plan.

The plan is not a suggestion. It was produced by a step that read the fit
analysis, and your job is to execute it rather than to re-decide the strategy.

## The plan
{plan}

## The posting
{job}

## The profile, in full — this is the ONLY source of facts
{master}

## Resume-writing guidance
{guidelines}

## Rules

1. You may **reorder**, **select**, and **rewrite**. You may not invent.
2. Every claim must trace to something in the profile above. If the profile does
   not say it, it does not go in the resume — not implied, not softened, not
   hedged into place.
3. The plan's `protected_gaps` are the requirements the profile cannot answer.
   Do not write around them. A resume that omits a requirement is honest; one
   that gestures at it is not.
4. Return **only the items you are changing or dropping**. An item you leave
   alone should not appear. Do not retype the resume.
5. Every item you return MUST carry `source_item_id`, copied **exactly** from
   the `[id: ...]` prefix of the profile line it changes. Copy it character for
   character; do not invent one and do not leave it out. A proposal whose id
   does not name a real line cannot be applied and will be discarded.
   Lines with no `[id: ...]` prefix — a role's heading — are context. You cannot
   propose against them.
6. `text` is the new wording. Leave it null if only the position or inclusion
   changes.
7. Every rewrite carries a `reason` — one sentence, why this wording serves this
   posting. The owner reads it beside your proposal and decides."""

_REVIEW = """You are reviewing a tailored resume draft against the profile it came from.

You are the last check before a person is asked to approve this. Be exacting:
your job is to find what is wrong, not to confirm it is fine.

## The profile — the only thing that makes a claim true
{master}

## The posting
{job}

## The resulting resume — every line that will appear once this draft is applied
{resume}

Lines marked `(rewritten)` are the ones this draft changed. **Every other line is
the owner's existing wording, unchanged and still in the resume.** Judge coverage
against this whole document, not only the rewritten lines: a requirement answered
by an unchanged line is answered.

You may only raise `ungrounded` or `overstated` against a `(rewritten)` line. The
unchanged lines are the owner's own words, not this draft's claims.

## What to report

- `ungrounded`: the draft claims something the profile does not contain. Quote
  the exact words. This is the most serious finding and the one that matters
  most — a resume that invents experience harms the person who sends it.
- `overstated`: the profile supports the claim, but the wording inflates it.
  "Led" where the profile says "contributed to". Quote the exact words.
- `uncovered`: the posting asks for something the draft never addresses. This
  concerns the draft as a whole, so do not attach it to an item.

## Attaching a finding to what it concerns

Every `ungrounded` and `overstated` finding MUST carry `source_item_id`, copied
exactly from the `source_item_id` of the draft item above that it concerns. Do
not invent one and do not leave it out — a finding nobody can attribute to a
specific line is one the person cannot act on, and it will be rejected.

Only `uncovered` has no `source_item_id`, because it is about the draft as a
whole. Leave it null there.

An adjacent skill described accurately is not `ungrounded`. A domain qualifier
is not a gap: "build AI workflows for system architecture" asks for building AI
workflows. Judge the claim, not the vocabulary.

`confidence` is 0-100: how sound this draft is **given this profile**. It is not
a judgement of the person's fit for the job. Report it as a whole number, never
as a fraction of one."""

_REVISE = """You are revising a tailored resume draft that did not pass review.

## What the reviewer found
{findings}

## The plan you are still working to
{plan}

## The profile — the ONLY source of facts
{master}

## The resulting resume — every line that will appear once your changes are applied
{resume}

Lines marked `(rewritten)` are the ones already changed; the rest is the owner's
existing wording. An `uncovered` finding is about this whole document, so check
it against every line before concluding something is missing.

## Rules

1. Fix what the reviewer named. An `ungrounded` finding means the claim must go,
   not be softened — if the profile does not support it, no wording makes it
   true.
2. An `overstated` finding means the claim is real and the wording is not. Bring
   the wording back to what the profile actually says.
3. An `uncovered` finding may have no fix. If the profile cannot answer that
   requirement, leave it unaddressed rather than manufacturing something.
4. Return only the items you are changing. Do not retype the resume.
5. Every item you return MUST carry `source_item_id`, copied **exactly** from
   the item it revises in the draft above, or from the `[id: ...]` prefix of the
   profile line. Do not invent one and do not leave it out.
6. Do not introduce new claims while fixing old ones."""


def compose_resume(state: TailoringState) -> str:
    """The resume that **results** from this draft, line by line.

    The Reviewer used to be shown `state.items` — only what the draft changed or
    dropped — under the heading "## The draft". On a run that rewrote one line it
    received one line and reported eight requirements the resume "never
    addresses", naming bullets that were sitting in the resume untouched.

    `uncovered` is a question about the document. It cannot be answered from a
    diff. So the diff is applied over the master here, in code, and the Reviewer
    judges coverage against the result — the same content the owner will see.

    **This is a view, not a document.** It carries no role headings, dates or
    contact block, because `master_items` does not hold them and coverage does
    not depend on them; the assembled résumé is slice 006's job. It also does not
    re-sort: reordering is recorded in each row's `position` and read at render
    time, and no coverage judgement turns on sequence. Master order is kept so
    this view and the persisted rows can be compared item for item.

    **Input-side only.** Draft and Revise still return item ids with changed
    text. Showing a model a whole resume and letting it hand one back is what
    research R5 identifies as the cost problem, not the fix.
    """
    changed = {
        str(item.source_item_id): item for item in state.items if item.source_item_id is not None
    }

    lines: list[str] = []
    for row in state.master_items:
        item_id = str(row["source_item_id"])
        proposal = changed.get(item_id)

        # Dropped by the draft, so genuinely not in the resulting resume. A
        # requirement it used to answer is now unaddressed, and the Reviewer
        # should see that rather than be told otherwise.
        if proposal is not None and not proposal.included:
            continue

        kind = str(row["source_kind"]).upper()
        if proposal is not None and proposal.text:
            # Marked, so `overstated` and `ungrounded` still know which lines
            # they may object to. Without this the Reviewer cannot tell a
            # proposal from the owner's own wording and starts objecting to the
            # profile.
            lines.append(f"[id: {item_id}] {kind} (rewritten): {proposal.text}")
        else:
            lines.append(f"[id: {item_id}] {kind}: {row['text']}")

    return "\n".join(lines)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def _guidelines(state: TailoringState) -> str:
    return "\n".join(f"- {g['text']}  [{g['source']}]" for g in state.guidelines)


def build_plan_prompt(state: TailoringState) -> str:
    return _PLAN.format(
        job=_json(state.job),
        match=_json(state.match),
        master=state.master,
        guidelines=_guidelines(state),
    )


def build_draft_prompt(state: TailoringState) -> str:
    return _DRAFT.format(
        plan=_json(state.plan),
        job=_json(state.job),
        master=state.master,
        guidelines=_guidelines(state),
    )


def build_review_prompt(state: TailoringState) -> str:
    return _REVIEW.format(master=state.master, job=_json(state.job), resume=compose_resume(state))


def build_revise_prompt(state: TailoringState) -> str:
    return _REVISE.format(
        # Unwrapped from `RaisedFinding`: the model sees exactly the findings
        # JSON it saw before the pass label existed. The label is state
        # bookkeeping for persistence, never prompt content.
        findings=_json([raised.finding.model_dump(mode="json") for raised in state.findings]),
        plan=_json(state.plan),
        master=state.master,
        resume=compose_resume(state),
    )


__all__ = [
    "build_draft_prompt",
    "build_plan_prompt",
    "build_review_prompt",
    "build_revise_prompt",
    "compose_resume",
]
