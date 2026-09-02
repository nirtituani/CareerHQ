"""The action-aware measure, drilled against every state it can report.

`action_execution` grades the `action` contract: a directive states
`keep`/`reframe`/`rewrite` and compliance means doing what was stated —
including doing *nothing* to a `keep`. The old measures (D0/D1/D3) grade a
different promise and are asserted untouched by `test_plan_execution.py`;
nothing here reuses their fixtures, because the two contracts must not share
one series.

The headline rule, learned from the Silverfort run: **`keep` is explicit
compliance, not absence.** Under D1 that run scored 0.125 for leaving
already-serving lines alone; under this measure the same behaviour scores as
what it was — the plan saying "leave it" and the draft obeying.
"""

from __future__ import annotations

from typing import Any

from careerhq.application.plan_adherence import (
    FindingFacts,
    ItemFacts,
    action_execution,
)


def _directive(item_id: str | None, action: str) -> dict[str, Any]:
    return {"source_item_id": item_id, "action": action, "what": f"emphasise {item_id}"}


def _plan(*directives: dict[str, Any]) -> dict[str, Any]:
    return {"emphasise": list(directives)}


def _item(
    item_id: str,
    kind: str = "experience_bullet",
    *,
    original: str = "original wording",
    proposed: str | None = None,
    final: str | None = None,
    position: int = 0,
    displaced: int | None = None,
) -> ItemFacts:
    return ItemFacts(
        source_item_id=item_id,
        source_kind=kind,
        original_text=original,
        proposed_text=proposed,
        final_text=final if final is not None else (proposed or original),
        position=position,
        displaced_position=displaced,
    )


