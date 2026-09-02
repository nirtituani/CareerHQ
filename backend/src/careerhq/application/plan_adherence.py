"""How much of the plan the draft actually carried out.

**A measurement, not a rule.** Nothing here has a threshold and nothing gates on
it, because the only evidence is two runs: Cellebrite planned eight emphases and
the draft rewrote four; Zipher planned six and rewrote one. Same profile, same
prompts, same code. Whether that gap is a defect, a prompt weakness or ordinary
variance is not decidable from two samples, and a floor chosen now would encode
a guess as a gate — which is how a number stops being questioned.

What this does is make the figure fall out of every run rather than be
re-derived by hand, so that when slice 007 can judge it there is a distribution
to judge rather than an anecdote.

**De-emphasis is deliberately unmeasured.** `TailoringPlan.de_emphasise` holds
free text — "C++ as a current primary skill" — with no ids, so whether the draft
dropped what the plan named cannot be computed. Making it computable means
changing the Plan schema and therefore the Plan prompt, and there is not yet
evidence to justify touching either. It is the larger of the two blind spots:
Zipher executed zero of nine.

**Two contracts are measured here, and their figures must never be read as one
series.** `emphasis_adherence` (D0) and `plan_execution` (D1/D3) grade the old
promise — "did a text proposal appear for what the plan named" — which the old
prompt never actually demanded; they are kept byte-identical because they are
the accumulated distribution. `action_execution` grades the `action` contract,
where a directive states `keep`/`reframe`/`rewrite` and compliance means doing
what was stated — including doing *nothing* to a `keep`. A Silverfort-style run
scoring D1 0.125 while scoring perfect action compliance is not a contradiction;
it is the difference between the two promises (the SC-008 (006) lesson: when a
definition changes, a comparison across the change measures the definition).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def emphasis_adherence(
    plan: Mapping[str, Any] | None, *, rewritten_ids: Iterable[str]
) -> dict[str, Any]:
    """Compare what the plan said to emphasise against what the draft rewrote.

    Read from data the run already persists — `tailoring_runs.plan` and the
    version's items — so this adds no schema, no column and no provider call,
    and applies retroactively to runs that finished before it existed.

    `source_item_id` is optional on an `EmphasisDirective`: a plan may emphasise
    something pointing at no single fact. Those cannot be matched against a
    rewrite, so they are reported in `planned` and excluded from the ratio
    rather than counted as failures.

    `adherence` is `None` rather than `0.0` when there is nothing to score. A
    plan with no addressable emphases and a plan whose emphases were all ignored
    are different facts, and a run that failed before planning has neither.
    """
    directives = (plan or {}).get("emphasise") or []
    planned = len(directives)

    wanted = [
        str(d["source_item_id"])
        for d in directives
        if isinstance(d, Mapping) and d.get("source_item_id")
    ]
    done = set(rewritten_ids)

    # Only emphases the plan named. A rewrite the plan never asked for is not
    # adherence, and counting it would let a run score well by ignoring the plan.
    executed = [item_id for item_id in wanted if item_id in done]

    return {
        "planned": planned,
        "with_ids": len(wanted),
        "executed": len(executed),
        "adherence": round(len(executed) / len(wanted), 3) if wanted else None,
        "unexecuted_ids": [item_id for item_id in wanted if item_id not in done],
    }


LABEL_KINDS = frozenset({"skill", "language"})
"""Kinds whose item text is a label, not prose.

