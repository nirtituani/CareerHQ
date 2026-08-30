"""What a Layer 2 role-research completion may return (slice 008).

Layer 2 differs from Layer 1 in exactly one structural way, and it is the whole
point of the layer: **its section set is variable, not fixed** (FR-022). What is
worth knowing about a backend role at an infrastructure company is not the same
set of headings as for a design role at the same employer, so Layer 1's five
named fields would force every brief into the shape of whichever role was
imagined first.

Everything else is deliberately identical to Layer 1 — the three tiers, their
differing evidence obligations (FR-028, FR-029), and the rule that an empty
thing explains itself. Reusing `Claim` rather than defining a parallel one is
what keeps `verify_excerpts` applicable to both layers.

**The obligations must be visible in the JSON Schema.** Slice 005 paid twice for
this: `model_validator(mode="after")` does not serialise, and the serialised
schema is the entire contract the gateway sends.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from careerhq.domain.schemas.research import (
    Claim,
    Evidence,
    ResearchSection,
    RoleFinding,
    RoleResearch,
)


def _finding(heading: str = "Architecture") -> RoleFinding:
    return RoleFinding(
        heading=heading,
        claims=[
            Claim(
                id="c1",
                text="They run a service-per-team topology.",
                tier="fact",
                evidence=[Evidence(source_id="s1", excerpt="a service per team")],
            )
        ],
    )


def _research(**overrides: object) -> RoleResearch:
    base: dict[str, object] = {
        "findings": [_finding()],
        "interview_preparation": ResearchSection(
            claims=[], empty_reason="No public material on their interview process."
        ),
    }
    base.update(overrides)
    return RoleResearch(**base)  # type: ignore[arg-type]


# -- FR-022: the section set is variable ------------------------------------


def test_findings_are_a_list_rather_than_named_fields() -> None:
    """The structural difference from Layer 1, asserted rather than assumed."""
    research = _research(findings=[_finding("Architecture"), _finding("Scale")])
    assert [f.heading for f in research.findings] == ["Architecture", "Scale"]


def test_a_finding_carries_its_own_heading() -> None:
    """Without a heading the list is an unlabelled pile of claims and the
    variability buys nothing."""
    assert _finding("Testing culture").heading == "Testing culture"


def test_a_heading_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        RoleFinding(heading="", claims=[_finding().claims[0]])


# -- silence and absence stay distinct --------------------------------------


def test_a_finding_with_no_claims_must_explain_itself() -> None:
    """The same rule `ResearchSection` enforces, for the same reason: a heading
    with nothing under it reads as "not applicable" when it may mean "we looked
    and found nothing"."""
    with pytest.raises(ValidationError, match="empty_reason"):
        RoleFinding(heading="Architecture", claims=[])


def test_a_finding_with_no_claims_is_valid_once_it_explains() -> None:
    finding = RoleFinding(
        heading="Architecture",
        claims=[],
        empty_reason="No public engineering material describes their architecture.",
    )
    assert finding.claims == []


def test_a_brief_with_no_findings_at_all_must_explain_itself() -> None:
    """The list-level counterpart. A Layer 2 brief that found nothing is a
    legitimate outcome (FR-024 forbids inventing technical detail), but an empty
    list with no reason is indistinguishable from a run that never happened."""
    with pytest.raises(ValidationError, match="no_findings_reason"):
        _research(findings=[])


def test_an_empty_brief_is_valid_once_it_explains() -> None:
    research = _research(
        findings=[], no_findings_reason="No reliable public source covered this role's stack."
    )
    assert research.findings == []


# -- FR-029: the tiers owe different evidence -------------------------------


def test_a_fact_in_a_finding_must_quote_a_source() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        RoleFinding(
            heading="Architecture",
            claims=[Claim(id="c1", text="They run Kubernetes.", tier="fact", evidence=[])],
        )


def test_an_interpretation_in_a_finding_must_name_what_it_rests_on() -> None:
    with pytest.raises(ValidationError, match="rests_on"):
        RoleFinding(
            heading="Architecture",
            claims=[Claim(id="c2", text="They value operational maturity.", tier="interpretation")],
        )


def test_an_inference_may_cite_nothing() -> None:
    """The only evidence-free tier, because it is the only one that does not
    claim a source said anything."""
    finding = RoleFinding(
        heading="Architecture",
        claims=[Claim(id="c3", text="They likely run a platform team.", tier="inference")],
    )
    assert finding.claims[0].evidence == []


# -- the schema is the contract ---------------------------------------------


def test_the_tier_obligations_survive_serialisation() -> None:
    """A rule that lives only in a validator is a rule the model is never shown.

    The gateway sends the serialised JSON Schema and nothing else, so the
    conditional requirements have to be in `description`, which serialises —
    not only in `model_validator`, which does not.
    """
    schema = json.dumps(RoleResearch.model_json_schema())
    for obligation in ("MUST have at least one entry", "MUST name at least one"):
        assert obligation in schema, (
            f"{obligation!r} is absent from the serialised schema; the model cannot follow "
            "a rule it is never sent"
        )


def test_the_variable_headings_are_explained_to_the_model() -> None:
    """The model chooses the headings, so the schema has to say what governs
    that choice — otherwise it invents Layer 1's five and the layer collapses."""
    schema = json.dumps(RoleResearch.model_json_schema()).lower()
    assert "role" in schema and "heading" in schema


# -- FR-022: the lens is the job, never the applicant -----------------------


def test_no_field_can_carry_the_applicant() -> None:
    """FR-022: Layer 2 "does not read the user's own profile or history — the
    lens is the job being applied for, not the applicant."

    A field named for the candidate would invite the synthesis prompt to weigh
    the person against the role, which is slice 004's job and not this one.
    """
    fields = list(RoleResearch.model_fields) + list(RoleFinding.model_fields)
    assert len(fields) >= 4, f"examined only {len(fields)} fields"
    forbidden = ("profile", "candidate", "applicant", "resume", "cv", "skill", "match")
    offenders = [f for f in fields if any(word in f.lower() for word in forbidden)]
    assert offenders == [], (
        f"Layer 2 carries {offenders}; FR-022 says the lens is the job, not the applicant"
    )
