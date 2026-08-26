"""Revise output is a delta over the Draft, never a replacement (T094).

The `_REVISE` prompt's rule 4 says "Return only the items you are changing" —
a delta contract. `state.items` carried no reducer, so LangGraph *overwrote*
the key with the Reviser's partial return, and every Draft decision the
Reviser did not re-emit was silently lost. Measured on the real Zipher run
`6356fb4e`: the final version held 1 proposal and 0 drops with 35/35 items
included, while one of its own reviewer findings praised a drop that existed
nowhere in the persisted version. The Cellebrite run, which needed no
revision, kept all 12 of its drops — the loss is exactly the revision path.

These tests drive the compiled graph with a scripted seam, so they prove the
merge where the defect lived: in what the graph hands back to the use case.
"""

from __future__ import annotations

import uuid
from typing import Any

from careerhq.application.agents.tailoring import build_tailoring_graph
from careerhq.application.agents.tailoring.state import TailoringState, merge_drafted_items
from careerhq.domain.schemas.tailoring import DraftedItem
from tests.support.scripted_seam import ScriptedSeam

BULLET_REWRITTEN = uuid.uuid4()  # the Draft rewrites it; the Reviser revises it again
BULLET_DROPPED = uuid.uuid4()  # the Draft drops it; the Reviser never mentions it
BULLET_UNTOUCHED = uuid.uuid4()  # neither node mentions it


def _master_items() -> list[dict[str, Any]]:
    """The shape `_render_master` returns as its second value."""
    return [
        {
            "source_item_id": BULLET_REWRITTEN,
            "source_kind": "experience_bullet",
            "position": 0,
            "text": "Led the payments platform team for six years.",
        },
        {
            "source_item_id": BULLET_DROPPED,
            "source_kind": "experience_bullet",
            "position": 1,
            "text": "Maintained a legacy SVN mirror nobody used.",
        },
        {
            "source_item_id": BULLET_UNTOUCHED,
            "source_kind": "experience_bullet",
            "position": 2,
            "text": "Contributed to a migration onto containerised infrastructure.",
        },
    ]


def _state() -> TailoringState:
    return TailoringState(
        job={"title": "Senior Backend Engineer", "description": "Payments.", "requirements": []},
        master="(the profile, rendered)",
        master_items=_master_items(),
        match={},
    )


def _plan() -> dict[str, Any]:
    return {
        "emphasise": [
            {"what": "Platform ownership", "serves_requirement": "5+ years backend services"}
        ],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with platform ownership.",
    }


def _rewrite(text: str) -> dict[str, Any]:
    return {
        "source_item_id": str(BULLET_REWRITTEN),
        "source_kind": "experience_bullet",
        "position": 0,
        "included": True,
        "text": text,
        "reason": "Leads with the posting's primary requirement.",
    }


def _drop() -> dict[str, Any]:
    return {
        "source_item_id": str(BULLET_DROPPED),
        "source_kind": "experience_bullet",
        "position": 1,
        "included": False,
    }


def _draft() -> dict[str, Any]:
    return {"items": [_rewrite("Owned the payments platform end to end."), _drop()]}


def _overstated() -> list[dict[str, Any]]:
    return [
        {
            "kind": "overstated",
            "source_item_id": str(BULLET_REWRITTEN),
            "detail": "'Owned' where the profile says 'led'.",
            "quoted_text": "Owned the payments platform end to end.",
        }
    ]


def _review(confidence: int, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"confidence": confidence, "findings": findings or []}


# -- the reducer itself, as a pure function ----------------------------------


def _item(
    item_id: uuid.UUID | None,
    *,
    kind: str = "experience_bullet",
    position: int = 0,
    included: bool = True,
    text: str | None = None,
) -> DraftedItem:
    return DraftedItem.model_validate(
        {
            "source_item_id": str(item_id) if item_id else None,
            "source_kind": kind,
            "position": position,
            "included": included,
            "text": text,
            "reason": "Because the posting asks for it." if text else None,
        }
    )


