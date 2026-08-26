"""Position-only proposals, and the four states that need telling apart (T095).

`text=None` is deliberately overloaded — `finalisation_rules.finalise`'s own
docstring calls it "one representation of 'no change', not two" — and
persistence overwrote the master position with the proposed one, keeping no
record that it had. So a Draft that *reordered* an item looked exactly like a
Draft that never touched it.

The real case this is measured against: Voyantis run `ff0e310c` moved all nine
experience bullets and ten of eleven skills while carrying only three text
proposals. `d61a73e8` — a planned emphasis the Draft demonstrably moved from
master position 2 to 7 — classified as `no_evidence`.

`displaced_position` records the master position a proposal displaced, and NULL
means no proposal arrived. The master's ordering at creation is therefore
`COALESCE(displaced_position, position)` for every item, which is what closes
the FR-030 gap: today an item carrying a proposal has lost it.

**Historical rows keep NULL and are never read as "no proposal arrived".** They
predate the column, so proposal arrival cannot be reconstructed, and asserting
absence from silence is the error this project keeps naming.
"""

from __future__ import annotations

from careerhq.application.plan_adherence import FindingFacts, ItemFacts, plan_execution


def _plan(*ids: str) -> dict[str, object]:
    return {"emphasise": [{"source_item_id": i, "what": f"emphasise {i}"} for i in ids]}


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


def _run(
    plan: dict[str, object],
    items: list[ItemFacts],
    findings: list[FindingFacts] | None = None,
    *,
    position_evidence: bool = True,
) -> dict[str, object]:
    return plan_execution(
        plan,
        items=items,
        findings=findings or [],
        contaminated=False,
        position_evidence=position_evidence,
    )


# --- the four no-text states ----------------------------------------------


def test_the_voyantis_case_is_reordered_not_no_evidence() -> None:
    """**The regression.** `d61a73e8` carried no text proposal and moved from
    master position 2 to 7. Before this task it read as `no_evidence` — the
    Draft credited with ignoring an emphasis it had executed by reordering."""
    result = _run(
        _plan("d61a73e8"),
        [_item("d61a73e8", position=7, displaced=2)],
    )
    assert result["distinct"] == 1
    assert result["states"] == {"reordered": 1}
    assert result["per_item"]["d61a73e8"] == "reordered"


def test_a_proposal_that_did_not_move_the_item_is_proposed_not_reordered() -> None:
    """A proposal arrived and left the order alone. That is an action, and it is
    not a reorder; conflating them would report movement that never happened."""
    result = _run(_plan("aaaa1111"), [_item("aaaa1111", position=3, displaced=3)])
    assert result["states"] == {"proposed": 1}


def test_no_proposal_on_a_measurable_row_is_no_evidence() -> None:
    """NULL on a row written after the column existed means what it says."""
    result = _run(_plan("bbbb2222"), [_item("bbbb2222", position=3, displaced=None)])
    assert result["states"] == {"no_evidence": 1}


def test_a_historical_row_is_unknown_position_never_no_evidence() -> None:
    """The same NULL on a row that predates the column proves nothing. Reading
    it as "no proposal arrived" would assert absence from silence."""
    result = _run(
        _plan("cccc3333"),
        [_item("cccc3333", position=3, displaced=None)],
        position_evidence=False,
    )
    assert result["states"] == {"unknown_position": 1}
    assert result["states"].get("no_evidence", 0) == 0


# --- D1 ---------------------------------------------------------------------


def test_d1_counts_both_proposed_and_reordered_as_acted() -> None:
    """Both are the Draft acting on the plan; only the effect differs."""
    result = _run(
        _plan("aaaa1111", "bbbb2222", "cccc3333"),
        [
            _item("aaaa1111", position=7, displaced=2),  # reordered
            _item("bbbb2222", position=3, displaced=3),  # proposed
            _item("cccc3333", position=4, displaced=None),  # untouched
        ],
    )
    assert result["states"] == {"reordered": 1, "proposed": 1, "no_evidence": 1}
    assert result["d1_draft_compliance"]["acted"] == 2
    assert result["d1_draft_compliance"]["determinable"] == 3
    assert result["d1_draft_compliance"]["ratio"] == 0.667


