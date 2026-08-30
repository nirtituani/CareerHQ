"""What a Layer 1 company-research completion may return (slice 008).

Three rules are enforced here, and each was decided rather than assumed:

* **Every claim carries a tier** — `fact`, `interpretation` or `inference`
  (spec FR-028). The tiers exist so a reader can weigh confidence, which is the
  distinction slice 004 drew when it made `unverified` an explicit verdict
  rather than an omission.
* **The tiers owe different evidence** (FR-029). A `fact` must quote a source;
  an `interpretation` must name the facts it rests on; an `inference` may cite
  nothing but is never renderable as a fact.
* **Layer 1 is role-independent** (FR-021). The schema carries no field through
  which a job could reach it, so the reuse guarantee is structural rather than a
  rule someone must remember.

**The conditional requirements must be visible in the JSON Schema**, not only in
a validator. Slice 005 paid for this twice: `model_validator(mode="after")` does
not serialise, and the serialised schema is the entire contract the gateway
sends the model. A rule the model cannot see is a rule it cannot follow.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from careerhq.domain.schemas.research import (
    Claim,
    CompanyResearch,
    Evidence,
    ResearchSection,
)


def _evidence() -> list[Evidence]:
    return [Evidence(source_id="s1", excerpt="They process payments for European retailers.")]


def _fact(claim_id: str = "c1") -> Claim:
    return Claim(
        id=claim_id,
        text="They process payments for European retailers.",
        tier="fact",
        evidence=_evidence(),
    )


# --- the tier obligations ---------------------------------------------------


def test_a_fact_must_quote_a_source() -> None:
    """FR-029. An uncited fact is the thing FR-007 makes unrepresentable."""
    with pytest.raises(ValidationError) as exc:
        Claim(id="c1", text="They process payments.", tier="fact")
    assert "evidence" in str(exc.value)


def test_a_fact_with_evidence_is_accepted() -> None:
    claim = _fact()
    assert claim.evidence[0].excerpt.startswith("They process payments")


def test_an_interpretation_must_name_the_facts_it_rests_on() -> None:
    """An interpretation is a reading *of* stated facts. One that rests on
    nothing is an inference wearing a stronger label."""
    with pytest.raises(ValidationError) as exc:
        Claim(
            id="c2",
            text="The volume implies a high-throughput transactional system.",
            tier="interpretation",
        )
    assert "rests_on" in str(exc.value)


def test_an_interpretation_that_names_its_facts_is_accepted() -> None:
    claim = Claim(
        id="c2",
        text="The volume implies a high-throughput transactional system.",
        tier="interpretation",
        rests_on=["c1"],
    )
    assert claim.rests_on == ["c1"]


def test_an_inference_may_cite_nothing_and_is_still_labelled() -> None:
    """FR-029's third tier. It asserts beyond the sources, so requiring a quote
    would make it unrepresentable — but the tier itself is the warning."""
    claim = Claim(id="c3", text="They likely run an event-driven architecture.", tier="inference")
    assert claim.tier == "inference"
    assert claim.evidence == [] and claim.rests_on == []


def test_a_tier_outside_the_three_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim(id="c4", text="Something.", tier="speculation")  # type: ignore[arg-type]


# --- the rules must reach the model, not just the validator -----------------


def test_the_tier_obligations_are_visible_in_the_json_schema() -> None:
    """**The slice 005 lesson, as a gate.** `model_validator(mode="after")` does
    not serialise. If the obligations live only there, the model is asked to
    satisfy a contract it was never shown."""
    schema = json.dumps(Claim.model_json_schema()).lower()

    assert "fact" in schema and "interpretation" in schema and "inference" in schema
    assert "evidence" in schema, "the fact obligation must be stated in the schema"
    assert "rests_on" in schema, "the interpretation obligation must be stated in the schema"
    assert "must" in schema, (
        "the conditional requirements have to be spelled out in Field(description=...), "
        "which serialises — a validator alone is invisible to the model"
    )


# --- Layer 1 shape ----------------------------------------------------------


def test_layer_one_carries_every_section_by_construction() -> None:
    """FR: each section present even when empty. Named fields rather than a
    list, so a missing section cannot be expressed."""
    assert set(CompanyResearch.model_fields) == {
        "what_the_company_does",
        "products_and_services",
        "market_and_customers",
        "practical_facts",
        "interview_preparation",
    }


def test_an_empty_section_must_say_why() -> None:
    """Silence and absence must be distinguishable — the slice 004 rule."""
    with pytest.raises(ValidationError) as exc:
        ResearchSection(claims=[])
    assert "empty_reason" in str(exc.value)


def test_an_empty_section_with_a_reason_is_accepted() -> None:
    section = ResearchSection(claims=[], empty_reason="No public pricing information was found.")
    assert section.claims == []


def test_a_section_with_claims_needs_no_reason() -> None:
    section = ResearchSection(claims=[_fact()])
    assert section.empty_reason is None


# --- role independence, structurally ---------------------------------------


def test_layer_one_has_no_field_through_which_a_role_could_reach_it() -> None:
    """FR-021. Layer 1 must read identically for two different jobs at the same
    employer; the cheapest way to guarantee that is to give the schema nowhere
    to put a role."""
    schema = CompanyResearch.model_json_schema()

    def property_names(node: object) -> set[str]:
        """Every field name anywhere in the schema, definitions included.

        Field names, deliberately — not the whole serialised blob. Prose may
        legitimately mention the role-specific layer; what must not exist is a
        *channel* through which a job could arrive.
        """
        found: set[str] = set()
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                found |= {str(k).lower() for k in props}
            for value in node.values():
                found |= property_names(value)
        elif isinstance(node, list):
            for value in node:
                found |= property_names(value)
        return found

    names = property_names(schema)
    assert names, "the walk found no properties — a gate with nothing to examine passes forever"
    for forbidden in ("job_title", "job_description", "role", "requirements", "application_id"):
        assert forbidden not in names, (
            f"Layer 1 must be role-independent, but its schema has a {forbidden!r} field — "
            "that is a channel through which a job could shape the general layer"
        )
