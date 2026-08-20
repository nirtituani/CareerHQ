"""Match analysis: append-only runs, grounded requirements, and the R1 correction.

Slice 004 (T011). Two tables and two columns on `applications`.

**The grounding CHECK is the point of this migration.** Read it as an
equivalence in both directions: every verdict except `unverified` must quote the
profile, including `gap`, which has to point at the text showing the shortfall.
A model that cannot quote anything does not get to say the person falls short —
the honest verdict is then `unverified`, the sole evidence-free one because it
is the only one that asserts nothing. That is AI-008 made true of the table
rather than true of the code that usually writes to it.

**`applications.requirements` is deliberately left NULL on existing rows.** It
is not backfilled with an empty array, and that is not an oversight. Before this
slice, `job_description` held the extracted requirements joined by newlines and
the posting body was discarded — so for an existing row there is no posting to
recover, and no heuristic can tell a stored requirements list from a terse
advert. NULL marks "no posting was ever captured" and those rows are never
scored; `{}` marks "the posting was read and stated no requirements". Collapsing
them would silently reinstate requirements-only scoring, and the resulting
number would look entirely normal (research.md R1).

Revision ID: 0006_match_analysis
Revises: 0005_applications
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_match_analysis"
down_revision: str | None = "0005_applications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_analyses",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("application_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("overall_score", sa.SmallInteger(), nullable=True),
        sa.Column("band", sa.String(length=16), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        # NOT NULL from the first insert: nullable would make a forgotten value
        # indistinguishable from a deliberate one, and a calibration
        # measurement across scores from different unnamed criteria measures
        # nothing (FR-018).
        sa.Column("criteria_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        # Decimal, never float — an audit value accumulated over thousands of runs.
        sa.Column("cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_match_analyses_application_id"), "match_analyses", ["application_id"])
    # FR-007, enforced where it cannot be raced. Partial, so a *finished*
    # analysis never blocks a re-run — without the WHERE clause every
    # application would be scoreable exactly once.
    op.create_index(
        "uq_match_analysis_one_pending_per_application",
        "match_analyses",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "match_requirements",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("shortfall", sa.String(length=16), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(verdict = 'unverified') = (evidence IS NULL)",
            name="ck_match_requirement_grounded",
        ),
        sa.CheckConstraint(
            "(verdict = 'confirmed') = (shortfall IS NULL)",
            name="ck_match_requirement_shortfall",
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["match_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_match_requirements_analysis_id"), "match_requirements", ["analysis_id"]
    )

    op.add_column(
        "applications",
        sa.Column("requirements", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("current_match_analysis_id", sa.UUID(), nullable=True),
    )
    # Added after both tables exist, because it closes a cycle. Named, because
    # an unnamed altered constraint cannot be dropped.
    op.create_foreign_key(
        "fk_applications_current_match_analysis_id",
        "applications",
        "match_analyses",
        ["current_match_analysis_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_applications_current_match_analysis_id", "applications", type_="foreignkey"
    )
    op.drop_column("applications", "current_match_analysis_id")
    op.drop_column("applications", "requirements")
    op.drop_index(op.f("ix_match_requirements_analysis_id"), table_name="match_requirements")
    op.drop_table("match_requirements")
    op.drop_index("uq_match_analysis_one_pending_per_application", table_name="match_analyses")
    op.drop_index(op.f("ix_match_analyses_application_id"), table_name="match_analyses")
    op.drop_table("match_analyses")