def test_unknown_position_leaves_the_d1_denominator_and_is_reported_separately() -> None:
    """A row whose evidence was never recorded is not a failure and must not sit
    in the denominator. The ratio is withheld for the reason a contaminated run
    withholds one: a numerator over a shrunken denominator cannot be compared."""
    result = _run(
        _plan("aaaa1111", "bbbb2222", "cccc3333", "dddd4444"),
        [
            _item("aaaa1111", position=7, displaced=2),
            _item("bbbb2222", position=1, displaced=None),
            _item("cccc3333", position=2, displaced=None),
            _item("dddd4444", position=3, displaced=None),
        ],
        position_evidence=False,
    )
    assert result["states"] == {"reordered": 1, "unknown_position": 3}
    assert result["d1_draft_compliance"]["acted"] == 1
    assert result["d1_draft_compliance"]["determinable"] == 1, (
        "three unknowns leave the denominator"
    )
    assert result["d1_draft_compliance"]["unknown_position"] == 3, "and are reported separately"
    assert result["d1_draft_compliance"]["ratio"] is None


# --- D3 is untouched --------------------------------------------------------


def test_d3_is_unaffected_by_position_evidence() -> None:
    """Whether text survived is knowable regardless of what is known about
    ordering, so no recorded D3 figure may move because of this task. A reorder
    is an action, never a surviving text change."""
    items = [
        _item("aaaa1111", original="a", proposed="a rewritten", position=0, displaced=0),
        _item("bbbb2222", position=7, displaced=2),
        _item("cccc3333", "skill", original="C++", position=1, displaced=None),
    ]
    plan = _plan("aaaa1111", "bbbb2222", "cccc3333")

    measurable = _run(plan, items)
    historical = _run(plan, items, position_evidence=False)

    assert measurable["d3_plan_effect"] == historical["d3_plan_effect"], (
        "position evidence must not move D3"
    )
    assert measurable["d3_plan_effect"]["survived"] == 1
    assert measurable["d3_plan_effect"]["addressable"] == 2, "three distinct minus one skill label"
    assert measurable["d3_plan_effect"]["ratio"] == 0.5


def test_a_label_kind_target_stays_label_kind_on_a_historical_row() -> None:
    """`label_kind` is a property of the target, not of the evidence — otherwise
    a historical skill emphasis would leave D3's denominator and silently change
    every D3 figure already recorded."""
    result = _run(
        _plan("cccc3333"),
        [_item("cccc3333", "skill", original="C++", position=1, displaced=None)],
        position_evidence=False,
    )
    assert result["states"] == {"label_kind": 1}


def test_a_reorder_does_not_count_as_survived() -> None:
    result = _run(_plan("aaaa1111"), [_item("aaaa1111", position=7, displaced=2)])
    assert result["d3_plan_effect"]["survived"] == 0
    assert result["d1_draft_compliance"]["acted"] == 1


# --- text evidence still wins ----------------------------------------------


def test_text_evidence_outranks_position_evidence() -> None:
    """A rewrite that also moved is `survived`, not `reordered`: the strongest
    evidence classifies the item, and the four historical runs' text-based
    states must not shift."""
    result = _run(
        _plan("aaaa1111"),
        [_item("aaaa1111", original="a", proposed="a rewritten", position=7, displaced=2)],
    )
    assert result["states"] == {"survived": 1}


def test_a_discarded_proposal_stays_discarded_even_though_it_moved() -> None:
    """`finalise` nulls the text of an ungrounded proposal but leaves its
    position, so the position evidence must not reclassify a fabrication."""
    result = _run(
        _plan("aaaa1111"),
        [_item("aaaa1111", original="a", proposed=None, position=7, displaced=2)],
        [FindingFacts("aaaa1111", "ungrounded", "invented words")],
    )
    assert result["states"] == {"discarded": 1}
