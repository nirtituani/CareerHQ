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


@dataclass(frozen=True, slots=True)
class FindingFacts:
    """One reviewer finding, as the columns record it."""

    source_item_id: str | None
    kind: str
    quoted_text: str | None


def _classify(
    item: ItemFacts | None, findings: Sequence[FindingFacts], *, contaminated: bool
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

    if contaminated:
        # Pre-T094 the revision replaced the draft's item set, so an absent
        # proposal may have been erased rather than never made. Absence is not
        # evidence here, and recording it as such would credit the draft with a
        # failure the merge caused.
        return "unknown"

    if item.source_kind in LABEL_KINDS:
        return "label_kind"

    return "no_evidence"


_ACTED = frozenset({"survived", "reverted", "discarded", "attempted"})


def plan_execution(
    plan: Mapping[str, Any] | None,
    *,
    items: Iterable[ItemFacts],
    findings: Iterable[FindingFacts],
    contaminated: bool = False,
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
            by_id.get(item_id), findings_by_id.get(item_id, ()), contaminated=contaminated
        )
        for item_id in distinct
    }

    states: dict[str, int] = {}
    for state in per_item.values():
        states[state] = states.get(state, 0) + 1

    unknown = states.get("unknown", 0)
    acted = sum(1 for state in per_item.values() if state in _ACTED)
    survived = states.get("survived", 0)
    determinable = len(distinct) - unknown
    addressable = determinable - states.get("label_kind", 0)

    def ratio(numerator: int, denominator: int) -> float | None:
        if unknown or denominator <= 0:
            return None
        return round(numerator / denominator, 3)

    return {
        "planned": planned,
        "with_ids": len(wanted),
        "distinct": len(distinct),
        "duplicates_collapsed": len(wanted) - len(distinct),
        "contaminated": contaminated,
        "states": states,
        "per_item": per_item,
        "d1_draft_compliance": {
            "acted": acted,
            "determinable": determinable,
            "ratio": ratio(acted, determinable),
        },
        "d3_plan_effect": {
            "survived": survived,
            "addressable": addressable,
            "ratio": ratio(survived, addressable),
        },
    }


__all__ = [
    "LABEL_KINDS",
    "FindingFacts",
    "ItemFacts",
    "emphasis_adherence",
    "plan_execution",
]
