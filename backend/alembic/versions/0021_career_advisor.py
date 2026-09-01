"""The Career Advisor's three tables: runs, memories, dispositions.

Slice 009 (data-model.md). Purely additive — no existing table is touched.

**Every CHECK constraint here is written by hand and named**, because Alembic
does not diff check constraints: a constraint that exists in Python and not in
the database passes every gate and fails at the first real write (the slice
006 near-miss). `tests/unit/test_advisor_models.py` asserts what the schema
declares; the integration suite hands PostgreSQL rows it must refuse, which is
what proves the two agree.

The one index that is not an optimisation:
`uq_advisor_run_one_pending_per_user` is the FR-001 invariant — at most one
run in flight per user — enforced where it cannot be raced.

Revision ID: 0021_career_advisor
Revises: 0020_application_research
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_career_advisor"
down_revision: str | None = "0020_application_research"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "advisor_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("rules_version", sa.String(32), nullable=False),
        sa.Column("evidence_pack", postgresql.JSONB(), nullable=True),
        sa.Column("ops_proposed", sa.SmallInteger(), nullable=True),
        sa.Column("ops_applied", sa.SmallInteger(), nullable=True),
        sa.Column("ops_discarded", sa.SmallInteger(), nullable=True),
        sa.Column("grouping_model", sa.String(128), nullable=True),
        sa.Column("reason_model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_advisor_runs_user_id", "advisor_runs", ["user_id"])
    op.create_index(
        "uq_advisor_run_one_pending_per_user",
        "advisor_runs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "career_memories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "advisor_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("advisor_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("scope_kind", sa.String(32), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=True),
        sa.Column("priority_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "supersedes_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("career_memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recreates_dismissed_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("career_memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("retired_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(scope_kind = 'global') = (scope_value IS NULL)",
            name="ck_career_memory_scope",
        ),
        sa.CheckConstraint(
            "(status = 'retired') = (retired_reason IS NOT NULL)",
            name="ck_career_memory_retired_reason",
        ),
        sa.CheckConstraint(
            "priority IS NULL OR priority BETWEEN 0 AND 100",
            name="ck_career_memory_priority",
        ),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_career_memory_supersedes_not_self",
        ),
    )
    op.create_index("ix_career_memories_user_id", "career_memories", ["user_id"])

    op.create_table(
        "memory_dispositions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("advisor_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("career_memories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_delta", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("run_id", "memory_id", name="uq_memory_disposition_once_per_run"),
        sa.CheckConstraint(
            "(action IN ('retired', 'left_open')) = (reason IS NOT NULL)",
            name="ck_memory_disposition_reason",
        ),
    )
    op.create_index("ix_memory_dispositions_run_id", "memory_dispositions", ["run_id"])
    op.create_index("ix_memory_dispositions_memory_id", "memory_dispositions", ["memory_id"])


def downgrade() -> None:
    op.drop_table("memory_dispositions")
    op.drop_table("career_memories")
    op.drop_table("advisor_runs")
