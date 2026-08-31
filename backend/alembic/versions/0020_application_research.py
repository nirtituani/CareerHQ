"""Reshape the empty Layer 2 table into application_research_snapshots.

Slice 010 (research.md D2). `role_research_snapshots` was declared by 0019 as
storage for a Layer 2 that was never wired to a route, so the table is empty on
every deployment that ever ran — and **the migration proves that instead of
assuming it**: the emptiness guard below refuses to reshape a table holding
rows, because rewriting even one would be exactly the history-rewriting that
Principle IV forbids. `tests/integration/test_migration_0020.py` watches the
guard fail.

The reshape, in one place: rename the table; drop the mandatory Layer 1
lineage column (there is no Layer 1 underneath any more — the snapshot is the
whole research); rename `findings` → `sections`; add `produced_by` and
`cost_basis`; carry every constraint and index over under names matching the
new table, so nothing half-renamed survives to confuse a later autogenerate.
`research_sources` follows: `role_snapshot_id` → `application_snapshot_id`,
and the exactly-one-owner check is **rewritten by hand** — Alembic does not
diff check constraints, so leaving it would keep the old column name in a
constraint the column no longer has.

Adding NOT NULL columns without server defaults is safe here for the same
reason the reshape is: the guard has already proven there are no rows to
violate them.

Revision ID: 0020_application_research
Revises: 0019_company_research
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020_application_research"
down_revision: str | None = "0019_company_research"
branch_labels: str | None = None
depends_on: str | None = None


def _refuse_unless_empty(table: str) -> None:
    # The two callers pass literal table names from this file; nothing
    # user-supplied can reach here. Quoted as an identifier regardless, which
    # also satisfies the linter's injection rule for the right reason.
    quoted = '"' + table.replace('"', "") + '"'
    count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {quoted}")).scalar()  # noqa: S608
    if count:
        raise RuntimeError(
            f"{table} holds {count} row(s); this migration reshapes it in place and is "
            "only legitimate against the empty table the never-wired Layer 2 left behind. "
            "A populated table means something undocumented wrote to it — stop and look."
        )


def upgrade() -> None:
    _refuse_unless_empty("role_research_snapshots")

    # -- research_sources: detach everything that names the old column -------
    op.drop_index("uq_research_sources_role_snapshot_source_id", table_name="research_sources")
    op.drop_constraint(
        "ck_research_sources_exactly_one_snapshot", "research_sources", type_="check"
    )
    op.drop_constraint(
        "research_sources_role_snapshot_id_fkey", "research_sources", type_="foreignkey"
    )
    op.alter_column(
        "research_sources", "role_snapshot_id", new_column_name="application_snapshot_id"
    )

    # -- the snapshot table: reshape in place --------------------------------
    op.drop_index(
        "uq_role_research_one_running_per_application", table_name="role_research_snapshots"
    )
    op.drop_index("ix_role_research_snapshots_application", table_name="role_research_snapshots")
    for check in ("status", "tokens_non_negative", "cost_non_negative"):
        op.drop_constraint(
            f"ck_role_research_snapshots_{check}", "role_research_snapshots", type_="check"
        )
    op.drop_constraint(
        "role_research_snapshots_company_research_snapshot_id_fkey",
        "role_research_snapshots",
        type_="foreignkey",
    )
    op.drop_column("role_research_snapshots", "company_research_snapshot_id")

    op.rename_table("role_research_snapshots", "application_research_snapshots")
    op.alter_column("application_research_snapshots", "findings", new_column_name="sections")
    op.add_column(
        "application_research_snapshots",
        sa.Column("produced_by", sa.String(32), nullable=False),
    )
    op.add_column(
        "application_research_snapshots",
        sa.Column("cost_basis", sa.String(16), nullable=False),
    )

    # Names the rename does not touch, renamed so the schema reads as one
    # table rather than as a rename's residue.
    op.execute(
        "ALTER INDEX role_research_snapshots_pkey RENAME TO application_research_snapshots_pkey"
    )
    op.execute(
        "ALTER TABLE application_research_snapshots RENAME CONSTRAINT "
        "role_research_snapshots_user_id_fkey TO application_research_snapshots_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE application_research_snapshots RENAME CONSTRAINT "
        "role_research_snapshots_application_id_fkey "
        "TO application_research_snapshots_application_id_fkey"
    )

    op.create_check_constraint(
        "ck_application_research_snapshots_status",
        "application_research_snapshots",
        "status IN ('running', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_application_research_snapshots_tokens_non_negative",
        "application_research_snapshots",
        "input_tokens >= 0 AND output_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_application_research_snapshots_cost_non_negative",
        "application_research_snapshots",
        "cost >= 0",
    )
    op.create_check_constraint(
        "ck_application_research_snapshots_cost_basis",
        "application_research_snapshots",
        "cost_basis IN ('recorded', 'estimate')",
    )
    op.create_index(
        "ix_application_research_snapshots_application",
        "application_research_snapshots",
        ["application_id"],
    )
    op.create_index(
        "uq_application_research_one_running_per_application",
        "application_research_snapshots",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    # -- research_sources: reattach to the reshaped table --------------------
    op.create_foreign_key(
        "research_sources_application_snapshot_id_fkey",
        "research_sources",
        "application_research_snapshots",
        ["application_snapshot_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_research_sources_exactly_one_snapshot",
        "research_sources",
        "(company_snapshot_id IS NOT NULL) <> (application_snapshot_id IS NOT NULL)",
    )
    op.create_index(
        "uq_research_sources_application_snapshot_source_id",
        "research_sources",
        ["application_snapshot_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("application_snapshot_id IS NOT NULL"),
    )


def downgrade() -> None:
    # The same honesty in reverse: rows written under the new shape cannot be
    # given the mandatory Layer 1 lineage the old shape demands, so a populated
    # table refuses rather than inventing one.
    _refuse_unless_empty("application_research_snapshots")

    op.drop_index(
        "uq_research_sources_application_snapshot_source_id", table_name="research_sources"
    )
    op.drop_constraint(
        "ck_research_sources_exactly_one_snapshot", "research_sources", type_="check"
    )
    op.drop_constraint(
        "research_sources_application_snapshot_id_fkey", "research_sources", type_="foreignkey"
    )
    op.alter_column(
        "research_sources", "application_snapshot_id", new_column_name="role_snapshot_id"
    )

    op.drop_index(
        "uq_application_research_one_running_per_application",
        table_name="application_research_snapshots",
    )
    op.drop_index(
        "ix_application_research_snapshots_application",
        table_name="application_research_snapshots",
    )
    for check in ("status", "tokens_non_negative", "cost_non_negative", "cost_basis"):
        op.drop_constraint(
            f"ck_application_research_snapshots_{check}",
            "application_research_snapshots",
            type_="check",
        )
    op.drop_column("application_research_snapshots", "produced_by")
    op.drop_column("application_research_snapshots", "cost_basis")

    op.alter_column("application_research_snapshots", "sections", new_column_name="findings")
    op.rename_table("application_research_snapshots", "role_research_snapshots")
    op.execute(
        "ALTER INDEX application_research_snapshots_pkey RENAME TO role_research_snapshots_pkey"
    )
    op.execute(
        "ALTER TABLE role_research_snapshots RENAME CONSTRAINT "
        "application_research_snapshots_user_id_fkey TO role_research_snapshots_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE role_research_snapshots RENAME CONSTRAINT "
        "application_research_snapshots_application_id_fkey "
        "TO role_research_snapshots_application_id_fkey"
    )

    op.add_column(
        "role_research_snapshots",
        sa.Column("company_research_snapshot_id", sa.dialects.postgresql.UUID(), nullable=False),
    )
    op.create_foreign_key(
        "role_research_snapshots_company_research_snapshot_id_fkey",
        "role_research_snapshots",
        "company_research_snapshots",
        ["company_research_snapshot_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_role_research_snapshots_status",
        "role_research_snapshots",
        "status IN ('running', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_role_research_snapshots_tokens_non_negative",
        "role_research_snapshots",
        "input_tokens >= 0 AND output_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_role_research_snapshots_cost_non_negative",
        "role_research_snapshots",
        "cost >= 0",
    )
    op.create_index(
        "ix_role_research_snapshots_application",
        "role_research_snapshots",
        ["application_id"],
    )
    op.create_index(
        "uq_role_research_one_running_per_application",
        "role_research_snapshots",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_research_sources_role_snapshot_source_id",
        "research_sources",
        ["role_snapshot_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("role_snapshot_id IS NOT NULL"),
    )
