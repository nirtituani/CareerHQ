"""The reasoning-prompt renderer (T014, extended by T024/T036).

The prompt is the reasoning step's entire world: facts it may cite, memories
it must disposition, dismissals it must not recreate. These tests read the
rendered text the way the model would — by marker — and every set assertion
also asserts its size, because a marker that stopped rendering would
otherwise pass every membership check vacuously.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from careerhq.application.advise_career import render_reasoning_prompt
from careerhq.application.advisor_evidence import build_evidence_pack
from careerhq.domain.models import USER_DISMISSED, CareerMemory, MemoryStatus
from tests.unit.test_advisor_evidence import _sample  # the seeded Tier 1 rows

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

_FACT_LINE = re.compile(r"^\[fact: (?P<fact_id>[^\]]+)\] .*n=(?P<num>\d+)/(?P<den>\d+)", re.M)
_MEMORY_LINE = re.compile(r"^\[memory: (?P<id>[0-9a-f-]{36})\]", re.M)
_DISMISSED_LINE = re.compile(r"^\[dismissed: (?P<id>[0-9a-f-]{36})\]", re.M)


def _memory(
    *, status: MemoryStatus = MemoryStatus.ACTIVE, retired_reason: str | None = None
) -> CareerMemory:
    memory = CareerMemory(
        user_id=uuid.uuid4(),
        advisor_run_id=uuid.uuid4(),
        claim="2 of 5 applications ended rejected",
        kind="outcome_pattern",
        scope_kind="global",
        evidence={
            "facts": [
                {"fact_id": "outcome.rejection_rate.global", "numerator": 2, "denominator": 5}
            ]
        },
        status=status,
        retired_reason=retired_reason,
    )
    memory.id = uuid.uuid4()
    memory.created_at = NOW
    memory.last_confirmed_at = NOW
    return memory


def test_every_fact_line_traces_to_a_pack_fact_and_all_are_rendered() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    prompt = render_reasoning_prompt(pack=pack, active=[], dismissed=[])

    rendered = {match.group("fact_id"): match for match in _FACT_LINE.finditer(prompt)}
    pack_ids = {fact.fact_id for fact in pack.facts}
    assert set(rendered) == pack_ids
    assert len(rendered) == len(pack.facts) and len(rendered) >= 6

    by_id = {fact.fact_id: fact for fact in pack.facts}
    for fact_id, match in rendered.items():
        fact = by_id[fact_id]
        assert int(match.group("num")) == fact.numerator
        assert int(match.group("den")) == fact.denominator


def test_the_rules_block_never_instructs_a_distribution() -> None:
    """ "Most real profiles are mostly partial" made a model comply — never
    tell a model how its answers should be distributed."""
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    prompt = render_reasoning_prompt(pack=pack, active=[], dismissed=[])
    for rule_word in ("floor of 5", "25", "denominator"):
        assert rule_word in prompt
    assert not re.search(r"most (users|runs|memories|profiles)", prompt, re.I)


def test_active_and_tentative_render_as_memory_lines_and_terminal_rows_do_not() -> None:
    """G3/FR-014: only active+tentative are the prior state. The absence is
    asserted against the [memory:] marker specifically — dismissed rows
    legitimately appear via [dismissed:] — and the line count must equal the
    active+tentative count, so an empty section cannot pass vacuously."""
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    active = [_memory(), _memory(status=MemoryStatus.TENTATIVE)]
    superseded = _memory(status=MemoryStatus.SUPERSEDED)
    retired = _memory(status=MemoryStatus.RETIRED, retired_reason="no longer relevant")
    dismissed = _memory(status=MemoryStatus.RETIRED, retired_reason=USER_DISMISSED)

    prompt = render_reasoning_prompt(
        pack=pack, active=active, dismissed=[dismissed], history=[superseded, retired]
    )

    memory_ids = {match.group("id") for match in _MEMORY_LINE.finditer(prompt)}
    assert memory_ids == {str(memory.id) for memory in active}
    assert len(memory_ids) == 2

    for terminal in (superseded, retired):
        assert str(terminal.id) not in memory_ids
        assert f"[memory: {terminal.id}]" not in prompt

    dismissed_ids = {match.group("id") for match in _DISMISSED_LINE.finditer(prompt)}
    assert dismissed_ids == {str(dismissed.id)}
    assert "dismissed by the user" in prompt and "do not recreate" in prompt


def test_memory_lines_carry_claim_and_frozen_figures() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    memory = _memory()
    prompt = render_reasoning_prompt(pack=pack, active=[memory], dismissed=[])
    line = next(line for line in prompt.splitlines() if line.startswith(f"[memory: {memory.id}]"))
    assert memory.claim in line
    assert "active" in line and "outcome_pattern" in line
