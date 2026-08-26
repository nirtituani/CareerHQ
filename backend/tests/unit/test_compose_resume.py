"""What the Reviewer is shown, and why it was wrong.

`build_review_prompt` passed the master plus `state.items` — which the Draft
node fills with **only the items it is changing or dropping** — under the
heading "## The draft". On a run that changed one line, the Reviewer was handed
one line and told it was the resume. It then reported eight things missing that
were present, naming the exact bullet ids it believed had been omitted:

    "The draft omits this bullet entirely" — of a bullet that was never touched.

`uncovered` asks what the *document* fails to address. That question cannot be
answered from a diff. `overstated` and `ungrounded` were unaffected, because
they judge proposed text, which the Reviewer did see.

The fix is a view, not more data: the Reviewer already received everything. It
is composed here, in a pure function, and it is **input-side only** — Draft and
Revise still return item ids with changed text and never the whole resume, which
research R5 identifies as 57-86% of the cost and the slow half of a completion.
"""

from __future__ import annotations

import uuid
from typing import Any

from careerhq.application.agents.tailoring.prompts import (
    _DRAFT,
    build_review_prompt,
    build_revise_prompt,
    compose_resume,
)
from careerhq.application.agents.tailoring.state import TailoringState
from careerhq.domain.schemas.tailoring import DraftedItem, TailoredDraft

SUMMARY = uuid.uuid4()
KEPT = uuid.uuid4()
CHANGED = uuid.uuid4()
DROPPED = uuid.uuid4()


def _master() -> list[dict[str, Any]]:
    """The shape `_render_master` already returns as its second value."""
    return [
        {"source_item_id": SUMMARY, "source_kind": "summary", "position": 0, "text": "A summary."},
        {
            "source_item_id": KEPT,
            "source_kind": "experience_bullet",
            "position": 0,
            "text": "Designed distributed event-driven systems using IBM MQ and ActiveMQ.",
        },
        {
            "source_item_id": CHANGED,
            "source_kind": "experience_bullet",
            "position": 1,
            "text": "Building cloud-based applications using AWS.",
        },
        {"source_item_id": DROPPED, "source_kind": "skill", "position": 0, "text": "SVN"},
    ]


def _state(items: list[DraftedItem] | None = None) -> TailoringState:
    return TailoringState(
        job={"title": "Senior Backend Engineer"},
        master="(the profile, rendered)",
        master_items=_master(),
        match={},
        items=items or [],
    )


def _drafted() -> list[DraftedItem]:
    return [
        DraftedItem(
            source_item_id=CHANGED,
            source_kind="experience_bullet",
            position=1,
            text="Built and deployed cloud-native applications on AWS (Lambda, EC2, S3, IAM).",
            reason="Names the services the posting asks for.",
        ),
        DraftedItem(source_item_id=DROPPED, source_kind="skill", position=0, included=False),
    ]


# -- 1. the composition itself ----------------------------------------------


def test_an_unchanged_item_appears_with_the_owners_own_wording() -> None:
    composed = compose_resume(_state(_drafted()))

    assert "Designed distributed event-driven systems using IBM MQ and ActiveMQ." in composed
    assert "A summary." in composed


def test_a_changed_item_appears_once_as_the_proposal_and_not_as_the_original() -> None:
    composed = compose_resume(_state(_drafted()))

    assert "Built and deployed cloud-native applications on AWS" in composed
    # The superseded wording must not sit beside its replacement: the Reviewer
    # would read the resume as containing both.
    assert "Building cloud-based applications using AWS." not in composed


def test_a_dropped_item_is_absent() -> None:
    composed = compose_resume(_state(_drafted()))

    # And its absence is the truth: a requirement it answered is now genuinely
    # unaddressed, which is exactly what `uncovered` should catch.
    assert "SVN" not in composed


def test_every_line_keeps_its_id() -> None:
    composed = compose_resume(_state(_drafted()))

    for item_id in (SUMMARY, KEPT, CHANGED):
        assert f"[id: {item_id}]" in composed
    assert f"[id: {DROPPED}]" not in composed


def test_a_draft_that_changed_nothing_composes_the_master_unchanged() -> None:
    composed = compose_resume(_state([]))

    for row in _master():
        assert row["text"] in composed


# -- 2. the regression gate -------------------------------------------------


def test_the_review_prompt_carries_every_unchanged_item() -> None:
    """**The gate for the defect this file exists for.**

    On the Zipher run this prompt carried one summary. The Reviewer concluded
    the resume had no experience bullets and raised eight `uncovered` findings
    against content that was sitting in the resume untouched.
    """
    prompt = build_review_prompt(_state(_drafted()))

    # Untouched by this draft: neither rewritten nor dropped. These are the ones
    # that vanished from the Reviewer's view and produced findings against
    # content that was present all along. A rewritten item is excluded here on
    # purpose — its *original* wording must not appear beside its replacement,
    # which `test_a_changed_item_appears_once...` asserts from the other side.
    untouched = [row for row in _master() if row["source_item_id"] not in (DROPPED, CHANGED)]
    assert len(untouched) == 2

    missing = [row["text"] for row in untouched if row["text"] not in prompt]
    assert not missing, f"{len(missing)} unchanged items never reach the Reviewer: {missing}"


def test_the_revise_prompt_carries_them_too() -> None:
    """Revise is told to fix `uncovered` findings. It cannot reason about
    coverage from a diff either."""
    prompt = build_revise_prompt(_state(_drafted()))

    assert "Designed distributed event-driven systems using IBM MQ" in prompt


def test_the_profile_is_still_sent_whole_for_grounding() -> None:
    """Composition replaces the *draft* view, never the master.

    Grounding asks whether a claim traces to anything in the profile —
    including facts the draft dropped or never touched. Judging that against
    the resulting resume alone would make a claim self-justifying.
    """
    assert "(the profile, rendered)" in build_review_prompt(_state(_drafted()))


# -- 3. changed items stay identifiable -------------------------------------


def test_a_changed_line_is_marked_so_findings_can_still_attach() -> None:
    """`overstated` and `ungrounded` must name the item they concern.

    If composition rendered proposals indistinguishably from the owner's own
    wording, the Reviewer would have no way to tell which lines it may object
    to — and would start objecting to the profile.
    """
    composed = compose_resume(_state(_drafted()))

    changed_line = next(line for line in composed.splitlines() if str(CHANGED) in line)
    kept_line = next(line for line in composed.splitlines() if str(KEPT) in line)

    assert "rewritten" in changed_line.lower()
    assert "rewritten" not in kept_line.lower()


def test_the_prompt_explains_what_the_marking_means() -> None:
    prompt = build_review_prompt(_state(_drafted()))
    lowered = prompt.lower()

    assert "rewritten" in lowered
    assert "unchanged" in lowered


# -- 5. the output contract is unchanged ------------------------------------


def test_the_draft_still_returns_only_what_it_changes() -> None:
    """**The cost lever, guarded.**

    This change is input-side. The obvious wrong version of it — show the model
    a whole resume, let it return a whole resume — would convert R5's stated
    lever into R5's stated problem: slice 003 measured 52 seconds and a proxy
    timeout from asking a model to retype text it was given, and output is
    57-86% of the bill.
    """
    assert "only the items you are changing or dropping" in _DRAFT
    assert "Do not retype the resume." in _DRAFT

    # And the schema still describes a diff: nothing requires every item back.
    assert TailoredDraft.model_fields["items"].is_required()
    assert set(DraftedItem.model_fields) == {
        "source_item_id",
        "source_kind",
        "position",
        "included",
        "text",
        "reason",
    }
