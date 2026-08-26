"""A finding the Reviser fixed must not keep forcing revisions (T096).

`state.findings` accumulates by design — it is the evidence the guardrail ran,
and T093 made each entry carry the pass that raised it. But `after_review`
handed the **whole accumulated history** to `should_revise`, and
`clears_review` fails on *any* `ungrounded` finding. So a fabrication caught on
pass 0 made the gate permanently unpassable: however well the Reviser fixed it,
the stale finding was still in the list, and the run spent its entire revision
budget every time.

Measured on the real Harman run `60263226`, from its own persisted rows. Its
three review passes found:

    attempt 0 -> 1 ungrounded, 2 overstated, 3 uncovered   (confidence 72)
    attempt 1 -> 4 uncovered                               (confidence 86)
    attempt 2 -> 4 uncovered                               (confidence 88)

`uncovered` never blocks and 86 clears the threshold of 70, so **pass 1 already
cleared on its own findings**. The run continued anyway, spending
`tailor_revise_escalated` on Opus ($0.065685, 897 output tokens) and a third
`tailor_review` on Opus ($0.081715, 1,364 output tokens): **$0.147400 and 2,261
output tokens, 26.9% of that run's $0.547891, with nothing left to fix.**
(Per-call latency is not instrumented; at the ~92 tok/s measured across the six
real runs those 2,261 tokens are on the order of 25s, which is derived rather
than measured.)

The fix is not a smaller budget and not a softer gate. The Reviewer re-judges
the **whole composed resume** on every pass (`_REVIEW` is built from
`compose_resume`, not from a diff), so the findings raised on the current pass
are already a complete statement about the document as it now stands. A claim
that is still ungrounded is re-reported and still blocks; one that was fixed is
simply absent.

What must not change, and is asserted below:

* an ungrounded finding raised on the **current** pass still blocks completion;
* the accumulated history still holds every pass's findings for persistence;
* `MAX_REVISIONS` still bounds the loop;
* the confidence threshold still applies.
"""

from __future__ import annotations

import uuid
from typing import Any

from careerhq.application.agents.tailoring import build_tailoring_graph
from careerhq.application.agents.tailoring.graph import active_findings
from careerhq.application.agents.tailoring.state import RaisedFinding, TailoringState
from careerhq.domain.schemas.tailoring import ReviewFinding
from tests.support.scripted_seam import ScriptedSeam

BULLET = uuid.uuid4()


def _master_items() -> list[dict[str, Any]]:
    return [
        {
            "source_item_id": BULLET,
            "source_kind": "experience_bullet",
            "position": 0,
            "text": "Used AI-assisted development tools across enterprise codebases.",
        }
    ]


def _state() -> TailoringState:
    return TailoringState(
        job={"title": "Backend Engineer", "description": "Platform.", "requirements": []},
        master="(the profile, rendered)",
        master_items=_master_items(),
        match={},
    )


def _plan() -> dict[str, Any]:
    return {
        "emphasise": [{"what": "AI tooling fluency", "serves_requirement": "AI proficiency"}],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with AI tooling.",
    }


def _proposal(text: str) -> dict[str, Any]:
    return {
        "source_item_id": str(BULLET),
        "source_kind": "experience_bullet",
        "position": 0,
        "included": True,
        "text": text,
        "reason": "Answers the posting's AI-proficiency requirement.",
    }


def _ungrounded() -> list[dict[str, Any]]:
    """The real Harman finding: a qualifier the profile never supports."""
    return [
        {
            "kind": "ungrounded",
            "source_item_id": str(BULLET),
            "detail": "The profile does not say the codebases were unfamiliar.",
            "quoted_text": "complex, unfamiliar enterprise codebases",
        }
    ]


def _review(confidence: int, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"confidence": confidence, "findings": findings or []}


def _raised(kind: str, attempt: int) -> RaisedFinding:
    return RaisedFinding(
        finding=ReviewFinding(
            kind=kind,
            source_item_id=BULLET,
            detail="detail",
            quoted_text="quoted",
        ),
        attempt=attempt,
    )


# -- the selection rule, as a pure function ----------------------------------


def test_active_findings_selects_only_the_current_pass() -> None:
    state = _state()
    state.attempt = 1
    state.findings = [_raised("ungrounded", 0), _raised("overstated", 1)]

    active = active_findings(state)

    assert [f.kind for f in active] == ["overstated"], (
        "a finding raised on an earlier pass does not describe the current draft"
    )


def test_active_findings_keeps_a_finding_re_raised_on_the_current_pass() -> None:
    state = _state()
    state.attempt = 1
    state.findings = [_raised("ungrounded", 0), _raised("ungrounded", 1)]

    assert [f.kind for f in active_findings(state)] == ["ungrounded"]