def _measure(plan: dict[str, Any], items: list[ItemFacts], **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("findings", [])
    kwargs.setdefault("position_evidence", True)
    return action_execution(plan, items=items, **kwargs)


# --- keep: explicit compliance -------------------------------------------


def test_a_keep_left_alone_is_compliance_not_absence() -> None:
    """The Silverfort behaviour, scored as what it was."""
    result = _measure(_plan(_directive("a1", "keep")), [_item("a1")])
    assert result["has_actions"] is True
    assert result["keep_compliance"] == {"compliant": 1, "keep": 1, "violations": 0, "ratio": 1.0}
    assert result["per_item"]["a1"] == {"action": "keep", "state": "no_evidence"}


def test_a_keep_that_was_reordered_is_still_compliance() -> None:
    """`keep` forbids rewording, not moving — position changes stay legal."""
    result = _measure(_plan(_directive("a1", "keep")), [_item("a1", position=5, displaced=0)])
    assert result["keep_compliance"]["compliant"] == 1
    assert result["keep_compliance"]["violations"] == 0


def test_a_keep_that_was_rewritten_is_a_violation() -> None:
    result = _measure(
        _plan(_directive("a1", "keep")),
        [_item("a1", original="orig", proposed="reworded", displaced=0)],
    )
    assert result["keep_compliance"] == {"compliant": 0, "keep": 1, "violations": 1, "ratio": 0.0}


def test_a_keep_whose_proposal_was_reverted_is_still_a_violation() -> None:
    """The draft acted where it was told not to; a later step correcting it
    does not un-act it. `reverted` needs a finding quoting words neither text
    contains — that is what proves a rewrite happened."""
    result = _measure(
        _plan(_directive("a1", "keep")),
        [_item("a1", original="orig", proposed="orig", final="orig", displaced=0)],
        findings=[FindingFacts("a1", "overstated", "words the draft wrote")],
    )
    assert result["per_item"]["a1"]["state"] == "reverted"
    assert result["keep_compliance"]["violations"] == 1


def test_a_keep_with_no_id_is_counted_but_not_scored() -> None:
    """Unmatchable against any row, so presuming it compliant would flatter."""
    result = _measure(_plan(_directive(None, "keep"), _directive("a1", "keep")), [_item("a1")])
    assert result["keep_without_id"] == 1
    assert result["actions"]["keep"] == 2
    # Only the matchable one is in the ratio.
    assert result["keep_compliance"]["keep"] == 1


# --- reframe / rewrite: a proposal is mandatory --------------------------


def test_a_reframe_with_a_surviving_proposal_is_executed() -> None:
    result = _measure(
        _plan(_directive("a1", "reframe")),
        [_item("a1", original="orig", proposed="framed toward the requirement", displaced=0)],
    )
    assert result["actionable_execution"] == {
        "executed": 1,
        "actionable": 1,
        "invalid_target": 0,
        "ratio": 1.0,
    }


def test_a_reframe_answered_only_by_a_reorder_is_not_executed() -> None:
    """The directive asked for wording; a move is not wording."""
    result = _measure(_plan(_directive("a1", "reframe")), [_item("a1", position=3, displaced=0)])
    assert result["per_item"]["a1"]["state"] == "reordered"
    assert result["actionable_execution"]["executed"] == 0
    assert result["actionable_execution"]["ratio"] == 0.0


def test_a_rewrite_with_no_proposal_is_not_executed() -> None:
    result = _measure(_plan(_directive("a1", "rewrite")), [_item("a1")])
    assert result["actionable_execution"] == {
        "executed": 0,
        "actionable": 1,
        "invalid_target": 0,
        "ratio": 0.0,
    }


def test_a_discarded_reframe_still_counts_as_the_draft_acting() -> None:
    """An ungrounded proposal was made and stopped — compliance with the
    directive, failure of grounding. The grounding failure is the Reviewer's
    record; this measure answers only "did the draft act"."""
    result = _measure(
        _plan(_directive("a1", "reframe")),
        [_item("a1", original="orig", proposed=None, final="orig", displaced=0)],
        findings=[FindingFacts("a1", "ungrounded", "invented words")],
    )
    assert result["per_item"]["a1"]["state"] == "discarded"
    assert result["actionable_execution"]["executed"] == 1


def test_a_reframe_aimed_at_a_label_is_the_plans_violation_not_the_drafts() -> None:
    """A skill has no wording to change, so the directive was invalid at birth.

    It leaves the actionable denominator — otherwise a plan could damage the
    draft's execution ratio by writing directives nobody can execute."""
    result = _measure(
        _plan(_directive("s1", "reframe"), _directive("a1", "rewrite")),
        [
            _item("s1", "skill", original="C++"),
            _item("a1", original="orig", proposed="rewritten", displaced=0),
        ],
    )
    assert result["actionable_execution"] == {
        "executed": 1,
        "actionable": 1,
        "invalid_target": 1,
        "ratio": 1.0,
    }


# --- legacy and malformed plans ------------------------------------------


def test_a_legacy_plan_reports_no_actions_and_no_ratios() -> None:
    """An old run cannot be scored against a promise it never made."""
    legacy = {"emphasise": [{"source_item_id": "a1", "what": "emphasise a1"}]}
    result = action_execution(legacy, items=[_item("a1")], findings=[])
    assert result == {"has_actions": False, "malformed_actions": 0}


def test_an_empty_plan_reports_no_actions() -> None:
    assert action_execution(None, items=[], findings=[]) == {
        "has_actions": False,
        "malformed_actions": 0,
    }


def test_a_mixed_plan_is_malformed_not_scored() -> None:
    """No valid completion can produce this shape; its presence is a bug's
    trace, and counting the well-formed half would hide it."""
    mixed = _plan(
        _directive("a1", "keep"),
        {"source_item_id": "a2", "what": "no action"},
    )
    result = action_execution(mixed, items=[_item("a1"), _item("a2")], findings=[])
    assert result["has_actions"] is False
    assert result["malformed_actions"] == 1


# --- refusal and dedup ----------------------------------------------------


def test_a_contaminated_run_reports_counts_but_refuses_ratios() -> None:
    """Pre-T094 the revision could erase the draft's decisions; what is
    unknowable is named rather than scored, same refusal as D1's."""
    result = _measure(
        _plan(_directive("a1", "keep"), _directive("a2", "reframe")),
        [_item("a1"), _item("a2")],
        contaminated=True,
        position_evidence=False,
    )
    assert result["has_actions"] is True
    assert result["unknowable"] == 2
    assert result["keep_compliance"]["ratio"] is None
    assert result["actionable_execution"]["ratio"] is None


def test_a_duplicated_id_is_one_directive() -> None:
    """A plan naming one line twice asked for one change (Cellebrite)."""
    result = _measure(
        _plan(_directive("a1", "reframe"), _directive("a1", "reframe")),
        [_item("a1", original="orig", proposed="rewritten", displaced=0)],
    )
    assert result["duplicates_collapsed"] == 1
    assert result["actionable_execution"]["actionable"] == 1


def test_the_measure_examined_every_directive_it_was_given() -> None:
    """A gate with nothing to examine passes forever — assert the count."""
    result = _measure(
        _plan(
            _directive("a1", "keep"),
            _directive("a2", "reframe"),
            _directive("a3", "rewrite"),
        ),
        [
            _item("a1"),
            _item("a2", original="orig", proposed="framed", displaced=0),
            _item("a3"),
        ],
    )
    assert sum(result["actions"].values()) == 3
    assert len(result["per_item"]) == 3
