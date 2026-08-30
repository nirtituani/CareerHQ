"""The persistence shape of company research (slice 008, plan.md §8 step 1).

These tests read `Base.metadata` rather than a live database, deliberately: they
assert what the schema **declares**, which is what makes `0019` safe to
autogenerate from. What the database actually **enforces** is a separate claim
and is proved separately, by
`tests/integration/test_research_persistence.py` handing PostgreSQL rows it must
refuse. Both are needed: a `CheckConstraint` can be correct here, absent from the
database, and green through every gate until the first real write — Alembic does
not diff check constraints, which is how slice 006's T005 nearly shipped a
constraint permitting only the five slice-005 statuses.

**Four invariants, and each is enforced by an absence.** Slice 003's
`rejected`-column lesson applies to every one of them: an invariant enforced by
something *not* being there has nothing to catch its return, so each test below
was watched failing before it passed.

* **FR-021 — Layer 1 is role-independent.** `company_research_snapshots` carries
  no column through which a job, role or application could arrive. This is the
  same guarantee `domain/schemas/research.py` makes about the completion, made
  again at the storage layer, because a snapshot that could name an application
  would eventually be shaped by one — and the reuse in `plan.md` §6 would stop
  being sound.
* **FR-010 — a snapshot is immutable.** No `updated_at` on any of the three
  tables. `plan.md` §5 states the absence *is* the enforcement.
* **FR-023 — Layer 2 records its lineage.** `company_research_snapshot_id` is
  not nullable: a role brief that cannot say which company brief it rests on
  cannot be aged, and FR-023 asks exactly that question.
* **FR-018 — ownership comes from the session.** Both snapshot tables carry
  `user_id`, cascading, like every other owned row in this system.

**Every test that asserts an absence also asserts how many columns it
examined.** A gate with nothing to examine passes forever, and this project has
shipped that failure four times.
"""

from __future__ import annotations

import warnings

import pytest
from sqlalchemy import Table
from sqlalchemy.exc import SAWarning

from careerhq.infrastructure.database import Base

#: The three tables plan.md §5 specifies. Named here rather than discovered so a
#: table silently failing to register is a failure rather than an empty loop.
RESEARCH_TABLES = (
    "company_research_snapshots",
    "role_research_snapshots",
    "research_sources",
)


def _table(name: str) -> Table:
    table = Base.metadata.tables.get(name)
    assert table is not None, (
        f"{name} is not registered in Base.metadata. A mapped class that is never "
        "imported does not exist as far as the schema is concerned."
    )
    return table


@pytest.mark.parametrize("name", RESEARCH_TABLES)
def test_the_three_research_tables_are_registered(name: str) -> None:
    _table(name)


def test_all_three_tables_registered_and_none_extra() -> None:
    """The count is the part that catches a rename."""
    present = {n for n in Base.metadata.tables if "research" in n and "knowledge" not in n}
    assert present == set(RESEARCH_TABLES), (
        f"expected exactly {sorted(RESEARCH_TABLES)}, found {sorted(present)}"
    )


# -- FR-021: Layer 1 cannot be shaped by a role -----------------------------

#: Substrings that would betray a job reaching Layer 1. `role` is included even
#: though it reads generic: `role_research_snapshot_id` on a *Layer 1* row would
#: invert the lineage and is exactly the mistake this guards.
ROLE_BEARING = ("application", "job", "role", "posting", "requirement", "vacancy")


def test_layer_one_carries_no_column_a_job_could_arrive_through() -> None:
    """FR-021, at the storage layer.

    Drilled by adding `application_id` to `CompanyResearchSnapshot`; this named
    it exactly.
    """
    table = _table("company_research_snapshots")
    columns = list(table.columns.keys())

    # A gate with nothing to examine passes forever.
    assert len(columns) >= 10, (
        f"examined only {len(columns)} columns on company_research_snapshots; "
        "that is too few for the table plan.md §5 specifies, so this gate is "
        "probably looking at the wrong thing"
    )

    offenders = [c for c in columns if any(word in c.lower() for word in ROLE_BEARING)]
    assert offenders == [], (
        f"company_research_snapshots carries {offenders}, through which a role could "
        "reach Layer 1. Layer 1 must read identically for two different jobs at the "
        "same employer (FR-021) — that belongs on role_research_snapshots."
    )


