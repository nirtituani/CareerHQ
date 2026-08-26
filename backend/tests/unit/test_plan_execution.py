"""Plan execution as a state vector, against the three real historical runs.

The old figure — `emphasis_adherence`, D0 — counts a planned emphasis as
executed when the version holds a proposal row for it. Four defects follow from
that definition, and all four are reproduced below from real persisted data:

* a proposal **reverted** to the owner's wording still has a non-null
  `proposed_text`, so it counts as executed while changing nothing (Harman);
* a plan naming the same id twice is counted twice (Cellebrite);
* an emphasis on a **label-kind** item — the skill line "C++" — has no prose to
  rewrite, and scores zero against a denominator that includes it;
* a run whose revision **erased** the draft's decisions has outcomes that are
  unknowable, not failed (Zipher, pre-T094).

The fixtures below carry the real `source_item_id` prefixes and the real
equality relationships between original, proposed and final text. Text is
abbreviated: nothing here depends on its content, only on which strings match.

Measured from the database on 2026-08-26; the run ids are in each fixture's
docstring so any figure can be traced back.
"""

from __future__ import annotations

from careerhq.application.plan_adherence import (
    FindingFacts,
    ItemFacts,
    emphasis_adherence,
    plan_execution,
)

# --- the three runs, transcribed from persisted rows -----------------------


def _plan(*ids: str) -> dict[str, object]:
    """A plan carrying one emphasis per id, in order, duplicates preserved."""
    return {"emphasise": [{"source_item_id": i, "what": f"emphasise {i}"} for i in ids]}


def _item(
    item_id: str,
    kind: str = "experience_bullet",
    *,
    original: str = "original wording",
    proposed: str | None = None,
    final: str | None = None,
) -> ItemFacts:
    return ItemFacts(
        source_item_id=item_id,
        source_kind=kind,
        original_text=original,
        proposed_text=proposed,
        final_text=final if final is not None else (proposed or original),
    )


def cellebrite() -> tuple[dict[str, object], list[ItemFacts], list[FindingFacts], bool]:
    """Run `2615363e`, version `a8f1e4b7`. Eight emphases, `cd5f3821` named twice.

    Three items were rewritten and survived; two of those carry `overstated`
    findings that were never corrected, because the run cleared review on the
    first pass and `attempts = 0`.
    """
    plan = _plan(
        "5813b809",
        "8c715699",
        "cd5f3821",
        "cd5f3821",  # the duplicate
        "48100a48",
        "13fc719c",
        "d61a73e8",
        "b3b96ffa",
    )
    items = [
        _item("5813b809"),
        _item("8c715699", "summary", original="summary orig", proposed="summary rewritten"),
        _item("cd5f3821", original="RAG orig", proposed="RAG pipelines rewritten"),
        _item("48100a48", original="AWS orig", proposed="AWS enterprise-scale rewritten"),
        _item("13fc719c", "skill", original="C++"),
        _item("d61a73e8"),
        _item("b3b96ffa"),
    ]
    findings = [
        FindingFacts("cd5f3821", "overstated", "exploring RAG pipelines"),
        FindingFacts("48100a48", "overstated", "for enterprise-scale backend systems"),
    ]
    return plan, items, findings, False


def harman() -> tuple[dict[str, object], list[ItemFacts], list[FindingFacts], bool]:
    """Run `60263226`, version `d3700cb8`. Seven emphases, post-T094.

    Two proposals were reverted to the owner's wording after `overstated`
    findings, one was discarded after an `ungrounded` finding, and two emphases
    name bare skill lines.
    """
    plan = _plan(
        "9902aeb2",
        "93c80b50",
        "d61a73e8",
        "13fc719c",
        "b3b96ffa",
        "9c20b0f0",
        "a3c2ae0f",
    )
    items = [
        # Reverted: the proposal now equals the original, and the finding below
        # quotes wording that is in neither.
        _item("9902aeb2", original="copilot orig", proposed="copilot orig"),
        _item("93c80b50", original="messaging orig", proposed="messaging orig"),
        _item("d61a73e8"),
        _item("13fc719c", "skill", original="C++"),
        _item("b3b96ffa"),
        # Discarded: the ungrounded proposal was removed and the original stands.
        _item("9c20b0f0", original="ai tools orig", proposed=None),
        _item("a3c2ae0f", "skill", original="Git"),
    ]
    findings = [
        FindingFacts("9902aeb2", "overstated", "throughout the development lifecycle"),
        FindingFacts("93c80b50", "overstated", "concurrency handling for asynchronous workloads"),
        FindingFacts("9c20b0f0", "ungrounded", "complex, unfamiliar enterprise codebases"),
    ]
    return plan, items, findings, False


