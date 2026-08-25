"""The schema rules that carry Principle III, tested without a provider.

Each of these encodes something slice 004 learned by shipping the opposite.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from careerhq.application.agents.tailoring.prompts import _REVIEW
from careerhq.domain.schemas.tailoring import DraftedItem, ReviewFinding, ReviewResult


def test_an_ungrounded_finding_must_quote_what_it_objects_to() -> None:
    """Otherwise the model can assert an absence it cannot support.

    That is AI-008's fabrication pointed the other way, and it is also
    untestable and undisplayable — nothing can show the owner *which* words the
    Reviewer meant.
    """
    with pytest.raises(ValidationError, match="must quote"):
        ReviewFinding(
            kind="ungrounded",
            source_item_id=uuid.uuid4(),
            detail="Claims Kubernetes experience the profile does not contain.",
            quoted_text=None,
        )


def test_a_whitespace_quote_does_not_count_as_a_quote() -> None:
    """`quoted_text=" "` satisfies a null check and nothing else."""
    with pytest.raises(ValidationError, match="must quote"):
        ReviewFinding(
            kind="ungrounded",
            source_item_id=uuid.uuid4(),
            detail="Unsupported.",
            quoted_text="   ",
        )


def test_an_uncovered_finding_must_not_name_an_item() -> None:
    """There is no item for an unaddressed requirement to attach to.

    Slice 004 demanded a `shortfall` reason on `unverified` and a real
    completion failed validation on it — the model was right, because the
    profile's silence gave no basis for choosing one. Manufacturing an item
    reference here would be the same mistake.
    """
    with pytest.raises(ValidationError, match="concerns the draft"):
        ReviewFinding(
            kind="uncovered",
            source_item_id=uuid.uuid4(),
            detail="The posting asks for Terraform; the draft never mentions it.",
        )


def test_an_uncovered_finding_is_valid_with_no_item() -> None:
    finding = ReviewFinding(
        kind="uncovered",
        detail="The posting asks for Terraform; the draft never mentions it.",
    )
    assert finding.source_item_id is None


@pytest.mark.parametrize("kind", ["ungrounded", "overstated"])
def test_an_item_level_finding_must_name_its_item(kind: str) -> None:
    """The converse rule. A concern about a bullet that cannot say which bullet
    lands in the interface as a banner, which is the presentation FR-042 exists
    to prevent."""
    with pytest.raises(ValidationError, match="must name the item"):
        ReviewFinding(kind=kind, detail="…", quoted_text="some words")  # type: ignore[arg-type]


def test_a_proposed_rewrite_must_carry_a_reason() -> None:
    """Principle III: every recommendation explains itself.

    Without this the diff can show a changed bullet with nothing beside it, and
    the owner is asked to approve a rewrite whose purpose they must reverse-
    engineer from the text.
    """
    with pytest.raises(ValidationError, match="must carry a reason"):
        DraftedItem(
            source_item_id=uuid.uuid4(),
            source_kind="experience_bullet",
            position=0,
            text="Led migration of the billing platform to Kubernetes.",
            reason=None,
        )


def test_an_unchanged_item_needs_no_reason() -> None:
    """Keeping an item as written is not a recommendation."""
    item = DraftedItem(source_item_id=uuid.uuid4(), source_kind="skill", position=3, text=None)
    assert item.reason is None


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ReviewResult(confidence=101)
    assert ReviewResult(confidence=0).findings == []


# -- the root cause of the first real run's failure -------------------------


def test_every_conditional_rule_is_visible_in_what_the_model_is_sent() -> None:
    """The first real tailoring run died here, and this is the gate for it.

    `ReviewFinding` enforces three cross-field rules in a
    `model_validator(mode="after")`. **Pydantic does not serialise those into
    JSON Schema** — and the JSON Schema is the entire contract the gateway sends
    the model. So the model was told `source_item_id` was optional with a
    default of `null`, told separately to "omit anything you cannot find", and
    then rejected in Python for omitting it.

    An invariant enforced in a place the model cannot read is not a contract; it
    is a trap. The validator stays exactly as it is — it is what makes the rule
    true — but the schema now *says* the rule, in the one field of the schema
    that survives serialisation: the description.
    """
    finding = ReviewResult.model_json_schema()["$defs"]["ReviewFinding"]
    described = " ".join(
        prop.get("description", "") for prop in finding["properties"].values()
    ).lower()

    # The rule that actually broke: required for the two item-level kinds.
    assert "ungrounded" in described and "overstated" in described
    assert "required" in described
    # And the opposite rule, which the model was already getting right.
    assert "uncovered" in described and "null" in described


def test_the_review_prompt_states_the_requirement_too() -> None:
    """Belt and braces, and they fail differently.

    The schema is machine-readable and precise; the prompt is where a model
    reading in prose picks the rule up. The first run had the requirement in
    neither — the prompt mentioned quoting the words and never mentioned the id
    at all, which is why omitting it looked correct.
    """
    assert "source_item_id" in _REVIEW
    lowered = _REVIEW.lower()
    assert "ungrounded" in lowered and "overstated" in lowered
    # It must say where the value comes from. "Include an id" without "copy it
    # from the draft above" invites a plausible invention, which validates and
    # then attaches a finding to nothing.
    assert "copy" in lowered or "exactly" in lowered


def test_a_finding_that_obeys_only_the_json_schema_still_fails_closed() -> None:
    """The fix is about compliance, not correctness.

    Even with the description and the prompt, a model may still omit the field.
    When it does, the run must fail rather than persist a finding attached to
    nothing — a finding nobody can attribute is the banner problem FR-042
    exists to prevent. The validator is what guarantees that, so it is asserted
    here rather than assumed.
    """
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(
            {
                "confidence": 78,
                "findings": [{"kind": "overstated", "detail": "Inflated.", "quoted_text": "Owned"}],
            }
        )


def test_the_drafted_item_says_where_its_id_comes_from() -> None:
    """The same defect as `ReviewFinding`'s, one node upstream.

    `DraftedItem.source_item_id` was `UUID | None = None` with no description at
    all, so the JSON Schema advertised it as optional and said nothing about
    where a value would come from. The Draft node is the *origin* of every id in
    the workflow — the Reviewer only copies what the draft carried — so an
    omission here empties the whole chain.
    """
    described = DraftedItem.model_json_schema()["properties"]["source_item_id"].get(
        "description", ""
    )
    assert "REQUIRED" in described
    assert "[id:" in described, "it must say where the value is copied from"
    assert "invent" in described.lower()
