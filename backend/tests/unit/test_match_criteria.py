"""The rubric: `v1-weighted` (contracts/match-analysis.md, research.md R9).

The model rates four dimensions; the application computes the score and derives
the band. Asking the model for the parts *and* the total invites them to
disagree, and the total is the one a person acts on.

Band boundaries are tested at every edge rather than in the middle, because
off-by-one at a threshold is the failure a mid-range example never shows.
"""

from __future__ import annotations

import pytest

from careerhq.application.match_criteria import (
    CRITERIA_VERSION,
    band_for,
    overall_score,
)
from careerhq.domain.models import MatchBand, RequirementKind, RequirementVerdict


def test_the_criteria_version_is_named_and_stable() -> None:
    """FR-018. A score whose criteria are unnamed cannot be calibrated against.

    Changing the weights or the thresholds means a **new** version, never an
    edit — otherwise every historical score silently becomes incomparable, and
    docs/07 §3.2 evaluates this capability on Match Score calibration.
    """
    assert CRITERIA_VERSION == "v1-weighted"


@pytest.mark.parametrize(
    ("direct", "transferable", "adjacent", "impact", "expected"),
    [
        (100, 100, 100, 100, 100),
        (0, 0, 0, 0, 0),
        # 88*.4 + 82*.3 + 75*.2 + 80*.1 = 35.2 + 24.6 + 15 + 8 = 82.8 -> 83
        (88, 82, 75, 80, 83),
        # Weighting is not an average: a strong direct match carries the score.
        (100, 0, 0, 0, 40),
        (0, 100, 0, 0, 30),
        (0, 0, 100, 0, 20),
        (0, 0, 0, 100, 10),
    ],
)
def test_the_score_is_the_weighted_sum_of_the_four_dimensions(
    direct: int, transferable: int, adjacent: int, impact: int, expected: int
) -> None:
    assert overall_score(direct, transferable, adjacent, impact) == expected


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100, MatchBand.STRONG),
        (75, MatchBand.STRONG),
        (74, MatchBand.MODERATE),
        (55, MatchBand.MODERATE),
        (54, MatchBand.STRETCH),
        (35, MatchBand.STRETCH),
        (34, MatchBand.LOW_PROBABILITY),
        (0, MatchBand.LOW_PROBABILITY),
    ],
)
def test_band_boundaries_land_on_the_right_side(score: int, expected: MatchBand) -> None:
    assert band_for(score, requirements=[]) is expected


def test_a_failed_must_have_caps_the_band_however_good_the_arithmetic() -> None:
    """The rule that is in neither source, added because averages hide this.

    A profile scoring 90 on every dimension while failing a stated must-have is
    not a strong match. A weighted sum will report one cheerfully, because a
    single unmet requirement barely moves four dimension ratings.
    """
    requirements = [
        (RequirementKind.MUST_HAVE, RequirementVerdict.CONFIRMED),
        (RequirementKind.MUST_HAVE, RequirementVerdict.GAP),
        (RequirementKind.PREFERRED, RequirementVerdict.CONFIRMED),
    ]

    assert band_for(90, requirements=requirements) is MatchBand.STRETCH


def test_the_cap_does_not_promote_a_worse_score() -> None:
    """A cap is a ceiling, not an assignment.

    A genuinely poor match that also fails a must-have stays where it was; it
    must not be lifted *up* to `stretch` by the rule meant to hold scores down.
    """
    requirements = [(RequirementKind.MUST_HAVE, RequirementVerdict.GAP)]

    assert band_for(10, requirements=requirements) is MatchBand.LOW_PROBABILITY


@pytest.mark.parametrize(
    "verdict",
    [RequirementVerdict.PARTIAL, RequirementVerdict.TRANSFERABLE, RequirementVerdict.UNVERIFIED],
)
def test_only_an_outright_gap_on_a_must_have_caps_the_band(
    verdict: RequirementVerdict,
) -> None:
    """`unverified` must not cap, and that is the whole point of separating it.

    A profile that is merely silent about a must-have has not been shown to fail
    it. Capping on silence would punish the person for a thin CV rather than for
    a real shortfall — and would quietly restore the met/missing binary the
    five-verdict taxonomy exists to break.
    """
    requirements = [(RequirementKind.MUST_HAVE, verdict)]

    assert band_for(90, requirements=requirements) is MatchBand.STRONG
