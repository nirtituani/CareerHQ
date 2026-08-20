"""The rubric: `v2-importance` (contracts/match-analysis.md, research.md R9, R10).

The model rates four dimensions and the importance of each requirement; the
application computes the score and derives the band.

**v2 changed two things from v1-weighted**, both recorded in R10:

* An unmet requirement is `gap` **or** `unverified`. The score answers *is this
  worth my evening*, and a recruiter reads the same profile the model does — so
  a requirement your CV does not evidence is a risk to the application whether
  or not the shortfall is provable.
* Importance is judged per requirement rather than taken from the posting's
  own `must have` heading, which is routinely a wishlist.

Band boundaries are tested at every edge rather than in the middle, because
off-by-one at a threshold is the failure a mid-range example never shows.
"""

from __future__ import annotations

import pytest

from careerhq.application.match_criteria import (
    CAP_IMPORTANCE,
    CRITERIA_VERSION,
    Judged,
    band_for,
    cap_bit,
    overall_score,
)
from careerhq.domain.models import MatchBand, RequirementKind, RequirementVerdict


def _req(
    verdict: RequirementVerdict,
    importance: int,
    kind: RequirementKind = RequirementKind.MUST_HAVE,
) -> Judged:
    return Judged(kind=kind, verdict=verdict, importance=importance)


def test_the_criteria_version_is_named_and_stable() -> None:
    """FR-018. A score whose criteria are unnamed cannot be calibrated against.

    Changing the weights, the thresholds or the cap rule means a **new**
    version, never an edit — otherwise every historical score silently becomes
    incomparable, and docs/07 §3.2 evaluates this capability on Match Score
    calibration. v1 scores exist and must stay distinguishable from v2 ones.
    """
    assert CRITERIA_VERSION == "v2-importance"


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


@pytest.mark.parametrize("verdict", [RequirementVerdict.GAP, RequirementVerdict.UNVERIFIED])
def test_an_unmet_important_requirement_caps_the_band(verdict: RequirementVerdict) -> None:
    """**v2: `unverified` caps too.** The reversal from v1, and why.

    v1 capped only on `gap`, reasoning that silence is not proof of absence.
    True about the *claim*, wrong about the *score*: a recruiter reads exactly
    the profile the model reads, and draws the same conclusion from silence. A
    score that treats "your CV does not evidence this" as costless models a
    reader who does not exist.

    The claim stays honest — `unverified` still asserts nothing and still
    carries no evidence. Only the weighing changed (research.md R10).
    """
    assert band_for(90, requirements=[_req(verdict, 85)]) is MatchBand.STRETCH


def test_an_unimportant_unmet_requirement_does_not_cap() -> None:
    """The whole point of judging importance rather than trusting the heading.

    Postings list wishlists under "must have". If every stated requirement
    capped, every job would read `stretch` and the band would stop
    discriminating — a uselessly pessimistic signal traded for a too-generous
    one.
    """
    assert band_for(90, requirements=[_req(RequirementVerdict.GAP, 30)]) is MatchBand.STRONG


def test_the_threshold_is_inclusive_at_its_edge() -> None:
    """An off-by-one here silently changes which jobs cap."""
    assert band_for(90, requirements=[_req(RequirementVerdict.GAP, CAP_IMPORTANCE)]) is (
        MatchBand.STRETCH
    )
    assert band_for(90, requirements=[_req(RequirementVerdict.GAP, CAP_IMPORTANCE - 1)]) is (
        MatchBand.STRONG
    )


@pytest.mark.parametrize(
    "verdict",
    [
        RequirementVerdict.CONFIRMED,
        RequirementVerdict.PARTIAL,
        RequirementVerdict.TRANSFERABLE,
    ],
)
def test_evidenced_verdicts_never_cap_however_important(verdict: RequirementVerdict) -> None:
    """`partial` and `transferable` are evidence of something, not absence.

    Capping on them would punish the profiles the five-verdict taxonomy exists
    to describe — most real ones are mostly `partial` and `transferable`.
    """
    assert band_for(90, requirements=[_req(verdict, 100)]) is MatchBand.STRONG


def test_importance_is_judged_not_taken_from_the_postings_heading() -> None:
    """A `preferred` requirement the model judges critical still caps.

    `kind` is what the posting *said*; `importance` is what the model *judged*.
    The same split as `status` and `normalized_status`: the source's own words
    are preserved, and the value the system reasons over is derived.
    """
    critical_but_labelled_optional = _req(
        RequirementVerdict.UNVERIFIED, 90, kind=RequirementKind.PREFERRED
    )

    assert band_for(90, requirements=[critical_but_labelled_optional]) is MatchBand.STRETCH


def test_the_cap_does_not_promote_a_worse_score() -> None:
    """A cap is a ceiling, not an assignment."""
    assert band_for(10, requirements=[_req(RequirementVerdict.GAP, 100)]) is (
        MatchBand.LOW_PROBABILITY
    )


def test_the_cap_fires_on_values_read_back_from_the_database() -> None:
    """These columns are `String(16)`, so a stored row returns plain `str`.

    `band_for` used to compare with `is`, which matches an enum member and never
    a string — so a re-run or recompute reading stored rows would have silently
    stopped capping, with nothing raising and every band looking plausible.
    Only a test that passes strings can catch it.
    """
    from_the_database = Judged(kind="must_have", verdict="gap", importance=90)  # type: ignore[arg-type]

    assert band_for(90, requirements=[from_the_database]) is MatchBand.STRETCH


def test_a_cap_that_changed_nothing_is_not_reported_as_one() -> None:
    """Reporting a cap that did not bite claims a causation that did not happen.

    A score of 54 is already `stretch` by arithmetic. An unmet critical
    requirement caps *to* `stretch` — so the band is the same either way, and
    telling a person their score was "capped by Kubernetes" would be false:
    removing Kubernetes entirely would not move the band.

    Found on the first real analysis after the breakdown shipped, where the
    interface was about to say exactly that.
    """
    critical_unmet = [_req(RequirementVerdict.UNVERIFIED, 75)]

    assert band_for(54, requirements=critical_unmet) is MatchBand.STRETCH
    assert band_for(54, requirements=[]) is MatchBand.STRETCH
    # Same band either way, so nothing was capped.
    assert cap_bit(54, requirements=critical_unmet) is False

    # A score that *would* have been moderate is genuinely held down.
    assert cap_bit(70, requirements=critical_unmet) is True


def test_a_cap_that_changed_nothing_is_not_reported_as_one_marker() -> None:
    assert cap_bit(90, requirements=[]) is False
