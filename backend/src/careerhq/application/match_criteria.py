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

from careerhq.domain.models import MatchBand, RequirementKind, RequirementVerdict

#: Adapted from `varunr89/resume-tailoring-skill` (MIT). Its dimensions scored
#: one experience against one template slot; the unit here is a whole profile
#: against a whole posting, so the weights carry over and the thresholds below
#: are ours. `v1` because a rubric arrived before implementation did — the
#: uncalibrated `v0` state the design planned for was never entered.
CRITERIA_VERSION = "v1-weighted"

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

#: A failed must-have cannot produce a better band than this, whatever the
#: arithmetic says.
_MUST_HAVE_GAP_CEILING = MatchBand.STRETCH

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


def band_for(
    score: int,
    *,
    requirements: Sequence[tuple[RequirementKind, RequirementVerdict]],
) -> MatchBand:
    """The band shown to the person, which is not simply the score bucketed.

    A stated must-have the profile is **shown to fall short of** caps the band,
    because a weighted sum hides exactly that: one unmet requirement barely
    moves four dimension ratings, so a profile can score 90 while failing the
    thing the posting said was required.

    Note what does *not* cap: `unverified`. A profile merely silent about a
    must-have has not been shown to fail it, and capping on silence would punish
    a thin CV rather than a real shortfall — quietly restoring the met/missing
    binary the five-verdict taxonomy exists to break. `partial` and
    `transferable` do not cap either; both are evidence of something.
    """
    banded = next(band for lower, band in _BANDS if score >= lower)

    failed_must_have = any(
        kind is RequirementKind.MUST_HAVE and verdict is RequirementVerdict.GAP
        for kind, verdict in requirements
    )
    if not failed_must_have:
        return banded

    # min by position: a ceiling, never a promotion.
    return min(banded, _MUST_HAVE_GAP_CEILING, key=_ORDER.index)


__all__ = ["CRITERIA_VERSION", "band_for", "overall_score"]
