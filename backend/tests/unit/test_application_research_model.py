"""ApplicationResearchSnapshot — the slice 010 reshape, asserted (T004).

The reshape's contract, each clause from data-model.md: application-scoped, no
Layer 1 lineage, `sections` not `findings`, `produced_by` and `cost_basis`
present and constrained, immutability still enforced by absence, and the
one-running-per-application guard carried over under its new name.

Asserted against the mapped metadata, the same way `test_research_models.py`
does — these are claims about the schema, not about a session.
"""

from __future__ import annotations

from careerhq.domain.models import ApplicationResearchSnapshot, ResearchSource
from careerhq.infrastructure.database import Base

TABLE = "application_research_snapshots"


def _table() -> object:
    return Base.metadata.tables[TABLE]


def test_the_reshaped_table_is_registered_and_the_old_name_is_gone() -> None:
    assert TABLE in Base.metadata.tables
    assert "role_research_snapshots" not in Base.metadata.tables
    assert ApplicationResearchSnapshot.__tablename__ == TABLE


def test_application_scoped_and_owned() -> None:
    table = _table()
    fks = {fk.column.table.name for fk in table.c.application_id.foreign_keys} | {
        fk.column.table.name for fk in table.c.user_id.foreign_keys
    }
    assert fks == {"applications", "users"}
    assert table.c.application_id.nullable is False
    assert table.c.user_id.nullable is False


def test_the_layer_one_lineage_column_is_gone() -> None:
    """D2: the snapshot IS the whole research; a vestigial lineage column would
    be permanently unanswerable for every new row."""
    assert "company_research_snapshot_id" not in _table().c


def test_sections_replaces_findings() -> None:
    table = _table()
    assert "sections" in table.c
    assert "findings" not in table.c
    assert table.c.sections.nullable is False


def test_produced_by_and_cost_basis_are_required() -> None:
    table = _table()
    assert table.c.produced_by.nullable is False
    assert table.c.cost_basis.nullable is False


def test_cost_basis_is_constrained_to_its_two_values() -> None:
    checks = {c.name: str(c.sqltext) for c in _table().constraints if hasattr(c, "sqltext")}
    basis = checks.get("ck_application_research_snapshots_cost_basis", "")
    assert "recorded" in basis and "estimate" in basis


def test_immutability_is_still_enforced_by_absence() -> None:
    assert "updated_at" not in _table().c


def test_one_running_per_application_guard_carried_over() -> None:
    names = {index.name for index in _table().indexes}
    assert "uq_application_research_one_running_per_application" in names
    guard = next(
        index
        for index in _table().indexes
        if index.name == "uq_application_research_one_running_per_application"
    )
    assert guard.unique


def test_sources_reference_the_reshaped_table() -> None:
    sources = Base.metadata.tables["research_sources"]
    assert "application_snapshot_id" in sources.c
    assert "role_snapshot_id" not in sources.c
    targets = {fk.column.table.name for fk in sources.c.application_snapshot_id.foreign_keys}
    assert targets == {TABLE}
    checks = {c.name: str(c.sqltext) for c in sources.constraints if hasattr(c, "sqltext")}
    ownership = checks.get("ck_research_sources_exactly_one_snapshot", "")
    assert "application_snapshot_id" in ownership
    # The relationship the routes will selectinload — a lazy access on a fresh
    # object raises MissingGreenlet, so its existence is part of the contract.
    assert hasattr(ApplicationResearchSnapshot, "sources")
    assert hasattr(ResearchSource, "application_snapshot")