def test_the_reducer_replaces_by_identity_and_preserves_the_rest() -> None:
    standing = [
        _item(BULLET_REWRITTEN, text="Draft wording."),
        _item(BULLET_DROPPED, position=1, included=False),
    ]
    update = [_item(BULLET_REWRITTEN, text="Revised wording.")]

    merged = merge_drafted_items(standing, update)

    assert len(merged) == 2, f"expected both standing decisions, got {len(merged)}"
    assert merged[0].text == "Revised wording."
    assert merged[1].included is False, "the unmentioned drop must be preserved unchanged"
    assert merged[1] is standing[1]


def test_the_reducer_keys_on_kind_as_well_as_id() -> None:
    """Two items may legally share a null-adjacent shape; identity is the
    pair the UNIQUE partial index enforces, not the id alone."""
    shared = uuid.uuid4()
    standing = [
        _item(shared, kind="experience_bullet", text="A bullet."),
        _item(shared, kind="skill", position=1),
    ]
    update = [_item(shared, kind="skill", position=0, included=False)]

    merged = merge_drafted_items(standing, update)

    assert len(merged) == 2
    assert merged[0].text == "A bullet.", "the bullet with the same id is not the same item"
    assert merged[1].included is False


def test_the_reducer_appends_an_update_that_matches_nothing_standing() -> None:
    standing = [_item(BULLET_REWRITTEN, text="Draft wording.")]
    update = [_item(BULLET_UNTOUCHED, position=2, text="A new proposal.")]

    merged = merge_drafted_items(standing, update)

    assert [i.source_item_id for i in merged] == [BULLET_REWRITTEN, BULLET_UNTOUCHED]


def test_the_reducer_passes_the_first_write_through_intact() -> None:
    """The Draft node's write merges into the empty initial list, so the
    reducer must hand the draft back — a reducer that broke the first write
    would fail every run, not only revised ones."""
    draft = [
        _item(BULLET_REWRITTEN, text="Draft wording."),
        _item(BULLET_DROPPED, position=1, included=False),
    ]

    merged = merge_drafted_items([], draft)

    assert merged == draft
    assert len(merged) == 2


def test_the_reducer_emits_no_duplicate_identities() -> None:
    """The persistence layer writes one row per (version, kind, source id)
    under a UNIQUE partial index; a duplicate here becomes an IntegrityError
    there. Last wins within one update, matching dict semantics."""
    standing = [_item(BULLET_REWRITTEN, text="Draft wording.")]
    update = [
        _item(BULLET_REWRITTEN, text="First revision."),
        _item(BULLET_REWRITTEN, text="Second thought."),
    ]

    merged = merge_drafted_items(standing, update)

    identities = [(i.source_kind, i.source_item_id) for i in merged]
    assert len(identities) == len(set(identities)) == 1
    assert merged[0].text == "Second thought."


def test_the_reducer_passes_unaddressable_items_through() -> None:
    """An item with no source id maps to nothing; the use case counts and
    discards it. The reducer neither invents an identity for it nor eats it."""
    standing = [_item(None, text="Standing, unaddressable.")]
    update = [_item(None, text="Updated, unaddressable.")]

    merged = merge_drafted_items(standing, update)

    assert len(merged) == 2, "neither side's unaddressable items may be silently dropped"
    assert {i.text for i in merged} == {"Standing, unaddressable.", "Updated, unaddressable."}


# -- the graph, end to end through the scripted seam --------------------------


