"""The severity split, tested as pure functions.

No database, no provider, no graph. This is the module where Principle III is
enforced, so its rules must be checkable in isolation — if proving "an
unsupported claim never reaches a row" needed a running stack, it would be
proved rarely.
"""

from __future__ import annotations

import uuid

from careerhq.application.finalisation_rules import (
    CONFIDENCE_THRESHOLD,
    FINALISATION_RULES_VERSION,
    MAX_REVISIONS,
    clears_review,
    finalise,
    should_revise,
    task_for_revision,
)
from careerhq.domain.schemas.tailoring import DraftedItem, ReviewFinding


def _item(item_id: uuid.UUID, text: str | None = "Rewritten bullet.") -> DraftedItem:
    return DraftedItem(
        source_item_id=item_id,
        source_kind="experience_bullet",
        position=0,
        text=text,
        reason="Leads with the posting's primary requirement." if text else None,
    )


def test_an_ungrounded_finding_removes_its_proposal() -> None:
    """FR-018. The claim must not survive into anything persistable."""
    doomed, kept = uuid.uuid4(), uuid.uuid4()
    result = finalise(
        items=[_item(doomed), _item(kept)],
        findings=[
            ReviewFinding(
                kind="ungrounded",
                source_item_id=doomed,
                detail="Claims Kubernetes ownership the profile does not contain.",
                quoted_text="owned the Kubernetes platform",
            )
        ],
    )

    reverted = next(i for i in result.items if i.source_item_id == doomed)
    survivor = next(i for i in result.items if i.source_item_id == kept)

    assert reverted.text is None, "an ungrounded proposal must not survive finalisation"
    assert reverted.reason is None, "its justification must not survive either"
    assert survivor.text == "Rewritten bullet."
    assert result.discarded_item_ids == {str(doomed)}


def test_the_finding_survives_even_though_the_proposal_does_not() -> None:
    """The record of what the Reviewer caught is the evidence it ran.

    Discarding the finding along with the claim would leave a run that looks
    like it had nothing to object to, which is indistinguishable from a run
    where the guardrail never executed.
    """
    doomed = uuid.uuid4()
    result = finalise(
        items=[_item(doomed)],
        findings=[
            ReviewFinding(
                kind="ungrounded",
                source_item_id=doomed,
                detail="Unsupported.",
                quoted_text="owned the Kubernetes platform",
            )
        ],
    )

    assert len(result.findings) == 1
    assert result.findings[0].kind == "ungrounded"


def test_overstated_and_uncovered_survive_untouched() -> None:
    """FR-019. Matters of degree are the owner's judgement, not ours."""
    item_id = uuid.uuid4()
    result = finalise(
        items=[_item(item_id)],
        findings=[
            ReviewFinding(
                kind="overstated",
                source_item_id=item_id,
                detail="'Led' where the profile says 'contributed to'.",
                quoted_text="Led the migration",
            ),
            ReviewFinding(kind="uncovered", detail="Terraform is never addressed."),
        ],
    )

    assert result.items[0].text == "Rewritten bullet.", (
        "an overstatement is shown to the owner, not silently removed"
    )
    assert result.discarded_item_ids == frozenset()
    assert len(result.findings) == 2


def test_an_ungrounded_finding_fails_the_draft_whatever_the_confidence() -> None:
    """A model that fabricates *and* reports high confidence is the case the
    threshold cannot be trusted to catch — and the one Principle III makes a
    release blocker."""
    fabrication = ReviewFinding(
        kind="ungrounded",
        source_item_id=uuid.uuid4(),
        detail="Unsupported.",
        quoted_text="ten years of Rust",
    )

    assert clears_review(100, [fabrication]) is False
    assert should_revise(confidence=100, findings=[fabrication], attempt=0) is True


def test_confidence_alone_decides_when_nothing_is_ungrounded() -> None:
    assert clears_review(CONFIDENCE_THRESHOLD, []) is True
    assert clears_review(CONFIDENCE_THRESHOLD - 1, []) is False


def test_the_threshold_is_65_calibrated_by_e1() -> None:
    """The absolute boundary, pinned on purpose — the relative test above would
    pass at any value, and the value is the calibrated decision.

    E1 (2026-09-01) measured the 65-69 band: in both direct observations, the
    revision only de-overstated one or two lines the owner sees flagged either
    way, with no judged quality difference — while low-60s revisions fixed 2-3
    overstatements per run. 65 harvests the former and keeps the latter.
    """
    assert CONFIDENCE_THRESHOLD == 65
    # 64 -> revise; 65 and 69 -> clear, when nothing is ungrounded.
    assert should_revise(confidence=64, findings=[], attempt=0) is True
    assert should_revise(confidence=65, findings=[], attempt=0) is False
    assert should_revise(confidence=69, findings=[], attempt=0) is False


def test_an_ungrounded_finding_blocks_inside_the_cleared_band_too() -> None:
    """The calibration must not touch grounding: a fabrication at 65-69 — the
    band the new threshold clears on confidence — still fails the draft."""
    fabrication = ReviewFinding(
        kind="ungrounded",
        source_item_id=uuid.uuid4(),
        detail="Unsupported.",
        quoted_text="ten years of Rust",
    )
    for confidence in (65, 69):
        assert clears_review(confidence, [fabrication]) is False
        assert should_revise(confidence=confidence, findings=[fabrication], attempt=0) is True


def test_the_revision_budget_is_not_extendable() -> None:
    """FR-013. Exhausting the budget is a normal exit, not an error."""
    assert should_revise(confidence=0, findings=[], attempt=MAX_REVISIONS) is False
    assert should_revise(confidence=0, findings=[], attempt=MAX_REVISIONS - 1) is True


def test_the_second_revision_escalates_by_task_name() -> None:
    """The escalation is configuration, not a branch on a model.

    `ports.py` resolves the model from the task name, which is what keeps
    docs/08 §3.2.3 out of workflow code.
    """
    assert task_for_revision(0) == "tailor_revise"
    assert task_for_revision(1) == "tailor_revise_escalated"


def test_the_rules_are_versioned() -> None:
    """A run finalised under unnamed rules cannot be compared with any other.

    Slice 007 measures this capability by comparing runs over time; that
    comparison is meaningless if a threshold changed without the version moving.
    """
    assert FINALISATION_RULES_VERSION
    # v3: CONFIDENCE_THRESHOLD calibrated 70 -> 65 by experiment E1. The v2
    # change (discard judged on the final pass only) is carried forward
    # unchanged. FR-020: changing a constant is a new name, never an edit.
    assert FINALISATION_RULES_VERSION == "v3-final-pass-t65"


def test_an_item_with_no_source_id_is_never_discarded() -> None:
    """A finding names an item by id. An item with no id cannot be the one it
    meant, and guessing would discard someone's summary on a coincidence."""
    orphan = DraftedItem(
        source_kind="summary", position=0, text="Rewritten.", reason="Leads with the domain."
    )
    result = finalise(
        items=[orphan],
        findings=[
            ReviewFinding(
                kind="ungrounded",
                source_item_id=uuid.uuid4(),
                detail="Unsupported.",
                quoted_text="something else entirely",
            )
        ],
    )

    assert result.items[0].text == "Rewritten."
