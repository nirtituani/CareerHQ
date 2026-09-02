"""Every stored advisor value the contract exposes reaches the API (T039).

The suite has never once caught a display bug — a fixture only contains the
fields whoever wrote it thought to include, so it cannot catch an omission.
This test reads the models' **own columns** (the `test_profile_content.py`
mechanism) and requires each to appear in the route serialisers, so a column
added to the model without a line in `_memory_out`/`_run_out` fails here
rather than shipping invisible.

Columns that are deliberately internal are whitelisted **with the reason**,
and the whitelist is part of the contract: growing it is a reviewed decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from careerhq.api.routes.advisor import _memory_out, _run_out
from careerhq.domain.models import (
    AdvisorRun,
    AdvisorRunStatus,
    CareerMemory,
    MemoryStatus,
)

#: Not exposed, and why. `user_id` — ownership comes from the session and
#: echoing it back discloses nothing useful. `advisor_run_id` — the audit
#: anchor, reachable through the memory's disposition history rather than
#: duplicated onto every card.
_MEMORY_INTERNAL = {"user_id", "advisor_run_id"}
#: `user_id` — as above. `evidence_pack` — the run's whole pack is an
#: operator/audit artefact; the page reads each memory's frozen subset.
_RUN_INTERNAL = {"user_id", "evidence_pack"}

#: Columns whose API spelling differs from the column name — the mapping is
#: asserted, not assumed.
_MEMORY_RENAMES = {"scope_kind": "scope", "scope_value": "scope"}
_RUN_RENAMES = {
    "ops_proposed": "ops",
    "ops_applied": "ops",
    "ops_discarded": "ops",
    "grouping_model": "models",
    "reason_model": "models",
}


def _flatten(payload: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.add(key)
            keys |= _flatten(value)
    return keys


def test_every_memory_column_reaches_the_page() -> None:
    memory = CareerMemory(
        user_id=uuid.uuid4(),
        advisor_run_id=uuid.uuid4(),
        claim="c",
        kind="k",
        scope_kind="global",
        evidence={"facts": []},
        status=MemoryStatus.ACTIVE,
    )
    memory.id = uuid.uuid4()
    memory.created_at = datetime.now(UTC)
    memory.last_confirmed_at = datetime.now(UTC)

    exposed = _flatten(_memory_out(memory))
    columns = set(CareerMemory.__table__.columns.keys())
    assert len(columns) >= 16, f"examined only {len(columns)} columns"

    missing = [
        column
        for column in columns
        if column not in _MEMORY_INTERNAL
        and column not in exposed
        and _MEMORY_RENAMES.get(column, column) not in exposed
    ]
    assert not missing, f"stored but never shown: {missing}"


def test_every_run_column_reaches_the_poll() -> None:
    run = AdvisorRun(
        user_id=uuid.uuid4(),
        status=AdvisorRunStatus.READY,
        rules_version="v1-advisor",
        dispositions=[],
        cost=Decimal("0.01"),
        ops_proposed=1,
        ops_applied=1,
        ops_discarded=0,
    )
    run.id = uuid.uuid4()
    run.created_at = datetime.now(UTC)

    exposed = _flatten(_run_out(run, include_dispositions=True))
    columns = set(AdvisorRun.__table__.columns.keys())
    assert len(columns) >= 15, f"examined only {len(columns)} columns"

    missing = [
        column
        for column in columns
        if column not in _RUN_INTERNAL
        and column not in exposed
        and _RUN_RENAMES.get(column, column) not in exposed
    ]
    assert not missing, f"stored but never shown: {missing}"


def test_the_derived_tier_fields_reach_the_page() -> None:
    """The refinement slice adds read-time derived fields; they must reach the
    API, not just be computed (the suite has never caught a display bug)."""
    import uuid as _uuid
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    memory = CareerMemory(
        user_id=_uuid.uuid4(),
        advisor_run_id=_uuid.uuid4(),
        claim="AWS was a gap in 4 of 5 analysed postings",
        kind="recurring_gap",
        scope_kind="skill",
        scope_value="AWS",
        evidence={
            "facts": [
                {
                    "fact_id": "tier2.requirement.g1",
                    "scope_value": "AWS",
                    "numerator": 5,
                    "denominator": 7,
                },
                {"fact_id": "tier2.gap.g1", "scope_value": "AWS", "numerator": 4, "denominator": 7},
            ]
        },
        status=MemoryStatus.ACTIVE,
    )
    memory.id = _uuid.uuid4()
    memory.created_at = _dt.now(_UTC)
    memory.last_confirmed_at = _dt.now(_UTC)

    out = _memory_out(memory)
    for field in ("tier", "section", "topic", "counts", "action"):
        assert field in out, f"derived field {field} never reaches the API"
    assert out["tier"] == "recommendation"
    assert out["section"] == "recommended"
    assert out["topic"] == "AWS"
    assert out["counts"] == {"occurrences": 5, "coverage": 7, "gaps": 4}
    assert out["action"] is not None