def zipher() -> tuple[dict[str, object], list[ItemFacts], list[FindingFacts], bool]:
    """Run `6356fb4e`, version `c582d938`. Six emphases, **pre-T094**.

    The revision replaced the draft's item set, so for every emphasis but the
    summary the absence of a proposal is not evidence of absence of an attempt.
    """
    plan = _plan("8c715699", "93c80b50", "b3b96ffa", "5813b809", "48100a48", "cd5f3821")
    items = [
        _item("8c715699", "summary", original="summary orig", proposed="summary rewritten"),
        _item("93c80b50"),
        _item("b3b96ffa"),
        _item("5813b809"),
        _item("48100a48"),
        _item("cd5f3821"),
    ]
    findings = [FindingFacts("8c715699", "overstated", "Production experience with Python")]
    return plan, items, findings, True  # contaminated


def _run(
    fixture: tuple[dict[str, object], list[ItemFacts], list[FindingFacts], bool],
) -> dict[str, object]:
    """Call `plan_execution` with a fixture's four parts."""
    plan, items, findings, contaminated = fixture
    return plan_execution(plan, items=items, findings=findings, contaminated=contaminated)


# --- the state vector ------------------------------------------------------


def test_cellebrite_states() -> None:
    """Three survived, three show no evidence, one is a label-kind target — and
    the duplicated id is collapsed to seven distinct entries, not eight."""
    plan, items, findings, contaminated = cellebrite()
    result = plan_execution(plan, items=items, findings=findings, contaminated=contaminated)

    assert result["planned"] == 8, "the plan really did carry eight entries"
    assert result["distinct"] == 7, "the duplicate must be collapsed before counting"
    assert result["states"] == {
        "survived": 3,
        # `unknown_position`, not `no_evidence` (T095). This run predates
        # `displaced_position`, and it demonstrably *did* receive position-only
        # proposals: its nine bullets hold five distinct positions, and master
        # ordering is a unique sequence, so duplicates can only come from
        # proposals. Reading these as "the draft did nothing" was wrong.
        "unknown_position": 3,
        "label_kind": 1,
    }
    assert sum(result["states"].values()) == 7, "every distinct entry must be classified once"


def test_harman_states() -> None:
    """Nothing survived: two were reverted, one discarded, two never evidenced,
    and two name skill labels with no prose to rewrite."""
    plan, items, findings, contaminated = harman()
    result = plan_execution(plan, items=items, findings=findings, contaminated=contaminated)

    assert result["distinct"] == 7
    assert result["states"] == {
        "reverted": 2,
        "discarded": 1,
        # Same correction as Cellebrite: Harman's nine bullets hold five
        # distinct positions, so it reordered too (T095).
        "unknown_position": 2,
        "label_kind": 2,
    }
    assert result["states"].get("survived", 0) == 0, (
        "a reverted proposal changes nothing and must never count as survived"
    )
    assert sum(result["states"].values()) == 7


def test_zipher_states_are_unknown_not_failed() -> None:
    """One survived; the other five are unknowable, because the pre-T094
    revision erased whatever the draft decided. Unknown is not failure."""
    plan, items, findings, contaminated = zipher()
    result = plan_execution(plan, items=items, findings=findings, contaminated=contaminated)

    assert result["distinct"] == 6
    assert result["contaminated"] is True
    assert result["states"] == {"survived": 1, "unknown": 5}
    assert result["states"].get("no_evidence", 0) == 0, (
        "on a contaminated run, a missing proposal proves nothing and must not "
        "be recorded as evidence of a draft that did nothing"
    )


# --- the two summary measures ---------------------------------------------


