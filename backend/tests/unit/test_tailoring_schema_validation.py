"""The schema rules that carry Principle III, tested without a provider.

Each of these encodes something slice 004 learned by shipping the opposite.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

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
