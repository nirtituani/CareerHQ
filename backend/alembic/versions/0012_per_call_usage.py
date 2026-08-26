"""Per-call usage for a tailoring run (T092).

`tailoring_runs` sums a run's spend into three totals, and totals cannot answer
the question a real failure asked: run `cd27b092` was billed $0.36 across
several calls and the record could not say which node spent it, whether the
escalated revision ran, or what the call that failed had already cost. Each
`complete()` call is now its own row, written on the success **and** failure
paths — the calls a failed run made were billed whether or not the run
finished.

Two invariants live in the schema rather than in prose:

* **(run, sequence) is unique.** `_record_usage` can legitimately run twice for
  one run — a success that fails on the flush re-enters through the failure
  path — and it deletes before it inserts; this index is what catches the day
  that rule is broken, so a double-write cannot silently double the bill.
* **Every row names its task.** A label-less row answers nothing the totals do
  not already answer, so the schema refuses it.

Revision ID: 0012_per_call_usage
Revises: 0011_version_items_and_findings
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_per_call_usage"
down_revision: str | None = "0011_version_items_and_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tailoring_run_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tailoring_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tailoring_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The ordering column. A timestamp cannot serve: `func.now()` is
        # transaction-scoped, so every row written in one transaction would
        # carry the same instant.
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        # Numeric, never float. An audit value, not a display value.
        sa.Column("cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint("length(task) > 0", name="ck_tailoring_run_calls_task_named"),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name="ck_tailoring_run_calls_tokens_non_negative",
        ),
        sa.CheckConstraint("cost >= 0", name="ck_tailoring_run_calls_cost_non_negative"),
    )
    # Serves both invariance and lookup: unique on the pair, and its leading
    # column is the foreign key every read filters on.
    op.create_index(
        "uq_tailoring_run_calls_run_sequence",
        "tailoring_run_calls",
        ["tailoring_run_id", "sequence"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_tailoring_run_calls_run_sequence", table_name="tailoring_run_calls")
    op.drop_table("tailoring_run_calls")