async def test_a_draft_drop_survives_a_revise_that_does_not_mention_it() -> None:
    """The confirmed Zipher-style failure, reproduced.

    The Reviser returns only the item it is changing — exactly what its
    prompt instructs — and the Draft's drop must still be in the result.
    """
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft()],
            "tailor_review": [_review(40, _overstated()), _review(88)],
            "tailor_revise": [{"items": [_rewrite("Led the payments platform for six years.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    items = result["items"]
    assert len(items) == 2, (
        f"the Draft decided two items and the Reviser changed one; the merge must "
        f"hold both, got {len(items)} — the drop vanished if this is 1"
    )
    by_id = {item.source_item_id: item for item in items}
    assert set(by_id) == {BULLET_REWRITTEN, BULLET_DROPPED}
    assert by_id[BULLET_DROPPED].included is False, (
        "the Draft dropped this item and the Reviser never mentioned it; "
        "losing the drop silently reinstates the item"
    )
    assert by_id[BULLET_REWRITTEN].text == "Led the payments platform for six years."


async def test_a_revised_item_replaces_its_draft_counterpart_without_duplicating_it() -> None:
    """One identity, one item: the revised text wins and the draft's loses."""
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft()],
            "tailor_review": [_review(40, _overstated()), _review(88)],
            "tailor_revise": [{"items": [_rewrite("Led the payments platform for six years.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    matching = [i for i in result["items"] if i.source_item_id == BULLET_REWRITTEN]
    assert len(matching) == 1, "a revision replaces its draft counterpart, never sits beside it"
    assert matching[0].text == "Led the payments platform for six years."
    assert "Owned the payments platform end to end." not in {i.text for i in result["items"]}


async def test_two_revisions_merge_twice_and_the_drop_still_survives() -> None:
    """The full budget: draft, two revisions, three reviews — one item set."""
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft()],
            "tailor_review": [
                _review(30, _overstated()),
                _review(45, _overstated()),
                _review(50, _overstated()),
            ],
            "tailor_revise": [{"items": [_rewrite("Second attempt.")]}],
            "tailor_revise_escalated": [{"items": [_rewrite("Third attempt.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    items = result["items"]
    assert len(items) == 2, (
        f"two merges must still yield the Draft's two decisions, got {len(items)}"
    )
    by_id = {item.source_item_id: item for item in items}
    assert by_id[BULLET_DROPPED].included is False, "the drop must survive both merges"
    assert by_id[BULLET_REWRITTEN].text == "Third attempt.", "the latest revision wins"


async def test_a_reviser_may_propose_against_a_line_the_draft_never_touched() -> None:
    """`_REVISE` rule 5 allows an id taken from the profile itself, so a
    revision item that matches nothing in the draft is an addition, not noise."""
    new_proposal = {
        "source_item_id": str(BULLET_UNTOUCHED),
        "source_kind": "experience_bullet",
        "position": 2,
        "included": True,
        "text": "Migrated payment services onto containerised infrastructure.",
        "reason": "Answers the container requirement the reviewer flagged as uncovered.",
    }
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft()],
            "tailor_review": [
                _review(
                    40,
                    [
                        {
                            "kind": "uncovered",
                            "source_item_id": None,
                            "detail": "Container experience is never addressed.",
                        }
                    ],
                ),
                _review(88),
            ],
            "tailor_revise": [{"items": [new_proposal]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    items = result["items"]
    assert len(items) == 3, f"two draft decisions plus one new proposal, got {len(items)}"
    by_id = {item.source_item_id: item for item in items}
    assert set(by_id) == {BULLET_REWRITTEN, BULLET_DROPPED, BULLET_UNTOUCHED}
    assert by_id[BULLET_DROPPED].included is False
    assert by_id[BULLET_UNTOUCHED].text == new_proposal["text"]


async def test_a_first_pass_clear_leaves_the_draft_untouched() -> None:
    """No revision, no merge: the Draft's items come back exactly as returned."""
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft()],
            "tailor_review": [_review(90)],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    assert seam.tasks_called == ["tailor_plan", "tailor_draft", "tailor_review"]
    items = result["items"]
    assert len(items) == 2
    by_id = {item.source_item_id: item for item in items}
    assert by_id[BULLET_REWRITTEN].text == "Owned the payments platform end to end."
    assert by_id[BULLET_DROPPED].included is False
