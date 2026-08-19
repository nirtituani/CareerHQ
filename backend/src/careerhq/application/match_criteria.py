"""The scoring rubric, named and versioned.

`contracts/match-analysis.md` specifies it; `research.md` R9 records where it
came from and what was adapted. One module, so a v2 is a **new module** rather
than an edit to the thing history was scored under.

The model rates four dimensions. Everything here — the weighting, the bands, the
must-have cap — is deterministic application code, which is what makes a score
reproducible from a stored analysis and testable without a provider call.

**Changing any constant in this file is a new `CRITERIA_VERSION`.** Editing one
in place silently makes every historical score incomparable, and docs/07 §3.2
evaluates this capability on Match Score calibration — a measurement across
scores produced by different unnamed criteria measures nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from careerhq.domain.models import MatchBand, RequirementKind, RequirementVerdict

#: Adapted from `varunr89/resume-tailoring-skill` (MIT). Its dimensions scored
#: one experience against one template slot; the unit here is a whole profile
#: against a whole posting, so the weights carry over and the thresholds below
#: are ours. `v1` because a rubric arrived before implementation did — the
#: uncalibrated `v0` state the design planned for was never entered.
CRITERIA_VERSION = "v2-importance"

#: What each dimension is worth. Deliberately not an average: a direct match in
#: the same domain at comparable scale is worth four times an adjacent one.
WEIGHT_DIRECT = 0.4
WEIGHT_TRANSFERABLE = 0.3
WEIGHT_ADJACENT = 0.2
WEIGHT_IMPACT = 0.1

#: Lower bound of each band, highest first.
_BANDS: tuple[tuple[int, MatchBand], ...] = (
    (75, MatchBand.STRONG),
    (55, MatchBand.MODERATE),
    (35, MatchBand.STRETCH),
    (0, MatchBand.LOW_PROBABILITY),
)

#: An unmet requirement this important cannot produce a better band than
#: `_UNMET_CEILING`, whatever the arithmetic says.
#:
#: The threshold exists because a posting's own `must have` heading is routinely
#: a wishlist. If every stated requirement capped, every job would read
#: `stretch` and the band would stop discriminating — a uselessly pessimistic
#: signal traded for a too-generous one. So the model judges importance and this
#: is where "clearly required" starts. The prompt anchors the scale.
CAP_IMPORTANCE = 70

#: Verdicts that mean *the profile does not evidence this*.
#:
#: `unverified` is in here from v2, and it is the substantive change. A
#: recruiter reads exactly the profile the model reads and draws the same
#: conclusion from silence, so treating "your CV does not show this" as costless
#: models a reader who does not exist. The *claim* stays honest — `unverified`
#: still asserts nothing and still carries no evidence — but it is weighed
#: (research.md R10).
_UNMET = frozenset({RequirementVerdict.GAP, RequirementVerdict.UNVERIFIED})

_UNMET_CEILING = MatchBand.STRETCH

#: Band order, worst to best. Only used to make the ceiling a ceiling rather
#: than an assignment — a poor score that also fails a must-have must not be
#: promoted up to it.
_ORDER: tuple[MatchBand, ...] = (
    MatchBand.LOW_PROBABILITY,
    MatchBand.STRETCH,
    MatchBand.MODERATE,
    MatchBand.STRONG,
)


def overall_score(direct: int, transferable: int, adjacent: int, impact: int) -> int:
    """Combine the four rated dimensions into one 0-100 score.

    Computed here rather than asked of the model: a model returning both the
    parts and the total will sometimes return a total that does not follow from
    its parts, and the total is the one a person acts on.
    """
    weighted = (
        direct * WEIGHT_DIRECT
        + transferable * WEIGHT_TRANSFERABLE
        + adjacent * WEIGHT_ADJACENT
        + impact * WEIGHT_IMPACT
    )
    return round(weighted)


@dataclass(frozen=True, slots=True)
class Judged:
    """One requirement as the model judged it, for banding purposes.

    `kind` is what the posting **said**; `importance` is what the model
    **judged**. Both are kept, the same split as `status` and
    `normalized_status`: the source's own words are preserved and the value the
    system reasons over is derived, so neither can be quietly lost.
    """

    kind: RequirementKind
    verdict: RequirementVerdict
    importance: int


def band_for(score: int, *, requirements: Sequence[Judged]) -> MatchBand:
    """The band shown to the person, which is not simply the score bucketed.

    An **important** requirement the profile does not evidence caps the band,
    because a weighted sum hides exactly that: one unmet requirement barely
    moves four dimension ratings, so a profile can score 90 while missing the
    thing the role is actually about.

    Two things this does *not* do:

    * It does not cap on `partial` or `transferable`. Both are evidence of
      something, and most real profiles live there — capping on them would
      punish exactly the shape the five-verdict taxonomy exists to describe.
    * It does not trust the posting's `must have` heading. A `preferred`
      requirement the model judges critical caps; a `must_have` it judges
      incidental does not.

    Comparisons are `==`, never `is`. These values are stored in `String(16)`
    columns, so anything read back from the database is a plain `str` — and `is`
    would silently never match, disabling the cap with nothing raising and every
    band still looking plausible.
    """
    banded = next(band for lower, band in _BANDS if score >= lower)

    unmet_and_important = any(
        requirement.verdict in _UNMET and requirement.importance >= CAP_IMPORTANCE
        for requirement in requirements
    )
    if not unmet_and_important:
        return banded

    # min by position: a ceiling, never a promotion.
    return min(banded, _UNMET_CEILING, key=_ORDER.index)


__all__ = ["CAP_IMPORTANCE", "CRITERIA_VERSION", "Judged", "band_for", "overall_score"]