Measured on version `d3700cb8`: skill lines average 17 characters and reach 44
("Python (FastAPI, Agentic AI frameworks)"), language lines reach 7, against an
average of 153 and a maximum of 223 for an experience bullet. A plan that says
to emphasise the skill "C++" is not asking for "C++" to be reworded — there is
nothing there to reword. Emphasis of a label is expressed by keeping it while
its neighbours are dropped, or by moving it, and **neither is visible in a text
comparison**. Counting such an entry against a rewrite ratio measures the
schema, not the draft, so D3 excludes it from the denominator rather than
scoring it zero.
"""


@dataclass(frozen=True, slots=True)
class ItemFacts:
    """The persisted state of one version item, as the columns record it."""

    source_item_id: str
    source_kind: str
    original_text: str
    proposed_text: str | None
    final_text: str
    #: The position the resume uses: proposed when a proposal arrived, the
    #: master's when none did.
    position: int = 0
    #: The master position a proposal displaced. **NULL means no proposal
    #: arrived** — on a row written after the column existed. On an older row it
    #: means only that nothing was recorded; see `position_evidence`.
    displaced_position: int | None = None


@dataclass(frozen=True, slots=True)
class FindingFacts:
    """One reviewer finding, as the columns record it."""

    source_item_id: str | None
    kind: str
    quoted_text: str | None


def _classify(
    item: ItemFacts | None,
    findings: Sequence[FindingFacts],
    *,
    contaminated: bool,
    position_evidence: bool,
) -> str:
    """Which state the persisted evidence supports for one planned emphasis.

    Ordered by strength of evidence, most conclusive first. Every branch rests
    on something a column records; nothing here reads meaning out of text.
    """
    if item is None:
        # The plan named an id the master does not contain. Nothing was ever
        # placeable against it, so there is no evidence either way.
        return "unknown" if contaminated else "no_evidence"

    grounding = [f for f in findings if f.kind in ("ungrounded", "overstated")]
    # A finding quoting words the owner never wrote is proof the draft rewrote
    # this line: `_REVIEW` permits `ungrounded`/`overstated` only against a
    # `(rewritten)` line, so the quote cannot have come from anywhere else.
    quotes_draft = [
        f for f in grounding if f.quoted_text and f.quoted_text not in item.original_text
    ]

    # An `ungrounded` finding discards its proposal and restores the owner's
    # wording (`finalisation_rules.finalise`), which is the only path that nulls
    # a proposal. A fabrication was attempted and stopped — not the same fact as
    # a draft that proposed nothing.
    if item.proposed_text is None and any(f.kind == "ungrounded" for f in grounding):
        return "discarded"

    if item.final_text != item.original_text:
        return "survived"

    # The proposal is byte-identical to the owner's wording *and* a finding
    # quotes something neither text contains: the draft wrote something else and
    # the revision put it back. The document did not change.
    if item.proposed_text is not None and quotes_draft:
        return "reverted"

    if item.proposed_text is not None or grounding:
        # Something was proposed, but nothing distinguishes a no-op proposal
        # from a reversion no finding recorded. Attempted is all the data says.
        return "attempted"

    # No text evidence. The position columns are the only remaining witness to
    # whether the draft named this item at all.
    if item.displaced_position is not None:
        # A reorder is an action with a visible effect on the document; a
        # proposal that left the position alone is an action without one. They
        # are counted the same by D1 and reported apart, because saying an item
        # moved when it did not is a claim the data does not support.
        return "reordered" if item.position != item.displaced_position else "proposed"

    if contaminated:
        # Pre-T094 the revision replaced the draft's item set, so an absent
        # proposal may have been erased rather than never made. Absence is not
        # evidence here, and recording it as such would credit the draft with a
        # failure the merge caused.
        return "unknown"

    if item.source_kind in LABEL_KINDS:
        # Checked before position evidence on purpose: `label_kind` is a
        # property of the *target*, not of the evidence, and it is the only
        # state D3 excludes from its denominator. Letting an old row fall
        # through to `unknown_position` instead would silently move every D3
        # figure already recorded.
        return "label_kind"

    if not position_evidence:
        # The row predates `displaced_position`, so its NULL records nothing.
        # "No proposal arrived" would be asserting absence from silence.
        return "unknown_position"

    return "no_evidence"


_ACTED = frozenset({"survived", "reverted", "discarded", "attempted", "reordered", "proposed"})


def plan_execution(
    plan: Mapping[str, Any] | None,
    *,
    items: Iterable[ItemFacts],
    findings: Iterable[FindingFacts],
    contaminated: bool = False,
    position_evidence: bool = False,
) -> dict[str, Any]:
    """What became of each planned emphasis, as states rather than one ratio.

    `emphasis_adherence` above answers "is there a proposal row for this id",
    which sits between two different questions and answers neither. It counts a
    proposal **reverted** to the owner's wording — the row survives with
    `proposed_text` set — while excluding one **discarded** as ungrounded, whose
    proposal is nulled. Harman is the case that makes this concrete: both of its
    D0 executions are reverted proposals, and its document changed nowhere.

    Two measures are reported because the product makes two separate promises:

    * **D1, draft compliance** — did the draft act on what the plan named? A
      reverted proposal *is* compliance: the draft executed the plan and a later
      step corrected it. This answers the FR-009 contract.
    * **D3, plan effect** — did the planned emphasis change the document the
      owner reads? A reverted or discarded proposal is not an effect. Label-kind
      targets leave the denominator, for the reason `LABEL_KINDS` gives.

    **Neither ratio is reported for a contaminated run.** Zipher's one known
    survival over its one determinable entry computes to 1.0, which would read
    as perfect execution of a plan whose other five outcomes were erased before
    anything could record them. The counts are still returned: what is known is
    reported, and what is unknowable is named rather than scored.

    No threshold, no gate — the same standing as the measure it sits beside.
    """
    directives = (plan or {}).get("emphasise") or []
    planned = len(directives)

    wanted: list[str] = []
    for directive in directives:
        if isinstance(directive, Mapping) and directive.get("source_item_id"):
            wanted.append(str(directive["source_item_id"]))

    # Deduplicated: a plan that names one line twice asked for one change, and
    # counting it twice scores a single rewrite as two (Cellebrite `cd5f3821`).
    distinct = list(dict.fromkeys(wanted))

    by_id = {item.source_item_id: item for item in items}
    findings_by_id: dict[str, list[FindingFacts]] = {}
    for finding in findings:
        if finding.source_item_id is not None:
            findings_by_id.setdefault(finding.source_item_id, []).append(finding)

    per_item = {
        item_id: _classify(
            by_id.get(item_id),
            findings_by_id.get(item_id, ()),
            contaminated=contaminated,
            position_evidence=position_evidence,
        )
        for item_id in distinct
    }

    states: dict[str, int] = {}
    for state in per_item.values():
        states[state] = states.get(state, 0) + 1

    unknown = states.get("unknown", 0)
    unknown_position = states.get("unknown_position", 0)
    acted = sum(1 for state in per_item.values() if state in _ACTED)
    survived = states.get("survived", 0)

    # D1 asks whether the draft acted, so a row that cannot say leaves its
    # denominator entirely — counting it would record a failure the data does
    # not support. The count is returned beside the ratio so a shrunken
    # denominator is never read without knowing it shrank.
    determinable = len(distinct) - unknown - unknown_position
    # D3 asks whether text survived, which is knowable however little is known
    # about ordering. Its denominator therefore excludes only `label_kind`, and
    # subtracting `unknown_position` here would move figures already recorded.
    addressable = len(distinct) - unknown - states.get("label_kind", 0)

    def ratio(numerator: int, denominator: int, *, blocked: int) -> float | None:
        if blocked or denominator <= 0:
            return None
        return round(numerator / denominator, 3)

    return {
        "planned": planned,
        "with_ids": len(wanted),
        "distinct": len(distinct),
        "duplicates_collapsed": len(wanted) - len(distinct),
        "contaminated": contaminated,
        "position_evidence": position_evidence,
        "states": states,
        "per_item": per_item,
        "d1_draft_compliance": {
            "acted": acted,
            "determinable": determinable,
            "unknown_position": unknown_position,
            "ratio": ratio(acted, determinable, blocked=unknown + unknown_position),
        },
        "d3_plan_effect": {
            "survived": survived,
            "addressable": addressable,
            "ratio": ratio(survived, addressable, blocked=unknown),
        },
    }


_ACTIONS = frozenset({"keep", "reframe", "rewrite"})

_TEXT_EVIDENCE = frozenset({"survived", "reverted", "discarded", "attempted"})
"""States that prove the draft acted on an item's *text*.

