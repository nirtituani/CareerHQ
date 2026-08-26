"""How much of the plan the draft actually carried out.

Two real runs on the same profile behaved very differently: Cellebrite planned
eight emphases and rewrote four; Zipher planned six and rewrote one. Same code,
same prompts, different jobs. Whether that is a defect, prompt weakness or
ordinary run-to-run variance **cannot be decided from two samples**, so nothing
here is a threshold and nothing gates on it.

What it does is make the number fall out of every future run instead of being
re-derived by hand, so that by the time slice 007 can judge it there is a
distribution to judge.

**De-emphasis is deliberately not measured.** `TailoringPlan.de_emphasise` is a
list of free text — "C++ as a current primary skill" — with no item ids, so
"did the draft drop what the plan said to drop" is not computable. Making it so
means changing the Plan schema and therefore the Plan prompt, which is exactly
what there is not yet evidence to justify. It is the larger blind spot of the
two: Zipher executed zero of nine.
"""

from __future__ import annotations

import uuid

from careerhq.application.plan_adherence import emphasis_adherence

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _plan(*ids: uuid.UUID | None) -> dict[str, object]:
    return {
        "emphasise": [
            {
                "what": "something",
                "serves_requirement": "a requirement",
                **({"source_item_id": str(i)} if i else {}),
            }
            for i in ids
        ]
    }


def test_it_counts_the_emphases_the_draft_rewrote() -> None:
    result = emphasis_adherence(_plan(A, B, C), rewritten_ids=[str(A), str(C)])

    assert result["planned"] == 3
    assert result["with_ids"] == 3
    assert result["executed"] == 2
    assert result["adherence"] == round(2 / 3, 3)
    assert result["unexecuted_ids"] == [str(B)]


def test_a_plan_nothing_acted_on_scores_zero_rather_than_erroring() -> None:
    result = emphasis_adherence(_plan(A, B), rewritten_ids=[])

    assert result["executed"] == 0
    assert result["adherence"] == 0.0
    assert sorted(result["unexecuted_ids"]) == sorted([str(A), str(B)])


def test_emphases_without_an_id_are_counted_but_not_scored() -> None:
    """`source_item_id` is optional on an `EmphasisDirective` — a plan may
    emphasise something that points at no single fact. Those cannot be matched
    against a rewrite, so they are reported and excluded from the ratio rather
    than silently counted as failures."""
    result = emphasis_adherence(_plan(A, None, None), rewritten_ids=[str(A)])

    assert result["planned"] == 3
    assert result["with_ids"] == 1
    assert result["executed"] == 1
    assert result["adherence"] == 1.0


def test_an_empty_plan_reports_nothing_rather_than_dividing_by_zero() -> None:
    result = emphasis_adherence({"emphasise": []}, rewritten_ids=[])

    assert result["planned"] == 0
    assert result["adherence"] is None


def test_a_missing_or_null_plan_is_handled() -> None:
    """A failed run has no plan. The audit endpoint still has to answer."""
    for plan in (None, {}, {"emphasise": None}):
        result = emphasis_adherence(plan, rewritten_ids=[])
        assert result["planned"] == 0
        assert result["adherence"] is None


def test_a_rewrite_the_plan_never_asked_for_does_not_inflate_the_score() -> None:
    """The draft may rewrite something the plan did not name. That is not
    adherence, and counting it would let a run score well by ignoring the plan
    entirely."""
    result = emphasis_adherence(_plan(A), rewritten_ids=[str(A), str(B), str(C)])

    assert result["executed"] == 1
    assert result["adherence"] == 1.0
