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

from collections.abc import Iterable, Mapping
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


__all__ = ["emphasis_adherence"]
