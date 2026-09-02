"""The v1 tier policy, as a table (advisor_tiers, product refinement slice).

The worked examples from the design plan ARE the test table: a change to the
thresholds must move a row here, deliberately. Pure functions over frozen
evidence dicts — no session, no provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from careerhq.application.advisor_tiers import (
    Tier,
    action_for,
    classify,
    topic_for,
)


def _skill_evidence(
    *, occurrences: int, coverage: int, gaps: int, topic: str = "AWS"
) -> dict[str, Any]:
    return {
        "facts": [
            {
                "fact_id": "tier2.requirement.g1",
                "scope_value": topic,
                "numerator": occurrences,
                "denominator": coverage,
            },
            {
                "fact_id": "tier2.gap.g1",
                "scope_value": topic,
                "numerator": gaps,
                "denominator": coverage,
            },
        ]
    }


# (occurrences, coverage, gaps) -> expected tier. The design plan's table.
_CASES = [
    # 1/1 and 2/2: coverage below the floor -> observation, whatever the gap.
    ((1, 1, 1), Tier.OBSERVATION),
    ((2, 2, 2), Tier.OBSERVATION),
    # 2/5: recurs twice, moderate prevalence -> emerging (never actionable).
    ((2, 5, 1), Tier.EMERGING),
    ((2, 5, 2), Tier.EMERGING),
    # 3/5: established (majority). Gap-heavy -> recommendation; met -> strength.
    ((3, 5, 3), Tier.RECOMMENDATION),
    ((3, 5, 0), Tier.STRENGTH),
    # 5/7: established, strong prevalence. gap 4 -> recommendation.
    ((5, 7, 4), Tier.RECOMMENDATION),
    # 6/8: established. gap 5 -> recommendation; gap 1 (rate 0.17) -> strength.
    ((6, 8, 5), Tier.RECOMMENDATION),
    ((6, 8, 1), Tier.STRENGTH),
    # A single occurrence is never more than an observation, at any coverage.
    ((1, 7, 1), Tier.OBSERVATION),
    # Established gap that does not clear the absolute-count floor (G>=3).
    ((4, 6, 2), Tier.PATTERN),
]


@pytest.mark.parametrize(
    ("counts", "expected"), _CASES, ids=[f"{o}of{c}_g{g}" for (o, c, g), _ in _CASES]
)
def test_the_v1_threshold_table(counts: tuple[int, int, int], expected: Tier) -> None:
    occurrences, coverage, gaps = counts
    tier = classify(_skill_evidence(occurrences=occurrences, coverage=coverage, gaps=gaps))
    assert tier == expected, f"{occurrences}/{coverage} gap {gaps} -> {tier}, expected {expected}"


def test_a_single_occurrence_is_never_a_recommendation() -> None:
    for coverage in range(1, 12):
        assert classify(_skill_evidence(occurrences=1, coverage=coverage, gaps=1)) != (
            Tier.RECOMMENDATION
        )


def test_tier1_memory_is_a_portfolio_insight_not_a_skill() -> None:
    tier1 = {
        "facts": [{"fact_id": "outcome.rejection_rate.global", "numerator": 6, "denominator": 12}]
    }
    assert classify(tier1) == Tier.PORTFOLIO
    assert action_for(Tier.PORTFOLIO, tier1) is None


def test_inconsistent_dates_fact_is_a_data_note() -> None:
    ev = {"facts": [{"fact_id": "timing.inconsistent_dates.global", "numerator": 96}]}
    assert classify(ev) == Tier.DATA_NOTE


def test_backward_compatible_with_evidence_lacking_facts() -> None:
    for shape in ({}, {"facts": []}, {"facts": "not-a-list"}, None):
        assert classify(shape) == Tier.PORTFOLIO  # never raises


def test_actions_only_for_recommendation_and_strength() -> None:
    assert action_for(Tier.RECOMMENDATION, {}) is not None
    assert action_for(Tier.STRENGTH, {}) is not None
    for tier in (Tier.OBSERVATION, Tier.EMERGING, Tier.PATTERN):
        assert action_for(tier, {}) is None, f"{tier} must not carry an action yet"


def test_topic_prefers_the_skill_then_scope_then_kind() -> None:
    skill = _skill_evidence(occurrences=5, coverage=7, gaps=4, topic="Kubernetes")
    assert topic_for(Tier.RECOMMENDATION, skill, kind="recurring_gap", scope_value=None) == (
        "Kubernetes"
    )
    assert topic_for(Tier.PORTFOLIO, {}, kind="outcome_pattern", scope_value="Backend") == (
        "Backend"
    )
    assert topic_for(Tier.PORTFOLIO, {}, kind="volume_trend", scope_value=None) == ("volume trend")