def test_active_findings_reads_the_first_pass_when_nothing_has_been_revised() -> None:
    state = _state()
    state.findings = [_raised("ungrounded", 0)]

    assert len(active_findings(state)) == 1, "attempt 0 findings describe the first draft"


# -- the loop, driven end to end through the scripted seam -------------------


async def test_a_resolved_ungrounded_finding_stops_the_loop() -> None:
    """**The regression.** The Harman trajectory: fabricate, get caught, fix.

    The script deliberately provides **no** `tailor_revise_escalated` answer.
    Before the fix the run reached for one and the seam raised
    `ScriptExhausted` — which is the wasted second revision, made visible.
    """
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [
                {"items": [_proposal("Worked across complex, unfamiliar enterprise codebases.")]}
            ],
            "tailor_review": [
                _review(88, _ungrounded()),  # pass 0: caught
                _review(92),  # pass 1: the fix cleared it
            ],
            "tailor_revise": [
                {"items": [_proposal("Worked across complex enterprise codebases.")]}
            ],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    assert result["attempt"] == 1, (
        f"one revision fixed the finding; the run must stop there, got attempt={result['attempt']}"
    )
    assert seam.times_called("tailor_revise") == 1
    assert seam.times_called("tailor_revise_escalated") == 0, (
        "the escalated revision had nothing left to fix — this is the waste"
    )
    assert seam.times_called("tailor_review") == 2
    assert seam.tasks_called == [
        "tailor_plan",
        "tailor_draft",
        "tailor_review",
        "tailor_revise",
        "tailor_review",
    ]


async def test_the_accumulated_history_still_holds_every_pass() -> None:
    """The gate stops reading stale findings; persistence must still see them.

    The record of what the Reviewer caught is the evidence the guardrail ran
    (T093), and slice 007 measures against it.
    """
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [{"items": [_proposal("Unfamiliar codebases.")]}],
            "tailor_review": [_review(88, _ungrounded()), _review(92)],
            "tailor_revise": [{"items": [_proposal("Enterprise codebases.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    raised = result["findings"]
    assert len(raised) == 1, "the pass-0 finding must survive in state for persistence"
    assert raised[0].finding.kind == "ungrounded"
    assert raised[0].attempt == 0, "and must still carry the pass that raised it"


async def test_a_still_active_ungrounded_finding_still_blocks() -> None:
    """**The safety half.** A fabrication the Reviser did not fix is re-reported
    by a Reviewer that re-reads the whole resume, and must still force a
    revision — with the Sonnet→Opus escalation intact."""
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [{"items": [_proposal("Unfamiliar codebases.")]}],
            "tailor_review": [
                _review(95, _ungrounded()),  # pass 0
                _review(95, _ungrounded()),  # pass 1: still wrong
                _review(95, _ungrounded()),  # pass 2: still wrong, budget spent
            ],
            "tailor_revise": [{"items": [_proposal("Still unfamiliar codebases.")]}],
            "tailor_revise_escalated": [{"items": [_proposal("Yet again unfamiliar.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    assert result["attempt"] == 2, "a live fabrication must spend the budget"
    assert seam.times_called("tailor_revise") == 1
    assert seam.times_called("tailor_revise_escalated") == 1, (
        "the second attempt must still escalate Sonnet -> Opus by task name"
    )
    assert seam.times_called("tailor_review") == 3


async def test_high_confidence_never_clears_a_current_ungrounded_finding() -> None:
    """Confidence cannot buy off Principle III on the pass that raised it."""
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [{"items": [_proposal("Unfamiliar codebases.")]}],
            "tailor_review": [_review(100, _ungrounded()), _review(100)],
            "tailor_revise": [{"items": [_proposal("Enterprise codebases.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    assert seam.times_called("tailor_revise") == 1, (
        "confidence 100 with a live ungrounded finding must still revise"
    )
    assert result["attempt"] == 1


async def test_low_confidence_alone_still_revises() -> None:
    """The threshold is untouched by this change."""
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [{"items": [_proposal("Enterprise codebases.")]}],
            "tailor_review": [_review(40), _review(88)],
            "tailor_revise": [{"items": [_proposal("Large enterprise codebases.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    assert seam.times_called("tailor_revise") == 1
    assert result["attempt"] == 1


async def test_the_revision_budget_is_still_bounded_at_two() -> None:
    """FR-013. Low confidence throughout, and the loop must still stop."""
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [{"items": [_proposal("Enterprise codebases.")]}],
            "tailor_review": [_review(10), _review(10), _review(10)],
            "tailor_revise": [{"items": [_proposal("One.")]}],
            "tailor_revise_escalated": [{"items": [_proposal("Two.")]}],
        }
    )

    result = await build_tailoring_graph(seam).ainvoke(_state())

    assert result["attempt"] == 2
    assert seam.times_called("tailor_review") == 3