def test_draft_compliance_is_identical_across_the_two_clean_runs() -> None:
    """D1 — did the draft act on the plan? Cellebrite and Harman both acted on
    three of seven distinct emphases by text. The spread between their D0
    figures is not a difference in what the draft did.

    Since T095 the *ratio* is withheld for both: they predate
    `displaced_position`, so the remaining items cannot say whether a proposal
    arrived, and the position data proves some did."""
    c = _run(cellebrite())
    h = _run(harman())

    # Both still acted on three, and the counts are what remain comparable.
    assert c["d1_draft_compliance"]["acted"] == 3
    assert h["d1_draft_compliance"]["acted"] == 3

    # **The ratios are now withheld** (T095). Both runs predate
    # `displaced_position`, so for the items with no text evidence it is
    # unknowable whether a proposal arrived — and both demonstrably reordered.
    # The 0.429 these once reported treated "no text proposal" as "no
    # proposal", which the position data disproves.
    assert c["d1_draft_compliance"]["unknown_position"] == 3
    assert h["d1_draft_compliance"]["unknown_position"] == 2
    assert c["d1_draft_compliance"]["ratio"] is None
    assert h["d1_draft_compliance"]["ratio"] is None


def test_plan_effect_excludes_label_kind_targets_from_the_denominator() -> None:
    """D3 — did the plan change the document? Cellebrite three of six
    addressable; Harman zero of five, because its two skill targets carry no
    prose and are not counted against it."""
    c = _run(cellebrite())
    h = _run(harman())

    assert c["d3_plan_effect"]["survived"] == 3
    assert c["d3_plan_effect"]["addressable"] == 6, "seven distinct minus one skill label"
    assert c["d3_plan_effect"]["ratio"] == 0.5

    assert h["d3_plan_effect"]["survived"] == 0
    assert h["d3_plan_effect"]["addressable"] == 5, "seven distinct minus two skill labels"
    assert h["d3_plan_effect"]["ratio"] == 0.0


def test_a_contaminated_run_reports_no_ratio() -> None:
    """Zipher's one known survival over one determinable entry would read as
    perfect execution. A ratio nobody can compare is worse than no ratio; the
    counts still carry what is known."""
    z = _run(zipher())

    assert z["d1_draft_compliance"]["ratio"] is None
    assert z["d3_plan_effect"]["ratio"] is None
    assert z["d1_draft_compliance"]["acted"] == 1, "what is known is still reported"
    assert z["d3_plan_effect"]["survived"] == 1
    assert z["states"]["unknown"] == 5


# --- D0 preserved, and what it gets wrong ----------------------------------


def test_d0_is_preserved_unchanged() -> None:
    """The old figure still computes, so the two can be compared while the new
    one accumulates a distribution."""
    plan, items, _, _ = cellebrite()
    rewritten = [i.source_item_id for i in items if i.proposed_text is not None]
    assert emphasis_adherence(plan, rewritten_ids=rewritten)["adherence"] == 0.5


def test_d0_counts_a_reverted_proposal_as_executed_and_the_new_measure_does_not() -> None:
    """The defect, side by side on the same run. Harman's only two D0
    executions are exactly the two proposals reverted to the owner's wording."""
    plan, items, findings, contaminated = harman()
    rewritten = [i.source_item_id for i in items if i.proposed_text is not None]

    old = emphasis_adherence(plan, rewritten_ids=rewritten)
    new = plan_execution(plan, items=items, findings=findings, contaminated=contaminated)

    assert old["executed"] == 2 and old["adherence"] == 0.286
    assert new["d3_plan_effect"]["survived"] == 0
    assert new["states"]["reverted"] == 2, "the two D0 counted are the two the document never kept"


def test_d0_double_counts_a_duplicated_planned_id() -> None:
    """Cellebrite names `cd5f3821` twice; D0 scores one rewrite as two."""
    plan, items, findings, contaminated = cellebrite()
    rewritten = [i.source_item_id for i in items if i.proposed_text is not None]

    old = emphasis_adherence(plan, rewritten_ids=rewritten)
    new = plan_execution(plan, items=items, findings=findings, contaminated=contaminated)

    assert old["with_ids"] == 8, "D0 counts the duplicate as a second emphasis"
    assert new["distinct"] == 7
    assert new["duplicates_collapsed"] == 1
