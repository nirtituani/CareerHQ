"""What the four tailoring completions return.

Specified by `specs/005-resume-tailoring/contracts/tailoring-workflow.md`. Named
with schema-ish nouns rather than the ORM's nouns for the same reason
`MatchJudgement` is: `tailor_resume.py` imports both, and two `TailoringPlan`s
would make every call site ambiguous.

**Draft and Revise return item identifiers with changed text, never the whole
resume.** This is a hard requirement of the schemas rather than an optimisation
to apply later. Output is the slow half of a completion and 57-86% of the cost,
and slice 003 measured the consequence directly: asking a model to retype text
it was already given took 52 seconds and timed out the frontend proxy, against
5.4 seconds when it returned metadata only.
"""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class EmphasisDirective(BaseModel):
    """One thing the plan says to lead with, and which requirement it serves."""

    source_item_id: UUID | None = Field(
        default=None, description="The profile fact, when this points at exactly one"
    )
    what: str = Field(description="What to emphasise, in the plan's own words")
    #: Which requirement this serves. Ties the strategy back to the posting, so
    #: a plan cannot emphasise something for no stated reason.
    serves_requirement: str = Field(description="The job requirement this addresses")


class ProtectedGap(BaseModel):
    """Something the profile does not support, named so the draft avoids it.

    Carried from the match analysis's `gap` and `unverified` verdicts. This is
    the plan's most important output: the grounding rule is *enforced* at
    finalisation, but naming the specific gaps up front is what stops a draft
    drifting toward them in the first place. Enforcement catches a fabrication;
    this prevents one.
    """

    requirement: str
    why_protected: str = Field(
        description="Why this must not be claimed — what the profile does and does not show"
    )


class TailoringPlan(BaseModel):
    """The strategy the draft is written against.

    Separate from the draft because one call producing both the strategy and the
    prose is the shape of slice 004's scoring bug: a summary computed
    independently of the thing it summarises is free to disagree with it, and
    here the disagreement would be silent — prose quietly optimising for
    something other than the plan nobody wrote down.
    """

    emphasise: list[EmphasisDirective] = Field(min_length=1)
    de_emphasise: list[str] = Field(
        default_factory=list,
        description="Present in the profile, not relevant to this posting",
    )
    protected_gaps: list[ProtectedGap] = Field(default_factory=list)
    strategy: str = Field(description="One paragraph: how this resume should read, and why")


class DraftedItem(BaseModel):
    """One item the agent proposes to change, keep, or drop.

    `text` is null when nothing changes — that is what keeps the payload
    proportional to the *diff* rather than to the resume.
    """

    source_item_id: UUID | None = None
    source_kind: Literal[
        "summary",
        "title",
        "experience_bullet",
        "skill",
        "project",
        "education",
        "certification",
        "language",
    ]
    #: Where this sits in its section. Ordering is part of tailoring: leading
    #: with what is relevant to this posting is most of what a reader notices.
    position: int = Field(ge=0)
    included: bool = True
    text: str | None = Field(
        default=None, description="The rewritten text. Null when the wording is unchanged."
    )
    #: Why this change, in one sentence. Principle III requires every
    #: recommendation to carry an explanation, and this is what the diff shows
    #: beside the proposal.
    reason: str | None = None

    @model_validator(mode="after")
    def _a_change_explains_itself(self) -> Self:
        """A rewrite with no reason is a change the owner cannot judge."""
        if self.text is not None and not (self.reason or "").strip():
            raise ValueError("a proposed rewrite must carry a reason (Principle III)")
        return self


class TailoredDraft(BaseModel):
    """What Draft and Revise both return."""

    items: list[DraftedItem] = Field(min_length=1)


class ReviewFinding(BaseModel):
    """One concern, typed so finalisation can route on it.

    The `kind` set is closed because the routing is where Principle III is
    enforced: `ungrounded` is discarded before persistence and never shown as a
    choice, while `overstated` and `uncovered` are shown to the owner. A
    free-text concern cannot be routed, so a free-text concern cannot enforce
    anything.
    """

    kind: Literal["ungrounded", "overstated", "uncovered"]
    source_item_id: UUID | None = Field(
        default=None, description="The item this concerns. Null for draft-level findings."
    )
    detail: str = Field(description="What is wrong, in the Reviewer's own words")
    quoted_text: str | None = Field(default=None, description="The exact words objected to")

    @model_validator(mode="after")
    def _findings_carry_what_their_kind_requires(self) -> Self:
        """Two rules, each learned from a failure in slice 004.

        **`ungrounded` must quote.** A finding that says "this is unsupported"
        without saying which words cannot be tested, cannot be displayed, and
        cannot be checked by a person — and it lets the model assert an absence
        it has no basis for, which is AI-008's fabrication pointed the other way.

        **`uncovered` must not name an item.** There is no item for an
        unaddressed requirement to attach to. Demanding one would repeat slice
        004's `unverified`-shortfall mistake exactly: a real completion failed
        validation on a field the model was *right* not to fill, because the
        honest answer was that there was nothing to point at.
        """
        if self.kind == "ungrounded" and not (self.quoted_text or "").strip():
            raise ValueError("an ungrounded finding must quote the words it objects to")
        if self.kind == "uncovered" and self.source_item_id is not None:
            raise ValueError("an uncovered finding concerns the draft, not one item")
        if self.kind != "uncovered" and self.source_item_id is None:
            raise ValueError(f"a {self.kind} finding must name the item it concerns")
        return self


class ReviewResult(BaseModel):
    """What the Reviewer returns.

    `confidence` is a judgement about *this draft* — how sound the writing is
    given the profile. It is not the match score, which is a judgement about the
    person's fit and is computed by entirely different means. The two are never
    shown as one number (FR-043).
    """

    confidence: int = Field(ge=0, le=100)
    findings: list[ReviewFinding] = Field(default_factory=list)
