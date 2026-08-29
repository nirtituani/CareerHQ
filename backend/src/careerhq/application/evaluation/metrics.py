"""What the numbers are, and what each one refuses to say.

Every metric here is a **pure function over persisted facts**, in the shape
`plan_adherence` already established: dataclasses describing what the columns
record, and no database access. That is not tidiness — it is what lets each
definition be developed and drilled against the thirteen runs this project has
already paid for, before a single benchmark case is billed.

**Four rules, and each has a test that has been watched failing.**

1. **`n` travels with the value.** `MetricValue` cannot be constructed measured
   without one, so "not measured" and "zero" are different objects rather than
   different readings of the same float.
2. **Only persisted records are read.** No metric infers a value the system did
   not store.
3. **Every metric is versioned.** Changing how a number is computed is a new
   `METRIC_VERSION`, never an edit — otherwise every historical result is silently
   reinterpreted, which is the rule the match criteria and the finalisation rules
   already follow.
4. **A metric refuses rather than guesses.** Eligibility — canned responses, a
   static fallback, an off-mix model set — is checked in `eligibility.py` and is
   not this module's business; what *is* this module's business is never turning
   an absence of evidence into a number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: Bumped whenever *how* any number here is computed changes.
#:
#: **A new version, never an edit.** Two results computed under different versions
#: are not comparable, and the version is written into every result file so the
#: comparison can refuse rather than average over the difference.
METRIC_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One number, the count it was computed over, and why it might be absent.

    **`value is None` and `value == 0.0` are different facts and this type refuses
    to conflate them.** `plan_adherence.emphasis_adherence` already returns `None`
    rather than `0.0` for a plan with nothing addressable in it; a posting that
    yielded no requirements is already "nothing to score against, not a zero". This
    is that rule, made impossible to get wrong by construction.
    """

    value: float | None = None
    n: int = 0
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.value is not None and self.n <= 0:
            raise ValueError(
                "a measured value must carry the count it was computed over; "
                "use MetricValue.not_measured() when there is nothing to measure"
            )

    @property
    def measured(self) -> bool:
        return self.value is not None

    @classmethod
    def not_measured(cls, *, reason: str, detail: dict[str, Any] | None = None) -> MetricValue:
        return cls(value=None, n=0, reason=reason, detail=detail or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "n": self.n,
            "measured": self.measured,
            "reason": self.reason,
            **({"detail": self.detail} if self.detail else {}),
        }


@dataclass(frozen=True, slots=True)
class ClaimFacts:
    """One proposed line, as the version's columns record it."""

    item_id: str
    source_item_id: str | None
    proposed_text: str | None
    original_text: str
    final_text: str


@dataclass(frozen=True, slots=True)
class FindingRecord:
    """One reviewer finding, as the columns record it."""

    item_id: str | None
    kind: str
    detail: str = ""
    quoted_text: str | None = None


@dataclass(frozen=True, slots=True)
class RequirementFacts:
    """One requirement the posting stated, and whether it was a must-have."""

    text: str
    must_have: bool


@dataclass(frozen=True, slots=True)
class GuidelineRecord:
    """One guideline a run consumed, joined to the document that produced it."""

    document_slug: str
    #: `integrity` means pinned — returned regardless of the query.
    source_type: str


# -- Grounding accuracy -------------------------------------------------------


def grounding(*, claims: list[ClaimFacts], findings: list[FindingRecord]) -> dict[str, Any]:
    """What proportion of what the agent proposed traces to a profile fact.

    **`persisted_ungrounded` is the load-bearing number and it must be 0** (SC-006,
    FR-015). The severity split runs in the use case *before any row is written*: an
    `ungrounded` finding discards its proposal and restores the owner's wording, so
    a fabricated claim has no persisted representation and can never reach an
    approve button. That guarantee is structural today; this is the measurement that
    would notice the day it stopped being.

    **`traceable` counts a proposal with no `source_item_id` against itself.**
    Without an id nothing maps back to a profile fact — which is exactly the failure
    two paid runs hit in slice 005, where the master carried no ids and a "passing"
    run would have persisted a diff with zero changes.
    """
    proposals = [
        c for c in claims if c.proposed_text is not None or c.final_text != c.original_text
    ]
    ungrounded_ids = {f.item_id for f in findings if f.kind == "ungrounded" and f.item_id}

    if not claims:
        traceable = MetricValue.not_measured(reason="the run proposed nothing to trace")
    else:
        traced = sum(1 for c in claims if c.source_item_id is not None)
        traceable = MetricValue(value=traced / len(claims), n=len(claims))

    # A proposal that the Reviewer called ungrounded and that is *still there*.
    leaked = sum(
        1
        for c in claims
        if c.item_id in ungrounded_ids
        and (c.proposed_text is not None or c.final_text != c.original_text)
    )

    return {
        "traceable": traceable,
        "ungrounded_caught": sum(1 for f in findings if f.kind == "ungrounded"),
        "overstated_flagged": sum(1 for f in findings if f.kind == "overstated"),
        "persisted_ungrounded": leaked,
        "proposals": len(proposals),
    }


# -- Requirement coverage -----------------------------------------------------


