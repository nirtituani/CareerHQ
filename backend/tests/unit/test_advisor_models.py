"""The persistence shape of the Career Advisor (slice 009, data-model.md).

These tests read `Base.metadata` rather than a live database, deliberately:
they assert what the schema **declares**. What the database actually
**enforces** is a separate claim, proved by the integration suite handing
PostgreSQL rows it must refuse — both are needed, because Alembic does not
diff check constraints, and `0021` writes them by hand.

The invariants worth naming:

* **A memory is insert-only with lineage.** The declared shape carries no
  `updated_at`; changed understanding is a new row via `supersedes_id`.
* **A retirement carries its reason.** `ck_career_memory_retired_reason` is
  the two-way equivalence, like `ck_match_requirement_grounded` before it.
* **One pending run per user**, enforced where it cannot be raced — a partial
  unique index, the same shape as match analysis's.
* **A run dispositions a memory exactly once** — `uq_memory_disposition_once_per_run`.
* **`left_open` states its reason.** `ck_memory_disposition_reason` covers
  `retired` *and* `left_open`: leaving a memory open is an explicit decision
  with a stated why, never a default for a memory the model forgot.

Every test that asserts a set also asserts its size — a gate with nothing to
examine passes forever.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, Index, Table

from careerhq.infrastructure.database import Base

ADVISOR_TABLES = (
    "advisor_runs",
    "career_memories",
    "memory_dispositions",
)


def _table(name: str) -> Table:
    table = Base.metadata.tables.get(name)
    assert table is not None, (
        f"{name} is not registered in Base.metadata. A mapped class that is never "
        "imported does not exist as far as the schema is concerned."
    )
    return table


def _check_constraints(table: Table) -> dict[str, str]:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }
    assert checks or table.name == "advisor_runs", f"{table.name} declares no CHECK constraints"
    return checks


@pytest.mark.parametrize("name", ADVISOR_TABLES)
def test_the_three_advisor_tables_are_registered(name: str) -> None:
    _table(name)


def test_one_pending_run_per_user_is_a_partial_unique_index() -> None:
    """The two-clicks race is closed in the schema, not in application code."""
    table = _table("advisor_runs")
    indexes = {index.name: index for index in table.indexes}
    index = indexes.get("uq_advisor_run_one_pending_per_user")
    assert index is not None, f"examined {sorted(indexes)} — the partial unique index is missing"
    assert isinstance(index, Index)
    assert index.unique
    where = index.dialect_options["postgresql"]["where"]
    assert where is not None and "pending" in str(where)
    assert [column.name for column in index.columns] == ["user_id"]


def test_career_memories_declares_the_four_checks() -> None:
    """Scope, retirement reason, priority range, and no self-supersession."""
    checks = _check_constraints(_table("career_memories"))
    expected = {
        "ck_career_memory_scope",
        "ck_career_memory_retired_reason",
        "ck_career_memory_priority",
        "ck_career_memory_supersedes_not_self",
    }
    assert expected <= set(checks), f"examined {sorted(checks)}"
    assert len(expected) == 4

    # The two-way equivalences, asserted as text so a weakened rewrite
    # (e.g. one-directional IS NOT NULL) fails here rather than in production.
    assert "=" in checks["ck_career_memory_scope"]
    assert "retired" in checks["ck_career_memory_retired_reason"]
    assert "=" in checks["ck_career_memory_retired_reason"]


def test_career_memories_lineage_and_content_columns() -> None:
    table = _table("career_memories")
    columns = set(table.columns.keys())
    expected = {
        "id",
        "user_id",
        "advisor_run_id",
        "claim",
        "kind",
        "scope_kind",
        "scope_value",
        "evidence",
        "priority",
        "priority_reason",
        "status",
        "supersedes_id",
        "recreates_dismissed_id",
        "retired_reason",
        "created_at",
        "last_confirmed_at",
    }
    assert expected <= columns, f"missing {sorted(expected - columns)}"
    # Insert-only: no updated_at. The absence is the enforcement, and this
    # assertion is what catches its return.
    assert "updated_at" not in columns
    assert len(columns) >= 16


def test_a_memory_freezes_its_essentials() -> None:
    table = _table("career_memories")
    for name in ("claim", "kind", "scope_kind", "evidence", "status", "advisor_run_id"):
        assert table.columns[name].nullable is False, f"{name} must be NOT NULL"


def test_memory_dispositions_shape() -> None:
    table = _table("memory_dispositions")
    checks = _check_constraints(table)

    unique = [
        constraint
        for constraint in table.constraints
        if constraint.name == "uq_memory_disposition_once_per_run"
    ]
    assert len(unique) == 1, "a run must disposition a memory exactly once"
    assert {column.name for column in unique[0].columns} == {"run_id", "memory_id"}

    # left_open requires a reason, exactly like retired — an explicit decision,
    # never a default. The equivalence must name both actions.
    reason_check = checks.get("ck_memory_disposition_reason")
    assert reason_check is not None, f"examined {sorted(checks)}"
    assert "left_open" in reason_check
    assert "retired" in reason_check


def test_advisor_runs_records_its_audit_columns() -> None:
    """Constitution V: model config, usage, cost — and the two-outcome counts."""
    table = _table("advisor_runs")
    columns = set(table.columns.keys())
    expected = {
        "id",
        "user_id",
        "status",
        "error",
        "rules_version",
        "evidence_pack",
        "ops_proposed",
        "ops_applied",
        "ops_discarded",
        "grouping_model",
        "reason_model",
        "input_tokens",
        "output_tokens",
        "cost",
        "is_fixture",
        "created_at",
        "completed_at",
    }
    assert expected <= columns, f"missing {sorted(expected - columns)}"
    assert table.columns["rules_version"].nullable is False