`reordered` and `proposed` are deliberately absent: a `reframe` answered only
by a move is non-compliance — the directive asked for wording, and a position
change is not wording. The same set read against a `keep` directive means the
draft acted where it was told not to, and a reverted or discarded proposal
still counts as a violation there: the draft acted; a later step corrected it.
"""

_UNKNOWABLE = frozenset({"unknown", "unknown_position"})


def action_execution(
    plan: Mapping[str, Any] | None,
    *,
    items: Iterable[ItemFacts],
    findings: Iterable[FindingFacts],
    contaminated: bool = False,
    position_evidence: bool = False,
) -> dict[str, Any]:
    """Did the draft do what each directive's `action` told it to?

    The action-aware measure for plans written under the `action` contract.
    `emphasis_adherence` and `plan_execution` above are **byte-identical to
    what they were** and keep grading every run — they are the accumulated
    distribution, and comparing their figures with this one is comparing two
    different promises: they ask "did a text proposal appear", which the old
    contract never actually demanded; this asks "was the stated action carried
    out", which the new one does. Report them side by side, never as one
    series.

    A plan with no `action` on every directive predates the contract and is
    answered with ``{"has_actions": False}`` and nothing else — a legacy run
    cannot be scored against a promise it never made, and inventing decisions
    for it retroactively would be exactly the ambiguity the field removes.

    Two exclusions keep the ratios honest rather than flattering:

    * A `reframe`/`rewrite` aimed at a label kind is the **plan's** violation,
      not the draft's — a skill has no wording to change — so it is reported
      as `invalid_target` and leaves the actionable denominator.
    * A `keep` with no `source_item_id` cannot be checked against any row, so
      it is counted (`keep_without_id`) and excluded from the compliance
      denominator rather than presumed compliant.

    No threshold, no gate — the same standing as the measures above.
    """
    directives = (plan or {}).get("emphasise") or []
    carrying = [d for d in directives if isinstance(d, Mapping) and d.get("action") in _ACTIONS]
    if not directives or len(carrying) != len(directives):
        # Legacy, empty, or malformed. `malformed_actions` is non-zero only in
        # the mixed case, which no valid completion can produce — its presence
        # is evidence of a bug, not of an old run.
        return {
            "has_actions": False,
            "malformed_actions": len(directives) - len(carrying) if carrying else 0,
        }

    # Deduplicated by target id, first directive wins — a plan that names one
    # line twice asked for one change (the Cellebrite lesson, unchanged). A
    # `keep` with no id has nothing to collide with and is kept as its own
    # entry, keyed for reporting only.
    chosen: dict[str, Mapping[str, Any]] = {}
    keep_without_id = 0
    for directive in directives:
        item_id = directive.get("source_item_id")
        if item_id is None:
            # The validator forbids this for reframe/rewrite, so only `keep`
            # lands here on data written through the schema.
            keep_without_id += 1
            continue
        chosen.setdefault(str(item_id), directive)
    duplicates_collapsed = (len(directives) - keep_without_id) - len(chosen)

    by_id = {item.source_item_id: item for item in items}
    findings_by_id: dict[str, list[FindingFacts]] = {}
    for finding in findings:
        if finding.source_item_id is not None:
            findings_by_id.setdefault(finding.source_item_id, []).append(finding)

    actions: dict[str, int] = {"keep": 0, "reframe": 0, "rewrite": 0}
    per_item: dict[str, dict[str, str]] = {}
    executed = actionable = invalid_target = 0
    keep_total = keep_compliant = keep_violations = 0
    unknowable = 0

    for item_id, directive in chosen.items():
        action = str(directive["action"])
        actions[action] += 1
        item = by_id.get(item_id)
        state = _classify(
            item,
            findings_by_id.get(item_id, ()),
            contaminated=contaminated,
            position_evidence=position_evidence,
        )
        per_item[item_id] = {"action": action, "state": state}

        if state in _UNKNOWABLE:
            unknowable += 1
            continue
        if action == "keep":
            keep_total += 1
            if state in _TEXT_EVIDENCE:
                keep_violations += 1
            else:
                keep_compliant += 1
        elif item is not None and item.source_kind in LABEL_KINDS:
            invalid_target += 1
        else:
            actionable += 1
            if state in _TEXT_EVIDENCE:
                executed += 1
    actions["keep"] += keep_without_id

    def ratio(numerator: int, denominator: int) -> float | None:
        # An unknowable outcome poisons both ratios the way `unknown` blocks
        # D1: what is known is still counted, but a figure computed over a
        # shrunken denominator would read as a claim about the whole plan.
        if unknowable or denominator <= 0:
            return None
        return round(numerator / denominator, 3)

    return {
        "has_actions": True,
        "actions": actions,
        "per_item": per_item,
        "duplicates_collapsed": duplicates_collapsed,
        "keep_without_id": keep_without_id,
        "unknowable": unknowable,
        "actionable_execution": {
            "executed": executed,
            "actionable": actionable,
            "invalid_target": invalid_target,
            "ratio": ratio(executed, actionable),
        },
        "keep_compliance": {
            "compliant": keep_compliant,
            "keep": keep_total,
            "violations": keep_violations,
            "ratio": ratio(keep_compliant, keep_total),
        },
    }


__all__ = [
    "LABEL_KINDS",
    "FindingFacts",
    "ItemFacts",
    "action_execution",
    "emphasis_adherence",
    "plan_execution",
]
