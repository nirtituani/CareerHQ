"""Per-pass review observability (T093).

One nullable column: `tailoring_runs.review_confidences`, every review pass's
confidence in pass order as a JSONB array. The graph state keeps only the
latest confidence — the conditional edge and the final score both mean "the
current draft" — so without a persisted record the first pass's judgement of a
revised run is destroyed before anything can read it.

`reviewer_findings.attempt` already exists (0011) and is untouched here: the
fix for its stamping is in code, where the review node now pairs each finding
with the pass that raised it instead of `run_tailoring` stamping the run's
final attempt on every row.

**No backfill, deliberately.** The runs that predate this migration keep NULL:
their per-pass values were overwritten in state before persistence, and
reconstructing them — from `confidence_score`, from `attempts`, from anything —
would present inference as record. NULL means unknowable, never zero
(HANDOFF §2a).

**Chained onto 0012 at merge time.** This was written in a parallel worktree
from the same base as 0012, so both briefly declared 0011 as their parent; the
chain was linearised when the branches were merged. Nothing about either
migration's content depends on the order — 0012 creates a table, this adds a
column to another — so the sequence is bookkeeping, not a dependency.

Revision ID: 0013_review_passes
Revises: 0012_per_call_usage
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_review_passes"
down_revision: str | None = "0012_per_call_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tailoring_runs",
        sa.Column("review_confidences", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tailoring_runs", "review_confidences")
