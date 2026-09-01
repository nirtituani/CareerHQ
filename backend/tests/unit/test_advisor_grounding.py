"""The grounding gate (T012/T030, spec FR-009/FR-010/FR-016/FR-016a/FR-021).

This is `finalisation_rules.py`'s discard-before-persistence applied to
statistics: a proposed insight the gate cannot verify never reaches a row.
Every refusal is recorded — asserted here on the records *this module*
emitted, filtered by logger name (testing rule 11) — and counted, so
*found-nothing* and *discarded-everything* stay different outcomes.

The cap check runs with the analyze-remediation G4 order: dispositions apply
conceptually first, creates are counted against the post-disposition active
set. The at-cap create-plus-retire case is the drill for the naive ordering.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pytest

from careerhq.application.advisor_grounding import (
    DispositionDefect,
    apply_gate,
)
from careerhq.application.advisor_rules import ACTIVE_MEMORY_CAP
from careerhq.domain.models import USER_DISMISSED, CareerMemory, MemoryStatus
from careerhq.domain.schemas.advisor import (
    AdvisorReasoning,
    EvidenceFact,
    EvidencePack,
    MemoryDispositionOp,
    ProposedMemory,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _fact(
    fact_id: str = "outcome.rejection_rate.global", num: int = 12, den: int = 20
) -> EvidenceFact:
    return EvidenceFact(
        fact_id=fact_id,
        kind="outcome",
        scope_kind="global",
        numerator=num,
        denominator=den,
        value=f"{num} of {den} applications ({round(100 * num / den)}%) ended rejected",
        record_ids=[uuid.uuid4()],
        basis="test fact",
    )


def _pack(*facts: EvidenceFact) -> EvidencePack:
    return EvidencePack(as_of=NOW, rules_version="v1-advisor", facts=list(facts))


def _proposal(
    claim: str = "12 of 20 applications ended rejected",
    *,
    cited: list[str] | None = None,
    kind: str = "outcome_pattern",
    scope_kind: str = "global",
    scope_value: str | None = None,
    priority: int | None = None,
    tentative: bool = False,
) -> ProposedMemory:
    return ProposedMemory(
        claim=claim,
        kind=kind,
        scope_kind=scope_kind,
        scope_value=scope_value,
        cited_fact_ids=cited if cited is not None else ["outcome.rejection_rate.global"],
        priority=priority,
        priority_reason="test priority" if priority is not None else None,
        tentative=tentative,
    )


def _memory(
    *,
    kind: str = "outcome_pattern",
    scope_kind: str = "global",
    scope_value: str | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    retired_reason: str | None = None,
    evidence: dict | None = None,  # type: ignore[type-arg]
) -> CareerMemory:
    memory = CareerMemory(
        user_id=uuid.uuid4(),
        advisor_run_id=uuid.uuid4(),
        claim="an existing claim over 12 of 20",
        kind=kind,
        scope_kind=scope_kind,
        scope_value=scope_value,
        evidence=evidence
        or {
            "facts": [
                {"fact_id": "outcome.rejection_rate.global", "numerator": 12, "denominator": 20}
            ]
        },
        status=status,
        retired_reason=retired_reason,
    )
    memory.id = uuid.uuid4()
    return memory


def _gate(reasoning: AdvisorReasoning, pack: EvidencePack, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("active", [])
    kwargs.setdefault("dismissed", [])
    kwargs.setdefault("run_id", uuid.uuid4())
    return apply_gate(reasoning, pack=pack, **kwargs)


# -- creation-side refusals --------------------------------------------------


def test_an_unknown_citation_is_discarded_and_recorded(caplog: pytest.LogCaptureFixture) -> None:
    reasoning = AdvisorReasoning(created=[_proposal(cited=["no.such.fact"])])
    with caplog.at_level(logging.INFO, logger="careerhq.application.advisor_grounding"):
        outcome = _gate(reasoning, _pack(_fact()))
    assert outcome.creates == []
    assert outcome.discarded == 1 and outcome.proposed == 1 and outcome.applied == 0
    records = [
        record
        for record in caplog.records
        if record.name == "careerhq.application.advisor_grounding"
    ]
    assert records, "the discard emitted no record from this module"
    assert any(getattr(record, "gate", None) == "citation" for record in records)


def test_a_claim_with_zero_citations_is_refused() -> None:
    outcome = _gate(AdvisorReasoning(created=[_proposal(cited=[])]), _pack(_fact()))
    assert outcome.creates == [] and outcome.discarded == 1


def test_a_digit_absent_from_cited_facts_is_discarded() -> None:
    reasoning = AdvisorReasoning(created=[_proposal(claim="17 of 20 applications ended rejected")])
    outcome = _gate(reasoning, _pack(_fact()))
    assert outcome.creates == []
    assert any(discard.gate == "numerals" for discard in outcome.discards)


def test_percentages_precomputed_in_the_fact_are_allowed() -> None:
    reasoning = AdvisorReasoning(
        created=[_proposal(claim="12 of 20 applications (60%) ended rejected")]
    )
    outcome = _gate(reasoning, _pack(_fact()))
    assert len(outcome.creates) == 1


def test_a_numberless_claim_fails_denominator_presence_not_bypasses_it() -> None:
    """G2: an evidence-backed claim that cannot state its denominator is not
    persisted — no numbers at all is a failure, not an exemption."""
    reasoning = AdvisorReasoning(
        created=[_proposal(claim="rejection is a recurring outcome for you")]
    )
    outcome = _gate(reasoning, _pack(_fact()))
    assert outcome.creates == []
    assert any(discard.gate == "denominator" for discard in outcome.discards)


def test_the_denominator_pair_may_read_n_of_m_or_n_slash_m() -> None:
    for claim in ("12 of 20 ended rejected", "12/20 ended rejected"):
        outcome = _gate(AdvisorReasoning(created=[_proposal(claim=claim)]), _pack(_fact()))
        assert len(outcome.creates) == 1, claim


def test_causal_language_is_refused() -> None:
    reasoning = AdvisorReasoning(
        created=[_proposal(claim="12 of 20 were rejected because your AWS gap leads to rejections")]
    )
    outcome = _gate(reasoning, _pack(_fact()))
    assert outcome.creates == []
    assert any(discard.gate == "causality" for discard in outcome.discards)


def test_a_small_denominator_forces_tentative_rather_than_refusing() -> None:
    """The honest downgrade: below the floor the claim persists as tentative
    even when the model said otherwise."""
    fact = _fact("tier2.gap.aws", num=3, den=4)
    reasoning = AdvisorReasoning(
        created=[
            _proposal(
                claim="3 of 4 analysed postings named AWS", cited=["tier2.gap.aws"], tentative=False
            )
        ]
    )
    outcome = _gate(reasoning, _pack(fact))
    assert len(outcome.creates) == 1
    assert outcome.creates[0].tentative is True


def test_two_creates_on_one_subject_keep_the_higher_priority() -> None:
    first = _proposal(claim="12 of 20 ended rejected", priority=80)
    second = _proposal(claim="12 of 20 ended rejected", priority=20)
    outcome = _gate(AdvisorReasoning(created=[first, second]), _pack(_fact()))
    assert len(outcome.creates) == 1
    assert outcome.creates[0].proposal.priority == 80
    assert any(discard.gate == "contradiction" for discard in outcome.discards)


# -- the cap, in the G4 evaluation order ------------------------------------


def _active_set(count: int) -> list[CareerMemory]:
    return [_memory(kind=f"kind_{index}", scope_kind="global") for index in range(count)]


def test_at_the_cap_a_create_plus_retire_is_valid() -> None:
    """G4's drill: dispositions apply first, so 25 active + 1 retire + 1
    create ends at 25 and the create survives. A naive pre-disposition count
    would wrongly discard it."""
    active = _active_set(ACTIVE_MEMORY_CAP)
    dispositions = [
        MemoryDispositionOp(
            memory_id=memory.id, action="confirm", fresh_fact_ids=["outcome.rejection_rate.global"]
        )
        for memory in active[:-1]
    ]
    dispositions.append(
        MemoryDispositionOp(memory_id=active[-1].id, action="retire", reason="no longer targeted")
    )
    reasoning = AdvisorReasoning(created=[_proposal()], dispositions=dispositions)
    outcome = _gate(reasoning, _pack(_fact()), active=active)
    assert len(outcome.creates) == 1, "the at-cap create+retire must survive"


def test_over_the_cap_the_excess_is_dropped_in_priority_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    active = _active_set(ACTIVE_MEMORY_CAP - 1)
    dispositions = [
        MemoryDispositionOp(
            memory_id=memory.id, action="confirm", fresh_fact_ids=["outcome.rejection_rate.global"]
        )
        for memory in active
    ]
    keeper = _proposal(claim="12 of 20 ended rejected", priority=90)
    dropped = _proposal(claim="12 of 20 ended rejected", kind="other_kind", priority=10)
    with caplog.at_level(logging.INFO, logger="careerhq.application.advisor_grounding"):
        outcome = _gate(
            AdvisorReasoning(created=[keeper, dropped], dispositions=dispositions),
            _pack(_fact()),
            active=active,
        )
    assert len(outcome.creates) == 1
    assert outcome.creates[0].proposal.priority == 90
    assert any(discard.gate == "cap" for discard in outcome.discards)


# -- dismissal (FR-021's deterministic layer) --------------------------------


def test_recreating_a_dismissed_claim_on_identical_evidence_is_refused() -> None:
    dismissed = _memory(
        status=MemoryStatus.RETIRED,
        retired_reason=USER_DISMISSED,
    )
    outcome = _gate(AdvisorReasoning(created=[_proposal()]), _pack(_fact()), dismissed=[dismissed])
    assert outcome.creates == []
    assert any(discard.gate == "dismissal" for discard in outcome.discards)


def test_materially_changed_evidence_recreates_with_the_history_visible() -> None:
    dismissed = _memory(status=MemoryStatus.RETIRED, retired_reason=USER_DISMISSED)
    changed = _fact(num=18, den=30)
    reasoning = AdvisorReasoning(created=[_proposal(claim="18 of 30 applications ended rejected")])
    outcome = _gate(reasoning, _pack(changed), dismissed=[dismissed])
    assert len(outcome.creates) == 1
    assert outcome.creates[0].recreates_dismissed_id == dismissed.id


# -- dispositions (invariant 1: left_open is never a default) ----------------


def test_an_omitted_active_memory_fails_the_run() -> None:
    """FR-013: unaccounted-for memories are a run defect. Nothing synthesises
    a disposition for a memory the model forgot."""
    active = [_memory(), _memory(kind="second")]
    reasoning = AdvisorReasoning(
        dispositions=[
            MemoryDispositionOp(
                memory_id=active[0].id,
                action="confirm",
                fresh_fact_ids=["outcome.rejection_rate.global"],
            )
        ],
        nothing_found_reason="nothing new",
    )
    with pytest.raises(DispositionDefect) as defect:
        _gate(reasoning, _pack(_fact()), active=active)
    assert str(active[1].id) in str(defect.value)


def test_a_disposition_for_a_memory_not_in_the_input_fails_the_run() -> None:
    active = [_memory()]
    stranger = uuid.uuid4()
    reasoning = AdvisorReasoning(
        dispositions=[
            MemoryDispositionOp(
                memory_id=active[0].id,
                action="confirm",
                fresh_fact_ids=["outcome.rejection_rate.global"],
            ),
            MemoryDispositionOp(memory_id=stranger, action="retire", reason="never existed"),
        ],
        nothing_found_reason="nothing new",
    )
    with pytest.raises(DispositionDefect):
        _gate(reasoning, _pack(_fact()), active=active)


def test_leave_open_maps_to_left_open_and_keeps_its_reason() -> None:
    """I1: the verb/participle translation lives here and only here."""
    active = [_memory()]
    reasoning = AdvisorReasoning(
        dispositions=[
            MemoryDispositionOp(
                memory_id=active[0].id,
                action="leave_open",
                reason="evidence is absent either way this run",
            )
        ],
        nothing_found_reason="nothing new",
    )
    outcome = _gate(reasoning, _pack(_fact()), active=active)
    planned = outcome.dispositions[0]
    assert planned.action == "left_open"
    assert planned.reason == "evidence is absent either way this run"


def test_leave_open_without_a_reason_fails_the_run() -> None:
    active = [_memory()]
    reasoning = AdvisorReasoning(
        dispositions=[
            MemoryDispositionOp(memory_id=active[0].id, action="leave_open", reason=None)
        ],
        nothing_found_reason="nothing new",
    )
    with pytest.raises(DispositionDefect):
        _gate(reasoning, _pack(_fact()), active=active)


# -- grouping validation (T030, FR-007) --------------------------------------


def _proposal_group(member_ids: list, group_id: str = "g1", kind: str = "skill"):  # type: ignore[no-untyped-def,type-arg]
    from careerhq.domain.schemas.advisor import GroupingProposal, ProposedGroup

    return GroupingProposal(
        groups=[
            ProposedGroup(group_id=group_id, label="AWS", group_kind=kind, member_ids=member_ids)
        ]
    )


def test_a_group_with_an_invented_id_is_dropped_and_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from careerhq.application.advisor_grounding import validate_grouping

    known = {uuid.uuid4(), uuid.uuid4()}
    stranger = uuid.uuid4()
    proposal = _proposal_group([next(iter(known)), stranger])
    with caplog.at_level(logging.INFO, logger="careerhq.application.advisor_grounding"):
        surviving, dropped = validate_grouping(proposal, known_ids=known, run_id=uuid.uuid4())
    assert surviving == []
    assert dropped == 1
    records = [r for r in caplog.records if r.name == "careerhq.application.advisor_grounding"]
    assert any(getattr(r, "gate", None) == "grouping" for r in records)


def test_an_id_in_two_groups_of_one_kind_keeps_only_the_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from careerhq.application.advisor_grounding import validate_grouping
    from careerhq.domain.schemas.advisor import GroupingProposal, ProposedGroup

    shared = uuid.uuid4()
    other = uuid.uuid4()
    proposal = GroupingProposal(
        groups=[
            ProposedGroup(
                group_id="g1", label="AWS", group_kind="skill", member_ids=[shared, other]
            ),
            ProposedGroup(group_id="g2", label="Amazon", group_kind="skill", member_ids=[shared]),
        ]
    )
    surviving, dropped = validate_grouping(proposal, known_ids={shared, other}, run_id=uuid.uuid4())
    assert [group.group_id for group in surviving] == ["g1"]
    assert dropped == 1


# -- B1/B2/B5 regressions (code review 2026-09-01, executed reproductions) ---


def test_b1_a_cap_drop_cannot_repoint_or_lose_a_supersede() -> None:
    """B1: the supersede->create link must survive the cap filter. 24 confirms
    + 1 supersede at the cap; creates [low-priority unrelated, replacement].
    The cap admits one create — it must be the replacement, still linked."""
    actives = [_memory(kind=f"k{i}") for i in range(24)]
    subject = _memory(kind="subject")
    unrelated = _proposal(kind="unrelated_a", priority=10)
    replacement = _proposal(kind="replacement_b", priority=90)
    dispositions = [
        MemoryDispositionOp(
            memory_id=m.id, action="confirm", fresh_fact_ids=["outcome.rejection_rate.global"]
        )
        for m in actives
    ]
    dispositions.append(
        MemoryDispositionOp(memory_id=subject.id, action="supersede", superseding_index=1)
    )
    outcome = _gate(
        AdvisorReasoning(created=[unrelated, replacement], dispositions=dispositions),
        _pack(_fact()),
        active=[*actives, subject],
    )
    sup = next(d for d in outcome.dispositions if d.memory_id == subject.id)
    assert str(sup.action) == "superseded", "a valid supersede must not be downgraded by the cap"
    assert sup.superseding_create is not None
    assert outcome.creates[sup.superseding_create].proposal.kind == "replacement_b", (
        "the link must resolve to the replacement, never a shifted neighbour"
    )


def test_b2_an_orphaned_supersede_cannot_breach_the_cap() -> None:
    """B2: at 25 active, a supersede whose replacement was discarded returns
    its memory to the active set — the cap must be evaluated against that,
    ending at <= 25, not 26."""
    actives = [_memory(kind=f"c{i}") for i in range(24)]
    subject = _memory(kind="subject8")
    replacement = _proposal(
        kind="replacement_r", priority=50, claim="17 of 99 fabricated"
    )  # fails numerals
    newcomer = _proposal(kind="new_n", priority=40)
    dispositions = [
        MemoryDispositionOp(
            memory_id=m.id, action="confirm", fresh_fact_ids=["outcome.rejection_rate.global"]
        )
        for m in actives
    ]
    dispositions.append(
        MemoryDispositionOp(memory_id=subject.id, action="supersede", superseding_index=0)
    )
    outcome = _gate(
        AdvisorReasoning(created=[replacement, newcomer], dispositions=dispositions),
        _pack(_fact()),
        active=[*actives, subject],
    )
    subject_action = next(d for d in outcome.dispositions if d.memory_id == subject.id).action
    staying = sum(1 for d in outcome.dispositions if str(d.action) in ("confirmed", "left_open"))
    final_active = staying + len(outcome.creates)
    assert final_active <= ACTIVE_MEMORY_CAP, (
        f"{final_active} active after the run (subject was {subject_action}) — FR-016a breached"
    )


def test_b5_a_stray_reason_on_confirm_is_normalised_not_fatal() -> None:
    """B5a: models routinely justify optional fields; a reason on confirm or
    supersede must be absorbed by the gate, never reach
    ck_memory_disposition_reason and fail the billed run."""
    active = [_memory()]
    reasoning = AdvisorReasoning(
        dispositions=[
            MemoryDispositionOp(
                memory_id=active[0].id,
                action="confirm",
                reason="looks fine to me",
                fresh_fact_ids=["outcome.rejection_rate.global"],
            )
        ],
        nothing_found_reason="n",
    )
    outcome = _gate(reasoning, _pack(_fact()), active=active)
    assert outcome.dispositions[0].reason is None, (
        "confirmed/superseded rows must carry NULL reason — the DB CHECK is a biconditional"
    )


def test_b5_scope_shapes_are_repaired_or_discarded_never_crashed() -> None:
    """B5b: (scope_kind='global') = (scope_value IS NULL) is a DB CHECK. A
    global claim with a stray value is repairable (drop the value); a scoped
    claim with no value is not (discard, recorded) — neither may reach the
    constraint and destroy the run."""
    global_with_value = _proposal(kind="g1", scope_kind="global", scope_value=None).model_copy(
        update={"scope_value": "AWS"}
    )
    scoped_without_value = _proposal(kind="g2", scope_kind="skill", scope_value=None)
    outcome = _gate(
        AdvisorReasoning(created=[global_with_value, scoped_without_value]),
        _pack(_fact()),
    )
    assert len(outcome.creates) == 1
    kept = outcome.creates[0].proposal
    assert kept.kind == "g1" and kept.scope_value is None, "the stray value is dropped"
    assert any(d.gate == "scope" for d in outcome.discards), (
        "the unrepairable shape is discarded with the gate named"
    )
