"""The grounding gate: what a proposed memory must survive to be persisted.

`finalisation_rules.py` discards an ungrounded resume claim before it can
reach an approve button; this module does the same for statistics (spec
FR-009, Constitution III). The gate runs in the contract's order
(reasoning-contract.md), every refusal is logged with structured fields —
Railway blanks `message`, so the fields are the record — and counted, so a
run that discarded everything is distinguishable from a run that found
nothing.

**Deterministic throughout.** The pack is ground truth; an LLM verifier pass
would be a model auditing a model with the answer key already on the table
(research.md D5).

**The `leave_open` -> `left_open` translation lives here and only here**
(analyze I1): the schema speaks in verbs (what the model chooses), the log
table in participles (what the run recorded), and `_ACTION_TO_RECORD` is the
single mapping between the two vocabularies.

One documented downgrade: a `supersede` whose replacement claim was itself
discarded cannot be honoured — the disposition becomes `left_open` with a
machine-stated reason and the event is recorded as a discard. This is not the
forbidden default (invariant 1 targets memories the model *omitted*; this one
was explicitly dispositioned) — it is the gate refusing to let a bad claim
take a good memory down with it.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from careerhq.application.advisor_rules import (
    ACTIVE_MEMORY_CAP,
    CAUSAL_PHRASES,
    SMALL_SAMPLE_FLOOR,
)
from careerhq.domain.models import USER_DISMISSED, CareerMemory, DispositionAction
from careerhq.domain.schemas.advisor import (
    AdvisorReasoning,
    EvidenceFact,
    EvidenceGrouping,
    EvidencePack,
    GroupingProposal,
    ProposedMemory,
)

logger = logging.getLogger(__name__)

_NUMERAL = re.compile(r"\d+(?:\.\d+)?")

#: The verb/participle mapping — the only place it exists.
_ACTION_TO_RECORD: dict[str, DispositionAction] = {
    "confirm": DispositionAction.CONFIRMED,
    "supersede": DispositionAction.SUPERSEDED,
    "retire": DispositionAction.RETIRED,
    "leave_open": DispositionAction.LEFT_OPEN,
}

#: Actions after which the memory still counts toward the active set — the
#: G4 evaluation order reads the cap against this, not against the
#: pre-disposition set.
_STAYING_ACTIONS = frozenset({"confirm", "leave_open"})


class DispositionDefect(Exception):
    """FR-013 violated: the run's dispositions do not cover the active set
    exactly once each, or a stated disposition is malformed. This fails the
    **run** — an unaccounted-for memory is never silently defaulted."""


@dataclass(frozen=True, slots=True)
class DiscardRecord:
    gate: str
    detail: str
    claim: str


@dataclass(frozen=True, slots=True)
class PlannedCreate:
    proposal: ProposedMemory
    #: The gate's verdict, which may override the model's (the floor forces
    #: tentative; it never refuses for smallness alone).
    tentative: bool
    recreates_dismissed_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class PlannedDisposition:
    memory_id: uuid.UUID
    action: DispositionAction
    reason: str | None
    evidence_delta: dict[str, Any] | None
    #: Which surviving create replaces this memory, for `superseded` only —
    #: an index into `GateOutcome.creates`.
    superseding_create: int | None = None


@dataclass(slots=True)
class GateOutcome:
    creates: list[PlannedCreate]
    dispositions: list[PlannedDisposition]
    discards: list[DiscardRecord] = field(default_factory=list)

    @property
    def proposed(self) -> int:
        return len(self.creates) + len(self.discards)

    @property
    def applied(self) -> int:
        return len(self.creates)

    @property
    def discarded(self) -> int:
        return len(self.discards)


def freeze_evidence(proposal: ProposedMemory, pack: EvidencePack) -> dict[str, Any]:
    """The subset of the pack a surviving memory carries for ever: cited facts
    plus any grouping they depend on, and the as-of. A record of past
    justification, never a live view."""
    cited = {fact.fact_id: fact for fact in pack.facts if fact.fact_id in proposal.cited_fact_ids}
    groupings = [
        grouping.model_dump(mode="json")
        for grouping in pack.groupings
        if grouping.group_id in proposal.grouping_ids
    ]
    return {
        "as_of": pack.as_of.isoformat(),
        "rules_version": pack.rules_version,
        "facts": [fact.model_dump(mode="json") for fact in cited.values()],
        "groupings": groupings,
    }


def apply_gate(
    reasoning: AdvisorReasoning,
    *,
    pack: EvidencePack,
    active: list[CareerMemory],
    dismissed: list[CareerMemory],
    run_id: uuid.UUID,
) -> GateOutcome:
    """Validate the reasoning output in the contract's order. Returns what may
    be persisted; raises `DispositionDefect` when the run itself is defective."""
    outcome = GateOutcome(creates=[], dispositions=[])
    facts_by_id = {fact.fact_id: fact for fact in pack.facts}

    surviving: list[PlannedCreate] = []
    for proposal in reasoning.created:
        planned = _gate_one_create(proposal, facts_by_id, dismissed, outcome, run_id)
        if planned is not None:
            surviving.append(planned)

    surviving = _reconcile_subjects(surviving, outcome, run_id)
    dispositions, staying = _validate_dispositions(
        reasoning, active, facts_by_id, surviving, outcome, run_id
    )
    surviving = _enforce_cap(surviving, staying, outcome, run_id)
    dispositions = _repair_orphaned_supersedes(dispositions, surviving, outcome, run_id)

    outcome.creates = surviving
    outcome.dispositions = dispositions
    return outcome


# -- creation-side gates, in contract order ---------------------------------


def _gate_one_create(
    proposal: ProposedMemory,
    facts_by_id: dict[str, EvidenceFact],
    dismissed: list[CareerMemory],
    outcome: GateOutcome,
    run_id: uuid.UUID,
) -> PlannedCreate | None:
    # 1. Citation existence — including the empty citation, refused outright.
    unknown = [cited for cited in proposal.cited_fact_ids if cited not in facts_by_id]
    if unknown or not proposal.cited_fact_ids:
        detail = f"unknown fact ids {unknown}" if unknown else "no facts cited"
        _discard(outcome, run_id, "citation", detail, proposal)
        return None
    cited = [facts_by_id[fact_id] for fact_id in proposal.cited_fact_ids]

    # 2. Numeral grounding: every digit in the claim exists in the cited facts.
    allowed = _allowed_numerals(cited)
    stray = [numeral for numeral in _NUMERAL.findall(proposal.claim) if numeral not in allowed]
    if stray:
        _discard(outcome, run_id, "numerals", f"{stray} not in cited evidence", proposal)
        return None

    # 2a. Denominator presence (G2): the claim states at least one cited
    # fact's numerator/denominator pair. A claim with no numbers at all fails
    # here rather than bypassing — it cannot state its denominator.
    if not any(
        f"{fact.numerator} of {fact.denominator}" in proposal.claim
        or f"{fact.numerator}/{fact.denominator}" in proposal.claim
        for fact in cited
    ):
        _discard(
            outcome,
            run_id,
            "denominator",
            "no cited numerator/denominator pair stated in the claim",
            proposal,
        )
        return None

    # 3. Causality.
    lowered = proposal.claim.lower()
    causal = [phrase for phrase in CAUSAL_PHRASES if phrase in lowered]
    if causal:
        _discard(outcome, run_id, "causality", f"causal phrasing {causal}", proposal)
        return None

    # 4. The floor forces tentative — the honest downgrade, never a refusal.
    tentative = proposal.tentative or any(fact.denominator < SMALL_SAMPLE_FLOOR for fact in cited)

    # 7. Dismissal (checked per create; the layer the prompt cannot guarantee).
    recreates: uuid.UUID | None = None
    for memory in dismissed:
        if memory.retired_reason != USER_DISMISSED:
            continue
        if (memory.kind, memory.scope_kind, memory.scope_value) != (
            proposal.kind,
            proposal.scope_kind,
            proposal.scope_value,
        ):
            continue
        if _evidence_tuples(cited) == _frozen_tuples(memory):
            _discard(
                outcome,
                run_id,
                "dismissal",
                f"recreates dismissed memory {memory.id} on unchanged evidence",
                proposal,
            )
            return None
        recreates = memory.id

    return PlannedCreate(proposal=proposal, tentative=tentative, recreates_dismissed_id=recreates)


def _allowed_numerals(cited: list[EvidenceFact]) -> set[str]:
    allowed: set[str] = set()
    for fact in cited:
        allowed.add(str(fact.numerator))
        allowed.add(str(fact.denominator))
        allowed.update(_NUMERAL.findall(fact.value))
        if fact.date_range:
            for endpoint in fact.date_range:
                allowed.add(str(endpoint.year))
    return allowed


def _evidence_tuples(cited: list[EvidenceFact]) -> set[tuple[str, int, int]]:
    return {(fact.fact_id, fact.numerator, fact.denominator) for fact in cited}


def _frozen_tuples(memory: CareerMemory) -> set[tuple[str, int, int]]:
    facts = memory.evidence.get("facts", []) if isinstance(memory.evidence, dict) else []
    return {
        (str(fact.get("fact_id")), int(fact.get("numerator", -1)), int(fact.get("denominator", -1)))
        for fact in facts
        if isinstance(fact, dict)
    }


def _reconcile_subjects(
    surviving: list[PlannedCreate], outcome: GateOutcome, run_id: uuid.UUID
) -> list[PlannedCreate]:
    """6. No two surviving creates on one subject: the higher priority wins
    (FR-016 — reconciliation before persistence, never two active
    contradictions)."""
    by_subject: dict[tuple[str, str, str | None], PlannedCreate] = {}
    for planned in surviving:
        key = (
            planned.proposal.kind,
            planned.proposal.scope_kind,
            planned.proposal.scope_value,
        )
        incumbent = by_subject.get(key)
        if incumbent is None:
            by_subject[key] = planned
            continue
        keep, drop = (
            (planned, incumbent)
            if (planned.proposal.priority or -1) > (incumbent.proposal.priority or -1)
            else (incumbent, planned)
        )
        by_subject[key] = keep
        _discard(outcome, run_id, "contradiction", f"duplicate subject {key}", drop.proposal)
    return [
        planned
        for planned in surviving
        if by_subject.get(
            (planned.proposal.kind, planned.proposal.scope_kind, planned.proposal.scope_value)
        )
        is planned
    ]


# -- dispositions (FR-013, invariant 1) --------------------------------------


def _validate_dispositions(
    reasoning: AdvisorReasoning,
    active: list[CareerMemory],
    facts_by_id: dict[str, EvidenceFact],
    surviving: list[PlannedCreate],
    outcome: GateOutcome,
    run_id: uuid.UUID,
) -> tuple[list[PlannedDisposition], int]:
    """5. Completeness: every active memory dispositioned exactly once, every
    disposition naming a real memory, every reason present where required.
    A shortfall raises — the run is defective, and nothing synthesises a
    disposition for a memory the model forgot."""
    active_ids = {memory.id for memory in active}
    seen: set[uuid.UUID] = set()
    planned: list[PlannedDisposition] = []

    for op in reasoning.dispositions:
        if op.memory_id not in active_ids:
            raise DispositionDefect(
                f"disposition names {op.memory_id}, which is not an active memory of this run"
            )
        if op.memory_id in seen:
            raise DispositionDefect(f"memory {op.memory_id} dispositioned twice")
        seen.add(op.memory_id)

        action = _ACTION_TO_RECORD.get(op.action)
        if action is None:
            raise DispositionDefect(f"unknown disposition action {op.action!r}")
        if op.action in ("retire", "leave_open") and not op.reason:
            raise DispositionDefect(
                f"{op.action} on {op.memory_id} states no reason — leaving a memory open "
                "is an explicit decision, and decisions say why"
            )
        superseding: int | None = None
        if op.action == "supersede":
            superseding = op.superseding_index
            if superseding is None or superseding >= len(reasoning.created):
                raise DispositionDefect(
                    f"supersede on {op.memory_id} points at no proposed creation"
                )

        delta: dict[str, Any] | None = None
        if op.action == "confirm":
            fresh = [
                facts_by_id[fact_id].model_dump(mode="json")
                for fact_id in op.fresh_fact_ids
                if fact_id in facts_by_id
            ]
            delta = {"facts": fresh} if fresh else None

        planned.append(
            PlannedDisposition(
                memory_id=op.memory_id,
                action=action,
                reason=op.reason,
                evidence_delta=delta,
                superseding_create=_surviving_index(reasoning, surviving, superseding),
            )
        )

    missing = active_ids - seen
    if missing:
        raise DispositionDefect(
            "these active memories were not dispositioned — an unaccounted-for memory is "
            f"a run defect, never a silent omission: {sorted(str(m) for m in missing)}"
        )

    staying = sum(1 for op in reasoning.dispositions if op.action in _STAYING_ACTIONS)
    return planned, staying


def _surviving_index(
    reasoning: AdvisorReasoning, surviving: list[PlannedCreate], proposed_index: int | None
) -> int | None:
    if proposed_index is None:
        return None
    target = reasoning.created[proposed_index]
    for index, planned in enumerate(surviving):
        if planned.proposal is target:
            return index
    return -1  # discarded — repaired in _repair_orphaned_supersedes


def _enforce_cap(
    surviving: list[PlannedCreate], staying: int, outcome: GateOutcome, run_id: uuid.UUID
) -> list[PlannedCreate]:
    """8. The cap, in the G4 order: creates count against the
    **post-disposition** active set, so an at-cap create-plus-retire is valid
    and ends at the cap."""
    room = ACTIVE_MEMORY_CAP - staying
    if len(surviving) <= room:
        return surviving
    ranked = sorted(surviving, key=lambda planned: planned.proposal.priority or -1, reverse=True)
    kept = ranked[: max(room, 0)]
    for planned in ranked[max(room, 0) :]:
        _discard(
            outcome,
            run_id,
            "cap",
            f"active set would exceed {ACTIVE_MEMORY_CAP}",
            planned.proposal,
        )
    kept_set = {id(planned) for planned in kept}
    return [planned for planned in surviving if id(planned) in kept_set]


def _repair_orphaned_supersedes(
    dispositions: list[PlannedDisposition],
    surviving: list[PlannedCreate],
    outcome: GateOutcome,
    run_id: uuid.UUID,
) -> list[PlannedDisposition]:
    """The documented downgrade: a supersede whose replacement was discarded
    becomes `left_open` with a machine-stated reason. The old memory stays
    active rather than being taken down by a claim that failed the gate."""
    repaired: list[PlannedDisposition] = []
    for planned in dispositions:
        index = planned.superseding_create
        if planned.action == DispositionAction.SUPERSEDED and (
            index is None or index < 0 or index >= len(surviving)
        ):
            logger.info(
                "advisor supersede downgraded",
                extra={
                    "run_id": str(run_id),
                    "gate": "supersede_orphan",
                    "detail": f"replacement for {planned.memory_id} was discarded",
                },
            )
            repaired.append(
                PlannedDisposition(
                    memory_id=planned.memory_id,
                    action=DispositionAction.LEFT_OPEN,
                    reason="the superseding claim was discarded by the grounding gate",
                    evidence_delta=None,
                )
            )
            continue
        repaired.append(planned)
    return repaired


def _discard(
    outcome: GateOutcome,
    run_id: uuid.UUID,
    gate: str,
    detail: str,
    proposal: ProposedMemory,
) -> None:
    outcome.discards.append(DiscardRecord(gate=gate, detail=detail, claim=proposal.claim))
    logger.info(
        "advisor insight discarded",
        extra={"run_id": str(run_id), "gate": gate, "detail": detail, "claim": proposal.claim},
    )


# -- grouping validation (T030, FR-007) --------------------------------------


def validate_grouping(
    proposal: GroupingProposal, *, known_ids: set[uuid.UUID], run_id: uuid.UUID
) -> tuple[list[EvidenceGrouping], int]:
    """The proposal is evidence, not truth: only groups whose every member is
    an id the prompt actually rendered survive, and an id may belong to one
    group per kind. Counting runs over survivors only — which is what keeps
    the model out of the arithmetic even when it invents a member.

    Returns the surviving groups (as the frozen `EvidenceGrouping` shape) and
    how many proposals were dropped, each drop recorded.
    """
    surviving: list[EvidenceGrouping] = []
    claimed: dict[str, set[uuid.UUID]] = {}
    dropped = 0

    for group in proposal.groups:
        unknown = [member for member in group.member_ids if member not in known_ids]
        already = claimed.setdefault(group.group_kind, set())
        overlap = [member for member in group.member_ids if member in already]
        if unknown or overlap or not group.member_ids:
            dropped += 1
            logger.info(
                "advisor grouping dropped",
                extra={
                    "run_id": str(run_id),
                    "gate": "grouping",
                    "detail": (
                        f"group {group.group_id!r}: "
                        + (f"unknown ids {unknown}" if unknown else f"overlapping ids {overlap}")
                    ),
                },
            )
            continue
        already.update(group.member_ids)
        surviving.append(
            EvidenceGrouping(
                group_id=group.group_id,
                label=group.label,
                group_kind=group.group_kind,
                member_ids=list(group.member_ids),
            )
        )

    return surviving, dropped
