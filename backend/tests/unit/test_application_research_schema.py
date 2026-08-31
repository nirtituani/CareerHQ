"""ApplicationResearch (`app-v1`) — the provider output schema (T005).

Two kinds of assertion, deliberately separate:

* what the **validator** enforces (required fields, non-empty identification
  reasoning, list bounds) — what makes the rules true;
* what the **serialised JSON Schema** carries — what makes them followable.
  With a research provider the schema is the entire prompt-side contract, and
  Tavily 400s any property without a `description` (measured in the POC), so
  "every property carries one" is itself a gate here, walked recursively and
  asserting the count of what it examined.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from careerhq.domain.schemas.research import ApplicationResearch, CompanyIdentification


def _valid_payload() -> dict[str, object]:
    return {
        "company_identification": {
            "official_name": "Pango Pay & Go Ltd.",
            "website": "https://www.pango.co.il",
            "headquarters": "Petah Tikva, Israel",
            "how_identified": "Matched the posting's location and parking domain.",
        },
        "company_overview": "An Israeli smart-mobility company.",
        "products_and_services": "Mobile parking payments.",
        "business_and_market": "Transaction-fee SaaS.",
        "relevant_to_your_role": "Python and AWS at scale on the Parking team.",
        "what_to_know_before_the_interview": ["Owned by Milgam and Unicell."],
        "questions_worth_asking": ["How is DynamoDB scaled for peak parking traffic?"],
    }


def test_a_complete_result_validates() -> None:
    research = ApplicationResearch.model_validate(_valid_payload())
    assert research.company_identification.official_name.startswith("Pango")


@pytest.mark.parametrize("missing", sorted(ApplicationResearch.model_fields))
def test_every_field_is_required(missing: str) -> None:
    payload = _valid_payload()
    del payload[missing]
    with pytest.raises(ValidationError):
        ApplicationResearch.model_validate(payload)


def test_identification_reasoning_must_not_be_empty() -> None:
    """FR-007: `how_identified` is the wrong-entity tripwire. An identification
    that cannot say how it was made is an assertion, not an identification."""
    payload = _valid_payload()
    payload["company_identification"]["how_identified"] = ""  # type: ignore[index]
    with pytest.raises(ValidationError):
        ApplicationResearch.model_validate(payload)


def test_headquarters_is_the_only_optional_identification_field() -> None:
    payload = _valid_payload()
    del payload["company_identification"]["headquarters"]  # type: ignore[attr-defined]
    research = ApplicationResearch.model_validate(payload)
    assert research.company_identification.headquarters is None


@pytest.mark.parametrize("field", ["what_to_know_before_the_interview", "questions_worth_asking"])
def test_list_sections_are_bounded_one_to_twelve(field: str) -> None:
    payload = _valid_payload()
    payload[field] = []
    with pytest.raises(ValidationError):
        ApplicationResearch.model_validate(payload)
    payload[field] = ["item"] * 13
    with pytest.raises(ValidationError):
        ApplicationResearch.model_validate(payload)


def _walk_properties(schema: dict, path: str = "") -> list[tuple[str, dict]]:
    """Every property in the schema tree, with its path — including nested
    objects and array item schemas, resolved through $defs."""
    defs = schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        ref = node.get("$ref", "")
        if ref.startswith("#/$defs/"):
            return defs[ref.rsplit("/", 1)[-1]]
        return node

    found: list[tuple[str, dict]] = []

    def visit(node: dict, at: str) -> None:
        node = resolve(node)
        for name, prop in node.get("properties", {}).items():
            where = f"{at}.{name}" if at else name
            found.append((where, prop))
            target = resolve(prop)
            visit(target, where)
            items = target.get("items")
            if isinstance(items, dict):
                visit(resolve(items), f"{where}[]")
        for option in node.get("anyOf", []):
            if isinstance(option, dict) and option.get("type") != "null":
                visit(resolve(option), at)

    visit(schema, path)
    return found


def test_every_property_in_the_serialised_schema_carries_a_description() -> None:
    """The provider refuses schemas with description-less properties, and the
    descriptions are the only place conditional requirements reach the model
    (`model_validator` does not serialise — the 005 lesson)."""
    schema = ApplicationResearch.model_json_schema()
    properties = _walk_properties(schema)
    # A gate with nothing to examine passes forever: the walk must have found
    # at least the seven top-level sections plus the identification's fields.
    assert len(properties) >= 11, f"walked only {len(properties)} properties"
    missing = [path for path, prop in properties if not prop.get("description")]
    assert not missing, f"properties without a description: {missing}"


def test_the_role_sections_describe_the_no_posting_obligation() -> None:
    """D7/FR-011: when no posting was supplied the role sections must explain
    the absence. A validator cannot see whether a posting existed, so the rule
    lives in the descriptions the provider is sent — assert it is actually
    there, not merely intended."""
    schema = ApplicationResearch.model_json_schema()
    role = schema["properties"]["relevant_to_your_role"]["description"]
    assert "posting" in role.lower()


def test_identification_is_its_own_named_type() -> None:
    assert CompanyIdentification.model_fields.keys() == {
        "official_name",
        "website",
        "headquarters",
        "how_identified",
    }