def _mentions(requirement: str, detail: str) -> bool:
    """Whether a free-text finding is plausibly about this requirement.

    **Textual and fallible, which is why `unmatched_findings` is reported.** An
    `uncovered` finding carries no requirement reference and the schema forbids it
    an item, deliberately — slice 004 established that demanding a structured field
    a model has no honest basis to fill produces invented answers. So the match is
    made here, crudely, and its crudeness is reported rather than hidden.
    """
    haystack = detail.lower()
    needle = requirement.lower()
    if needle in haystack:
        return True
    words = [w for w in needle.replace("/", " ").split() if len(w) > 3]
    if not words:
        return False
    return sum(1 for w in words if w in haystack) >= max(1, len(words) // 2)


def coverage(
    *, requirements: list[RequirementFacts], uncovered: list[FindingRecord]
) -> dict[str, Any]:
    """How much of the posting's requirement list the résumé addresses.

    **Must-have coverage is reported separately from overall** (FR-016): a résumé
    addressing every nice-to-have and no must-have is not 50% good.

    **This is the Reviewer-reported figure and it must never travel alone.** It
    measures the Reviewer's opinion of coverage, so it cannot detect the Reviewer
    becoming wrong — which has happened: on Zipher it reported eight requirements
    "never addressed" against bullets sitting untouched in the résumé, because it
    had been shown the diff rather than the document. The independently judged
    figure is the control, and their divergence is the only check this project has
    on its own Reviewer.
    """
    findings = [f for f in uncovered if f.kind == "uncovered"]

    if not requirements:
        empty = MetricValue.not_measured(
            reason="the posting yielded no requirements — nothing to score against, not a zero"
        )
        return {"overall": empty, "must_have": empty, "unmatched_findings": len(findings)}

    matched: set[int] = set()
    unmatched = 0
    for finding in findings:
        hits = [i for i, r in enumerate(requirements) if _mentions(r.text, finding.detail)]
        if hits:
            matched.update(hits)
        else:
            unmatched += 1

    overall = MetricValue(
        value=(len(requirements) - len(matched)) / len(requirements), n=len(requirements)
    )

    musts = [i for i, r in enumerate(requirements) if r.must_have]
    if musts:
        must_missed = len([i for i in musts if i in matched])
        must_have = MetricValue(value=(len(musts) - must_missed) / len(musts), n=len(musts))
    else:
        must_have = MetricValue.not_measured(reason="the posting stated no must-have requirements")

    return {"overall": overall, "must_have": must_have, "unmatched_findings": unmatched}


# -- Retrieval quality --------------------------------------------------------


def retrieval_quality(
    *, guidelines: list[GuidelineRecord], relevant_slugs: set[str] | None
) -> dict[str, Any]:
    """Whether the guidance retrieved for a posting is relevant to it.

    **Two figures, and collapsing them into one would report a floor as an
    achievement.** The returned set always contains the pinned integrity rules,
    which appear regardless of the query and are relevant by construction. Only the
    *selected* rules were chosen because of this posting, so only they can be right
    or wrong about it.

    `relevant_slugs=None` means nobody has judged relevance yet. The structural
    figures still compute; the relevance figure reports *not measured* rather than
    assuming everything retrieved was wanted.
    """
    pinned = [g for g in guidelines if g.source_type == "integrity"]
    selected = [g for g in guidelines if g.source_type != "integrity"]

    if guidelines:
        pinned_proportion = MetricValue(value=len(pinned) / len(guidelines), n=len(guidelines))
    else:
        pinned_proportion = MetricValue.not_measured(reason="the run retrieved nothing")

    if relevant_slugs is None:
        relevance = MetricValue.not_measured(
            reason="no relevance judgement has been recorded for this retrieval"
        )
    elif not selected:
        relevance = MetricValue.not_measured(
            reason="nothing was selected — only pinned integrity rules were returned, "
            "and those are relevant by construction"
        )
    else:
        hits = sum(1 for g in selected if g.document_slug in relevant_slugs)
        relevance = MetricValue(value=hits / len(selected), n=len(selected))

    return {
        "pinned": len(pinned),
        "selected": len(selected),
        "pinned_proportion": pinned_proportion,
        "selected_relevance": relevance,
    }


# -- Match-score calibration --------------------------------------------------

#: Below this, a correlation is a description of four points rather than evidence.
#: A floor rather than a claim about statistical power: the honest output at these
#: sample sizes is a direction and an `n`, never a coefficient presented as settled.
_MIN_CALIBRATION_SAMPLE = 4


def calibration(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """Whether higher match scores correspond to better-rated résumés.

    **Reports its sample size rather than implying one** (FR-018). At the sample
    sizes this slice can afford, the coefficient is a direction with an `n` attached
    and is presented as nothing more.

    A constant score reports *not measured*, never `0.0`: zero variance makes the
    coefficient undefined, and a spurious `0.0` would read as "uncorrelated" — a
    finding, where the truth is that there is nothing to find.
    """
    if len(pairs) < _MIN_CALIBRATION_SAMPLE:
        return {
            "correlation": MetricValue.not_measured(
                reason=f"{len(pairs)} pairs is below the floor of {_MIN_CALIBRATION_SAMPLE}"
            )
        }

    scores = [p[0] for p in pairs]
    ratings = [p[1] for p in pairs]
    mean_s = sum(scores) / len(scores)
    mean_r = sum(ratings) / len(ratings)
    var_s = sum((s - mean_s) ** 2 for s in scores)
    var_r = sum((r - mean_r) ** 2 for r in ratings)

    if var_s == 0 or var_r == 0:
        return {
            "correlation": MetricValue.not_measured(
                reason="no variance on one side — a correlation would be undefined, and "
                "reporting 0.0 would read as 'uncorrelated' rather than 'nothing to find'"
            )
        }

    covariance = sum((s - mean_s) * (r - mean_r) for s, r in pairs)
    return {"correlation": MetricValue(value=covariance / math.sqrt(var_s * var_r), n=len(pairs))}


__all__ = [
    "METRIC_VERSION",
    "ClaimFacts",
    "FindingRecord",
    "GuidelineRecord",
    "MetricValue",
    "RequirementFacts",
    "calibration",
    "coverage",
    "grounding",
    "retrieval_quality",
]
