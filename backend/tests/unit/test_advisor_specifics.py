"""The V2 mix, assessment and recommendation taxonomy (advisor_specifics).

Pure functions over resolved rows — no session, no provider. The taxonomy
table below is the specification: changing a threshold must move a row here,
deliberately, under a new `ADVISOR_ACTION_RULES_VERSION`.
"""

from __future__ import annotations

import uuid

import pytest

from careerhq.application.advisor_specifics import (
    ActionCategory,
    SpecificRequirement,
    Specifics,
    assess,
    mix_of,
    recommend,
    requirement_ids,
    specific_labels,
)
from careerhq.application.advisor_tiers import Tier


def _row(
    verdict: str,
    shortfall: str | None = None,
    *,
    text: str = "Experience with cloud platforms (e.g. AWS, GCP)",
    importance: int = 50,
    quote: str | None = None,
) -> SpecificRequirement:
    return SpecificRequirement(
        requirement_id=uuid.uuid4(),
        text=text,
        verdict=verdict,
        shortfall=shortfall,
        importance=importance,
        profile_quote=quote,
    )


def _specifics(*rows: SpecificRequirement, unresolved: int = 0) -> Specifics:
    return Specifics(items=list(rows), unresolved=unresolved)


# -- the mix -----------------------------------------------------------------


def test_the_mix_counts_verdicts_and_shortfalls() -> None:
    mix = mix_of(
        _specifics(
            _row("confirmed"),
            _row("partial", "capability"),
            _row("gap", "capability"),
            _row("unverified"),
        )
    )
    assert mix.total == 4
    assert mix.by_verdict["confirmed"] == 1
    assert mix.by_shortfall["capability"] == 2
    assert mix.shortfall_rows == 2, "only shortfall-bearing verdicts count"


def test_a_dominant_cause_needs_a_majority_and_no_tie() -> None:
    dominant = mix_of(_specifics(_row("gap", "capability"), _row("partial", "capability")))
    assert dominant.dominant_shortfall == "capability"

    tied = mix_of(_specifics(_row("gap", "capability"), _row("partial", "wording")))
    assert tied.dominant_shortfall is None, "a tie has no winner"

    scattered = mix_of(
        _specifics(
            _row("gap", "capability"),
            _row("partial", "wording"),
            _row("partial", "evidence"),
            _row("gap", "evidence"),
        )
    )
    # evidence is 2 of 4 shortfall rows — exactly the share, and unique.
    assert scattered.dominant_shortfall == "evidence"


def test_silence_is_measured_against_every_row_not_just_shortfalls() -> None:
    assert mix_of(_specifics(_row("unverified"), _row("unverified"), _row("confirmed"))).silent
    assert not mix_of(_specifics(_row("unverified"), _row("confirmed"), _row("confirmed"))).silent


# -- the taxonomy table ------------------------------------------------------

_CASES = [
    # (tier, rows, expected category)
    (
        "capability gap -> learn",
        Tier.RECOMMENDATION,
        [_row("gap", "capability"), _row("partial", "capability"), _row("gap", "capability")],
        ActionCategory.LEARN_BUILD,
    ),
    (
        "evidence gap -> prove",
        Tier.RECOMMENDATION,
        [_row("partial", "evidence"), _row("gap", "evidence")],
        ActionCategory.PROVE_IT,
    ),
    (
        "wording gap -> surface",
        Tier.RECOMMENDATION,
        [_row("partial", "wording"), _row("partial", "wording")],
        ActionCategory.SURFACE_IT,
    ),
    (
        "silent profile -> add if you have it",
        Tier.RECOMMENDATION,
        [_row("unverified"), _row("unverified"), _row("gap", "capability")],
        ActionCategory.ADD_IF_YOU_HAVE_IT,
    ),
    (
        "strength -> keep leading",
        Tier.STRENGTH,
        [_row("confirmed"), _row("confirmed")],
        ActionCategory.KEEP_LEADING,
    ),
    (
        "mixed causes -> no action yet",
        Tier.RECOMMENDATION,
        [_row("gap", "capability"), _row("partial", "wording")],
        ActionCategory.NO_ACTION_YET,
    ),
    (
        "emerging tier is watched, not acted on",
        Tier.EMERGING,
        [_row("gap", "capability"), _row("gap", "capability")],
        ActionCategory.NO_ACTION_YET,
    ),
    (
        "observation tier is watched, not acted on",
        Tier.OBSERVATION,
        [_row("gap", "capability")],
        ActionCategory.NO_ACTION_YET,
    ),
    (
        "pattern tier can act",
        Tier.PATTERN,
        [_row("gap", "capability"), _row("partial", "capability")],
        ActionCategory.LEARN_BUILD,
    ),
]