def test_layer_one_has_no_foreign_key_to_applications() -> None:
    """The same rule as above, asked of the foreign keys rather than the names."""
    table = _table("company_research_snapshots")
    targets = {fk.column.table.name for fk in table.foreign_keys}
    assert len(targets) >= 2, f"examined only {len(targets)} FK targets: {targets}"
    assert "applications" not in targets, (
        "company_research_snapshots references applications; FR-021 forbids Layer 1 "
        "from being scoped to a job"
    )


# -- FR-010: a snapshot is immutable ----------------------------------------


@pytest.mark.parametrize("name", RESEARCH_TABLES)
def test_no_research_table_has_an_updated_at(name: str) -> None:
    """FR-010. `plan.md` §5: "No `updated_at` […] The absence is the enforcement."

    Drilled by adding `updated_at` to each of the three in turn.
    """
    table = _table(name)
    columns = list(table.columns.keys())
    assert len(columns) >= 5, f"examined only {len(columns)} columns on {name}"
    assert "updated_at" not in columns, (
        f"{name} has updated_at. A snapshot is immutable once written (FR-010): "
        "re-running research writes a new row and leaves every earlier one intact "
        "(FR-011). A column that records mutation invites one."
    )


@pytest.mark.parametrize("name", RESEARCH_TABLES)
def test_every_research_table_records_when_it_was_retrieved(name: str) -> None:
    """FR-012, and per-source because a run spans time (plan.md §5)."""
    assert "retrieved_at" in _table(name).columns, (
        f"{name} has no retrieved_at. An immutable snapshot with no timestamp cannot "
        "be aged, and both the reuse window and the staleness window (OQ-E) need it."
    )


# -- FR-018: ownership comes from the session -------------------------------


@pytest.mark.parametrize("name", ("company_research_snapshots", "role_research_snapshots"))
def test_both_snapshot_tables_are_owned_and_cascade(name: str) -> None:
    table = _table(name)
    assert "user_id" in table.columns, f"{name} has no user_id (FR-018)"
    user_fks = [fk for fk in table.foreign_keys if fk.column.table.name == "users"]
    assert len(user_fks) == 1, f"expected exactly one FK to users on {name}, found {len(user_fks)}"
    assert user_fks[0].ondelete == "CASCADE", (
        f"{name}.user_id must cascade — deleting a user must not strand their research"
    )


# -- FR-023: Layer 2 records the Layer 1 it rests on ------------------------


def test_layer_two_lineage_is_not_nullable() -> None:
    """FR-023.

    Drilled by making the column nullable; this named it.
    """
    table = _table("role_research_snapshots")
    lineage = table.columns["company_research_snapshot_id"]
    assert not lineage.nullable, (
        "role_research_snapshots.company_research_snapshot_id is nullable. FR-023 "
        "requires Layer 2 to record which Layer 1 snapshot it rests on — and "
        "therefore how old that was. A nullable column makes that unanswerable."
    )


def test_layer_two_is_meaningless_without_an_application() -> None:
    table = _table("role_research_snapshots")
    assert not table.columns["application_id"].nullable, (
        "role_research_snapshots.application_id is nullable, but Layer 2 without a "
        "job has nothing to be role-specific about (FR-022)"
    )


# -- FR-012: the audit record Principle V requires ---------------------------

AUDIT_COLUMNS = ("model_config_used", "prompt_version", "input_tokens", "output_tokens", "cost")


@pytest.mark.parametrize("name", ("company_research_snapshots", "role_research_snapshots"))
def test_both_snapshot_tables_carry_the_audit_record(name: str) -> None:
    """FR-012 and Principle V. Slice 007 compares like with like using these."""
    columns = _table(name).columns
    missing = [c for c in AUDIT_COLUMNS if c not in columns]
    assert missing == [], f"{name} is missing audit columns {missing} (FR-012, Principle V)"


@pytest.mark.parametrize("name", ("company_research_snapshots", "role_research_snapshots"))
def test_a_failed_run_is_a_recorded_run(name: str) -> None:
    """plan.md §5: "a failed run is a recorded run, not an absent one"."""
    columns = _table(name).columns
    assert "status" in columns and "failure_reason" in columns, (
        f"{name} cannot record a failure; a run that vanishes on failure reports $0 "
        "spent and looks free"
    )


# -- FR-009 / FR-017: a source that could not be read is still recorded ------


