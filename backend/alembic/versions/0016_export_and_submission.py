"""Export and submission: two statuses and two records (T005).

`VersionStatus` gains `EXPORTED` and `SUBMITTED` — the two values migration
`0010`'s own docstring reserved for this slice — and the two tables that give
them something to mean: `exported_documents` (a rendered PDF) and
`submitted_resumes` (what was actually sent, insert-only).

**Autogenerate did not see the status change, and would not have.** It detected
both new tables correctly and proposed **nothing** for
`ck_resume_versions_status`, which still permits only the five slice-005 values.
Alembic does not diff check constraints; the plugin loads, logs, and finds
nothing. Had this file been the generated one, `alembic upgrade head` would have
succeeded, `mypy` and the suite would have stayed green, and the first real
export would have failed at run time with an integrity error naming a constraint
nobody had touched — a widened enum in Python that the database still refuses.
The drop-and-recreate below is written by hand for that reason.

**`READY`, not `APPROVED`.** `data-model.md` draws the lifecycle with an
`APPROVED` state; the value has been `ready` since `0010` and the rename is
declined — it would rewrite rows that are this project's only paid evaluation
evidence in exchange for agreeing with a document. The constraint therefore
keeps `ready` and appends the two new values. Noted in `VersionStatus`.

**The downgrade can legitimately fail, and must.** Restoring the narrow
constraint while a version sits at `exported` or `submitted` is refused by
PostgreSQL. That is the correct outcome: the alternative is a migration that
quietly rewrites the record of a document a person sent to an employer. Move
those rows back deliberately, or do not downgrade.

**The column is `document_storage_key`, not `storage_key`.** `data-model.md`
names it `storage_key`; that word already belongs to `imported_resumes` — the
uploaded CV — and `test_the_uploaded_file_is_read_by_exactly_one_module` finds
readers of the upload by attribute name. Adding a third table with the same
column name failed that gate immediately, and the only other way to satisfy it
was to add `domain/models/tailoring.py` to its allow-list, blinding it inside a
growing file forever. Renaming keeps the gate exact. Free to do here because
nothing has been written to these tables yet.

`submitted_resumes` uses `ondelete="RESTRICT"` on both foreign keys where the
rest of this schema uses `CASCADE`. Deliberate: Constitution IV requires an
application in `Applied` or later to be able to show what it sent, so deleting
the version or the application out from under a submission must be refused
rather than silently take the evidence with it.

Revision ID: 0016_export_and_submission
Revises: 0015_knowledge_corpus
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_export_and_submission"
down_revision: str | None = "0015_knowledge_corpus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than derived from `VersionStatus`. A migration records
#: what the schema became on this date; reading the enum would let a later slice
#: retroactively change what this one did.
_STATUSES_BEFORE = "'draft', 'tailoring', 'reviewing', 'awaiting_approval', 'ready'"
_STATUSES_AFTER = f"{_STATUSES_BEFORE}, 'exported', 'submitted'"


def upgrade() -> None:
    op.drop_constraint("ck_resume_versions_status", "resume_versions", type_="check")
    op.create_check_constraint(
        "ck_resume_versions_status", "resume_versions", f"status IN ({_STATUSES_AFTER})"
    )

    op.create_table(
        "exported_documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("resume_version_id", sa.UUID(), nullable=False),
        sa.Column("document_storage_key", sa.String(length=512), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "exported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # A checksum is a fixed-width lowercase hex digest or it is not a
        # checksum. FR-021 re-verifies it before a submission is written, which
        # is a comparison only if what was stored has a known shape.
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_exported_documents_checksum_hex"
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_exported_documents_byte_size"),
        sa.ForeignKeyConstraint(["resume_version_id"], ["resume_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_exported_documents_resume_version_id", "exported_documents", ["resume_version_id"]
    )

    op.create_table(
        "submitted_resumes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("resume_version_id", sa.UUID(), nullable=False),
        sa.Column("application_id", sa.UUID(), nullable=False),
        sa.Column("document_storage_key", sa.String(length=512), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_submitted_resumes_checksum_hex"
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_submitted_resumes_byte_size"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resume_version_id"], ["resume_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # One submission per version. A second send is a new version (FR-025),
        # not a second row against the old one — in the schema, because two
        # clicks can race an application-level check.
        sa.UniqueConstraint("resume_version_id"),
    )
    op.create_index("ix_submitted_resumes_application_id", "submitted_resumes", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_submitted_resumes_application_id", table_name="submitted_resumes")
    op.drop_table("submitted_resumes")
    op.drop_index("ix_exported_documents_resume_version_id", table_name="exported_documents")
    op.drop_table("exported_documents")

    # Refused by PostgreSQL if any version has reached `exported` or
    # `submitted`. See the module docstring: that failure is the point.
    op.drop_constraint("ck_resume_versions_status", "resume_versions", type_="check")
    op.create_check_constraint(
        "ck_resume_versions_status", "resume_versions", f"status IN ({_STATUSES_BEFORE})"
    )
