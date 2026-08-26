"""Resume versions and the runs that produce them.

Slice 005. Two tables that reference each other, which is why the foreign key
from `resume_versions` to `tailoring_runs` is added separately at the end.

**The circularity is deliberate, not an accident of modelling.** A version
points at the run that produced it, because `docs/03` line 273 makes the
workflow reference a property of the version. A run points back at its version,
because the reaper has to find abandoned work without scanning every version in
the table. One of the two has to be added after both tables exist.

**The constraint is named.** An unnamed `use_alter` foreign key cannot be
dropped, which breaks `drop_all` outright against an existing database — slice
004 hit exactly that when it added its first one.

The partial unique index is FR-004: at most one tailoring run in flight per
application, enforced where two clicks cannot race it.

Revision ID: 0010_resume_versions
Revises: 0009_match_dimensions
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_resume_versions"
down_revision: str | None = "0009_match_dimensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("professional_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_resume_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resume_profiles.id"),
            nullable=False,
        ),
        sa.Column("source_profile_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("professional_title", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        # Added at the end, once tailoring_runs exists.
        sa.Column("tailoring_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'tailoring', 'reviewing', 'awaiting_approval', 'ready')",
            name="ck_resume_versions_status",
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR confidence_score BETWEEN 0 AND 100",
            name="ck_resume_versions_confidence_range",
        ),
    )
    op.create_index("ix_resume_versions_profile_id", "resume_versions", ["profile_id"])
    op.create_index("ix_resume_versions_application_id", "resume_versions", ["application_id"])

    # FR-004. Partial, so a job may accumulate many finished versions but only
    # ever have one run in flight.
    op.create_index(
        "uq_resume_versions_one_in_flight_per_application",
        "resume_versions",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('tailoring', 'reviewing')"),
    )

    op.create_table(
        "tailoring_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "resume_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resume_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Read, never written. FR-011.
        sa.Column(
            "match_analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("match_analyses.id"),
            nullable=False,
        ),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("guidelines_used", postgresql.JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finalisation_rules_version", sa.String(32), nullable=False),
        sa.Column("model_config_used", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'abandoned')",
            name="ck_tailoring_runs_status",
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 2", name="ck_tailoring_runs_attempts"),
    )
    op.create_index("ix_tailoring_runs_resume_version_id", "tailoring_runs", ["resume_version_id"])

    # The second half of the cycle, now that both tables exist. Named, so that
    # it can be dropped again.
    op.create_foreign_key(
        "fk_resume_versions_tailoring_run",
        "resume_versions",
        "tailoring_runs",
        ["tailoring_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # The cycle has to be broken before either table can go.
    op.drop_constraint("fk_resume_versions_tailoring_run", "resume_versions", type_="foreignkey")
    op.drop_index("ix_tailoring_runs_resume_version_id", table_name="tailoring_runs")
    op.drop_table("tailoring_runs")
    op.drop_index("uq_resume_versions_one_in_flight_per_application", table_name="resume_versions")
    op.drop_index("ix_resume_versions_application_id", table_name="resume_versions")
    op.drop_index("ix_resume_versions_profile_id", table_name="resume_versions")
    op.drop_table("resume_versions")
