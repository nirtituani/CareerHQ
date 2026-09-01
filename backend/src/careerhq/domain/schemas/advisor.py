"""What the two advisor completions return, and the evidence facts they read.

Specified by `specs/009-career-advisor/contracts/reasoning-contract.md`.

**Every conditional rule below lives in `Field(description=...)`.** A
`model_validator(mode="after")` does not serialise, and the JSON Schema is the
whole contract the gateway sends — a rule the model cannot see is a rule it
cannot follow (the slice-005 lesson). The deterministic gate in
`application/advisor_grounding.py` is the enforcement; these descriptions are
the instruction.

**The model is never the source of a number.** `EvidenceFact` is produced by
`application/advisor_evidence.py` from SQL and arithmetic; the reasoning step
receives facts and cites them by id. A claim whose digits are not in its cited
facts is discarded before persistence (spec FR-005/FR-009).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Evidence — deterministic input, never model output
# ---------------------------------------------------------------------------


class EvidenceFact(BaseModel):
    """One deterministic quantitative fact, individually addressable.

    Percentages and deltas are precomputed as facts of their own so the model
    never has a reason to do arithmetic (research.md D2).
    """

    fact_id: str = Field(description="Deterministic slug, e.g. 'outcome.rejection_rate.global'")
    kind: str = Field(description="Fact family, e.g. 'outcome', 'volume', 'tier2.requirement'")
    scope_kind: str = Field(description="'global', 'role_family', 'skill', 'status' or 'source'")
    scope_value: str | None = Field(
        default=None, description="The scope's value; None exactly when scope_kind is 'global'"
    )
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: str = Field(description="The fact rendered as one sentence, digits included")
    date_range: tuple[date, date] | None = Field(
        default=None, description="The period the counted rows span, when meaningful"
    )
    #: The rows this fact was computed from. What makes SC-001's independent
    #: recomputation a test that can actually run.
    record_ids: list[UUID] = Field(default_factory=list)
    basis: str = Field(description="One sentence naming the computation")


class EvidenceGrouping(BaseModel):
    """A grouping a fact depends on, frozen so the arithmetic stays auditable."""

    group_id: str
    label: str
    group_kind: str
    member_ids: list[UUID]


class EvidencePack(BaseModel):
    """Everything one run computed. A function of (rows, as-of, rules version)."""

    as_of: datetime
    rules_version: str
    facts: list[EvidenceFact]
    groupings: list[EvidenceGrouping] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task `advisor_grouping` — optional, Haiku
# ---------------------------------------------------------------------------


class ProposedGroup(BaseModel):
    """One group over enumerated ids. Counting happens later, deterministically."""

    group_id: str = Field(description="Short slug you assign, unique in this response")
    label: str = Field(description="Human name for the group, e.g. 'AWS' or 'Backend'")
    group_kind: str = Field(
        description="'role_family' for title groups, 'skill' for requirement groups"
    )
    member_ids: list[UUID] = Field(
        description=(
            "Only ids listed in the input. Never invent an id. A group with fewer than 2 "
            "members should usually be omitted."
        )
    )


class GroupingProposal(BaseModel):
    """The whole grouping answer. Evidence, not truth — it is frozen into any
    memory that relies on it, so a reader can audit the grouping as well as the
    arithmetic."""

    groups: list[ProposedGroup]


# ---------------------------------------------------------------------------
# Task `advisor_reason` — Sonnet
# ---------------------------------------------------------------------------


class ProposedMemory(BaseModel):
    """One claim the agent judges worth remembering."""

    claim: str = Field(
        description=(
            "One falsifiable sentence. Every number in it must appear verbatim in the cited "
            "facts, and it must state at least one cited fact's numerator and denominator "
            "(e.g. '16 of 20'). No causal language — word co-occurrence as co-occurrence."
        )
    )
    kind: str = Field(
        description="Pattern kind slug, e.g. 'recurring_gap', 'strength', 'trend'. Open vocabulary."
    )
    scope_kind: str = Field(description="'global', 'role_family', 'skill', 'status' or 'source'")
    scope_value: str | None = Field(
        default=None, description="Required unless scope_kind is 'global'; then omit it"
    )
    cited_fact_ids: list[str] = Field(
        description=(
            "At least one fact_id from the evidence. Cite only facts that directly support "
            "the claim."
        )
    )
    grouping_ids: list[str] = Field(
        default_factory=list,
        description="group_ids the cited facts depend on, if any",
    )
    priority: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "0-100 when the memory is actionable (something the user could act on); omit "
            "otherwise. When set, priority_reason is required."
        ),
    )
    priority_reason: str | None = Field(
        default=None, description="Required exactly when priority is set; omit otherwise"
    )
    tentative: bool = Field(
        description=(
            "Must be true when any cited fact's denominator is below the floor of 5. The "
            "gate will force it true rather than refuse — but say it yourself."
        )
    )


class MemoryDispositionOp(BaseModel):
    """The agent's explicit decision about one prior memory.

    Every id rendered as `[memory: ...]` in the input must appear in exactly
    one of these. Omitting one fails the whole run — `leave_open` is a
    decision you state, never a default filled in for a memory you forgot
    (spec FR-013, the agent-managed-memory invariant).
    """

    memory_id: UUID = Field(
        description=(
            "An id rendered as [memory: ...] in the input. Every such id must appear in "
            "exactly one disposition."
        )
    )
    action: str = Field(description="'confirm', 'supersede', 'retire' or 'leave_open'")
    reason: str | None = Field(
        default=None,
        description="Required for 'retire' and 'leave_open'; omit for 'confirm' and 'supersede'",
    )
    superseding_index: int | None = Field(
        default=None,
        ge=0,
        description=(
            "For 'supersede' only: index into created[] of the memory that replaces this "
            "one, which must state what changed."
        ),
    )
    fresh_fact_ids: list[str] = Field(
        default_factory=list,
        description=(
            "For 'confirm': current facts showing the claim still holds; recorded as the "
            "confirmation's evidence delta."
        ),
    )


class AdvisorReasoning(BaseModel):
    """The reasoning step's whole answer: creations plus dispositions."""

    created: list[ProposedMemory] = Field(default_factory=list)
    dispositions: list[MemoryDispositionOp] = Field(default_factory=list)
    nothing_found_reason: str | None = Field(
        default=None,
        description=(
            "Required exactly when created is empty and no disposition supersedes: say "
            "honestly why the evidence supports no new memory."
        ),
    )
