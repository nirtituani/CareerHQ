"""The grounding rule, as a validator (contracts/match-analysis.md).

The database constraint in `test_match_schema.py` protects the table whatever
writes to it. This protects the seam, earlier and far more legibly: by the
seam's obligation O2 a validation failure **is** an extraction failure, never
partially accepted and never repaired by hand, so a model that returns an
ungrounded verdict has told you it was guessing and the analysis is recorded
`failed`.

Both layers exist deliberately. One catches a bad completion before anything is
written; the other catches a code path that skipped the first.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from careerhq.domain.schemas.match import JudgedRequirement, MatchJudgement

_GROUNDED = ("confirmed", "partial", "transferable", "gap")


def _requirement(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "text": "5+ years building production backend services",
        "kind": "must_have",
        "importance": 90,
        "verdict": "confirmed",
        "shortfall": None,
        "evidence": "Led the payments platform team for six years.",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("verdict", _GROUNDED)
def test_a_verdict_that_makes_a_claim_needs_evidence(verdict: str) -> None:
    """AI-008. `gap` is in this list on purpose.

    *You fall short of this* is a claim about the person and needs the profile
    text that shows it, exactly as *you have this* does. An earlier draft let
    the negative verdict go unevidenced, which turned a silent profile into a
    confident "you do not have this" (research.md R9/D1).
    """
    with pytest.raises(ValidationError, match="evidence"):
        JudgedRequirement.model_validate(
            _requirement(
                verdict=verdict,
                evidence=None,
                shortfall=None if verdict == "confirmed" else "evidence",
            )
        )


def test_unverified_must_not_carry_evidence() -> None:
    """An equivalence, not an implication.

    `unverified` promises to assert nothing. A quote attached to it is an
    assertion under the one label that says there isn't one.
    """
    with pytest.raises(ValidationError, match="evidence"):
        JudgedRequirement.model_validate(
            _requirement(verdict="unverified", shortfall=None, evidence="Something.")
        )


def test_unverified_is_valid_with_no_evidence() -> None:
    """The honest answer must be *expressible*, or the model will pick another.

    If every verdict required evidence, a model faced with a silent profile has
    no truthful option left and will reach for `gap` — manufacturing the exact
    negative claim the taxonomy exists to prevent.
    """
    requirement = JudgedRequirement.model_validate(
        _requirement(verdict="unverified", shortfall=None, evidence=None)
    )

    assert requirement.evidence is None


@pytest.mark.parametrize("evidence", ["", "   ", "\n"])
def test_whitespace_does_not_count_as_evidence(evidence: str) -> None:
    """Otherwise the constraint is satisfiable with a space.

    The database CHECK only tests `IS NULL`, so an empty string would pass it.
    This is the layer that closes that, which is why both layers exist.
    """
    with pytest.raises(ValidationError, match="evidence"):
        JudgedRequirement.model_validate(_requirement(evidence=evidence))


def test_a_confirmed_requirement_has_no_shortfall() -> None:
    """A reason for falling short is meaningless on something the profile confirms."""
    with pytest.raises(ValidationError, match="shortfall"):
        JudgedRequirement.model_validate(_requirement(verdict="confirmed", shortfall="wording"))


@pytest.mark.parametrize("verdict", ["partial", "transferable", "gap"])
def test_an_evidenced_shortfall_states_which_kind_it_is(verdict: str) -> None:
    """FR-011c. Rephrase, prove, or acknowledge — the action differs.

    A list of unmet requirements that does not say which is a list of problems
    with no next step. These three are all *evidenced*, so the model has read
    something and can say what kind of shortfall it saw.
    """
    with pytest.raises(ValidationError, match="shortfall"):
        JudgedRequirement.model_validate(
            _requirement(verdict=verdict, shortfall=None, evidence="Six years, not ten.")
        )


def test_unverified_carries_no_shortfall_because_it_cannot_know() -> None:
    """The rule this originally got wrong, corrected against a real completion.

    The first version demanded a shortfall on every verdict except `confirmed`.
    A real Sonnet response failed validation on exactly this: four `unverified`
    requirements with no shortfall.

    **The model was right.** `unverified` means the profile says nothing, so
    choosing between `wording`, `evidence` and `capability` is guessing *why* it
    is silent — do you lack the skill, word it differently, or simply not have
    written it down? Nothing in the profile answers that. Demanding an answer
    reintroduces the invented absence the taxonomy exists to prevent, in the one
    field added to make shortfalls actionable.

    The action for `unverified` is the same in every case and needs no
    classification: put it on your CV if you have it.
    """
    requirement = JudgedRequirement.model_validate(
        _requirement(verdict="unverified", shortfall=None, evidence=None)
    )

    assert requirement.shortfall is None

    with pytest.raises(ValidationError, match="shortfall"):
        JudgedRequirement.model_validate(
            _requirement(verdict="unverified", shortfall="capability", evidence=None)
        )


def test_the_model_rates_no_dimensions_at_all() -> None:
    """v3 removed them, and removing them is the fix.

    v2 asked for `direct`, `transferable`, `adjacent` and `impact`, computed
    the score from those, and let the per-requirement verdicts feed nothing
    but the band cap. Two independent judgements about the same thing, so a
    real job returned every requirement addressed and a score of 48 -- the
    summary disagreeing with the detail rather than explaining it.
    """
    for dimension in ("direct", "adjacent", "impact"):
        assert dimension not in MatchJudgement.model_fields


def test_the_model_does_not_return_an_overall_score() -> None:
    """The score is computed, never asked for (contracts/match-analysis.md).

    A model returning both the parts and the total will sometimes return a total
    that does not follow from its parts, and the total is the one a person acts
    on. `match_criteria.overall_score` derives it instead.
    """
    assert "overall_score" not in MatchJudgement.model_fields
    assert "band" not in MatchJudgement.model_fields