@pytest.mark.parametrize(
    ("tier", "rows", "expected"),
    [(t, r, e) for _, t, r, e in _CASES],
    ids=[name for name, _, _, _ in _CASES],
)
def test_the_recommendation_taxonomy(
    tier: Tier, rows: list[SpecificRequirement], expected: ActionCategory
) -> None:
    action = recommend(tier, mix_of(_specifics(*rows)))
    assert action is not None
    assert action.category == expected
    assert action.text, "every category carries user-facing text"


def test_portfolio_and_data_notes_get_no_action_or_assessment() -> None:
    mix = mix_of(_specifics())
    for tier in (Tier.PORTFOLIO, Tier.DATA_NOTE):
        assert recommend(tier, mix) is None
        assert assess(tier, mix) is None


def test_unresolvable_rows_yield_an_honest_refusal_not_a_guess() -> None:
    """Every underlying row deleted: the claim stands, the advice cannot."""
    empty = mix_of(_specifics(unresolved=4))
    action = recommend(Tier.RECOMMENDATION, empty)
    assert action is not None and action.category == ActionCategory.NO_ACTION_YET
    assert assess(Tier.RECOMMENDATION, empty) == (
        "The requirements behind this claim are no longer available to read."
    )


# -- assessment --------------------------------------------------------------


def test_assessment_never_restates_a_statistic() -> None:
    """The counts belong in the headline, once. An assessment carrying digits
    would be the V1 duplication returning in a new place."""
    for tier, rows in (
        (Tier.RECOMMENDATION, [_row("gap", "capability"), _row("gap", "capability")]),
        (Tier.RECOMMENDATION, [_row("partial", "evidence"), _row("gap", "evidence")]),
        (Tier.RECOMMENDATION, [_row("unverified"), _row("unverified")]),
        (Tier.STRENGTH, [_row("confirmed")]),
        (Tier.RECOMMENDATION, [_row("gap", "capability"), _row("partial", "wording")]),
    ):
        line = assess(tier, mix_of(_specifics(*rows)))
        assert line is not None
        assert not any(char.isdigit() for char in line), f"digits leaked into: {line}"


# -- pointer chain and labels ------------------------------------------------


def test_requirement_ids_prefer_the_requirement_fact_over_the_gap_subset() -> None:
    everyone = [str(uuid.uuid4()) for _ in range(4)]
    evidence = {
        "facts": [
            {"fact_id": "tier2.gap.g1", "record_ids": everyone[:2]},
            {"fact_id": "tier2.requirement.g1", "record_ids": everyone},
        ]
    }
    assert [str(i) for i in requirement_ids(evidence)] == everyone


def test_requirement_ids_fall_back_to_the_gap_fact_and_survive_junk() -> None:
    only_gap = {"facts": [{"fact_id": "tier2.gap.g1", "record_ids": [str(uuid.uuid4())]}]}
    assert len(requirement_ids(only_gap)) == 1

    for shape in (
        {},
        None,
        {"facts": "nope"},
        {"facts": [{"fact_id": "tier2.requirement.g", "record_ids": ["not-a-uuid"]}]},
    ):
        assert requirement_ids(shape) == []


def test_labels_are_verbatim_shortened_never_generalised() -> None:
    long_ask = (
        "Deep understanding of cloud infrastructure (AWS/GCP), containerisation and networking"
    )
    labels = specific_labels(_specifics(_row("partial", "capability", text=long_ask)))
    assert len(labels) == 1
    assert labels[0].endswith("…") and len(labels[0]) <= 48
    assert long_ask.startswith(labels[0][:20]), "the label is a prefix of the row, not a paraphrase"


def test_labels_cap_at_three_for_the_compact_card() -> None:
    rows = [_row("gap", "capability", text=f"Requirement {i}") for i in range(6)]
    assert len(specific_labels(_specifics(*rows))) == 3


def test_profile_quotes_are_deduped_in_row_order() -> None:
    quote = "Building and deploying cloud-based applications"
    specifics = _specifics(
        _row("partial", "capability", quote=quote),
        _row("confirmed", quote=quote),
        _row("gap", "capability", quote="Another line"),
        _row("unverified"),
    )
    assert specifics.profile_quotes == [quote, "Another line"]