def test_a_source_records_whether_it_was_actually_retrieved() -> None:
    """FR-009 (failed) and FR-017 (refused) are different outcomes and stay apart."""
    table = _table("research_sources")
    assert "fetch_status" in table.columns, (
        "research_sources has no fetch_status. A source that could not be retrieved "
        "shall be recorded as attempted-and-failed, not omitted (FR-009)"
    )
    constraints = {
        c.name: str(c.sqltext)  # type: ignore[attr-defined]
        for c in table.constraints
        if type(c).__name__ == "CheckConstraint"
    }
    assert constraints, "research_sources declares no check constraint on fetch_status"
    vocabulary = " ".join(constraints.values())
    for value in ("retrieved", "failed", "refused"):
        assert value in vocabulary, (
            f"fetch_status cannot be {value!r}. FR-009 (failed) and FR-017 (refused) "
            "are different outcomes: one is a network fact, the other a decision."
        )


def test_sources_belong_to_a_snapshot_and_cascade() -> None:
    table = _table("research_sources")
    fks = list(table.foreign_keys)
    assert len(fks) >= 1, "research_sources has no foreign key to a snapshot"
    assert all(fk.ondelete == "CASCADE" for fk in fks), (
        "research_sources must cascade from its snapshot — an excerpt outliving the "
        "claim it supports is unreachable evidence"
    )


def test_every_source_carries_the_excerpt_the_verbatim_check_needs() -> None:
    """FR-008 and FR-032. The excerpt is what defeats citation laundering."""
    columns = _table("research_sources").columns
    for required in ("url", "title", "excerpt", "retrieved_at"):
        assert required in columns, f"research_sources has no {required} (FR-008)"


# -- FR-014: the pointer to a company's current research ---------------------


def test_companies_points_at_its_current_research_snapshot() -> None:
    """FR-014. Written only on success, so a failed re-run does not blank a
    good result — slice 005's T093 lesson, designed in from the start."""
    pointer = Base.metadata.tables["companies"].columns.get("current_research_snapshot_id")
    assert pointer is not None, (
        "companies has no current_research_snapshot_id. FR-014 requires a pointer to "
        "the current snapshot for a company."
    )
    assert pointer.nullable, (
        "the pointer must be nullable — a company that has never been researched is "
        "the normal case, not an error"
    )


def test_the_pointer_does_not_delete_the_company_with_the_snapshot() -> None:
    """A snapshot is subordinate to the company, never the reverse."""
    table = Base.metadata.tables["companies"]
    fks = [fk for fk in table.foreign_keys if fk.column.table.name == "company_research_snapshots"]
    assert len(fks) == 1, f"expected one FK to company_research_snapshots, found {len(fks)}"
    assert fks[0].ondelete == "SET NULL", (
        "companies.current_research_snapshot_id must be SET NULL on delete. CASCADE "
        "would delete the employer when its research is deleted."
    )


def test_the_circular_foreign_key_is_named_so_it_can_be_dropped() -> None:
    """`companies` and `company_research_snapshots` reference each other, so the
    pointer needs `use_alter=True` — and CLAUDE.md records the trap: **a
    `use_alter` foreign key must be named, or it cannot be dropped.** An
    unnamed one makes the migration that creates it irreversible.

    Drilled by removing the name; this named it.
    """
    table = Base.metadata.tables["companies"]
    fks = [
        fk.constraint
        for fk in table.foreign_keys
        if fk.column.table.name == "company_research_snapshots"
    ]
    assert len(fks) == 1
    constraint = fks[0]
    assert getattr(constraint, "use_alter", False), (
        "the pointer must set use_alter=True; without it the two tables form a "
        "dependency cycle and create_all cannot order them"
    )
    assert constraint.name, (
        "the use_alter foreign key has no name and therefore cannot be dropped — the "
        "downgrade of the migration that creates it would fail"
    )


def test_the_schema_can_still_be_ordered_for_creation() -> None:
    """The cycle above is only safe if metadata can still sort.

    **This assertion has to be made against the warning, not against an
    exception.** The first version of this test was `assert
    Base.metadata.sorted_tables` — and the drill proved it could not fail:
    removing `use_alter` leaves SQLAlchemy *warning* `"Cannot correctly sort
    tables; there are unresolvable cycles"` and returning a list anyway, so a
    truthiness check passes over a schema whose foreign keys have been silently
    dropped from consideration. That is this project's fifth encounter with a
    gate that had nothing to examine, and it was caught only because the drill
    was run.

    `filterwarnings("error")` is what turns SQLAlchemy's advisory into the
    failure it deserves to be. Note the library's own text: "this warning may
    raise an error in a future release" — until it does, the escalation is ours
    to make.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        ordered = Base.metadata.sorted_tables

    assert len(ordered) >= 20, (
        f"sorted only {len(ordered)} tables; this gate is looking at the wrong metadata"
    )
