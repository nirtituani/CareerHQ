"""Applications, companies, and insert-only status history.

User Story 2 (T066). Carries constraints **C2** and **C3** from data-model.md §4,
both as database constraints rather than application checks: C2 is what makes
company dedup correct under a concurrent import retry, and C3 is what makes
re-running an import conflict instead of silently duplicating.

Two absences here are deliberate and are asserted by tests rather than left to
memory — there is no `rejected` column (FR-016) and no `submitted_resume_id`
(FR-011, slice 004).

Revision ID: 0005_applications
Revises: 0004_service_volunteering
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_applications"
down_revision: str | None = "0004_service_volunteering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("careers_url", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # C2 — FR-014. Scoped to the user: companies carry that person's own
        # notes and contacts, so they are not a shared directory.
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_companies_user_normalized_name"),
    )
    op.create_index("ix_companies_user_id", "companies", ["user_id"])

    op.create_table(
        "applications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("job_url", sa.String(length=2048), nullable=True),
        sa.Column("job_description_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("normalized_status", sa.String(length=16), nullable=False),
        sa.Column(
            "date_added",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("date_applied", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("salary_text", sa.String(length=255), nullable=True),
        sa.Column("imported_match_rating", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("import_source", sa.String(length=64), nullable=True),
        sa.Column("import_source_id", sa.String(length=255), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # RESTRICT, not CASCADE: deleting a company must not silently take the
        # applications recorded against it with it.
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_user_id", "applications", ["user_id"])
    op.create_index("ix_applications_company_id", "applications", ["company_id"])

    # C3 — FR-017. Partial, because manual entries have no import identity;
    # without the WHERE clause their NULLs would neither conflict nor be
    # constrained, and a plain UNIQUE would not express the rule at all.
    op.create_index(
        "uq_applications_import_identity",
        "applications",
        ["user_id", "import_source", "import_source_id"],
        unique=True,
        postgresql_where=sa.text("import_source IS NOT NULL"),
    )

    op.create_table(
        "application_status_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("application_id", sa.UUID(), nullable=False),
        # NULL on the row written at creation — there was no previous status.
        sa.Column("from_status", sa.String(length=64), nullable=True),
        sa.Column("to_status", sa.String(length=64), nullable=False),
        sa.Column("normalized_to_status", sa.String(length=16), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_status_history_application_id",
        "application_status_history",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_table("application_status_history")
    op.drop_index("uq_applications_import_identity", table_name="applications")
    op.drop_table("applications")
    op.drop_table("companies")
