"""What a tailored version holds, and what the Reviewer objected to.

Slice 005. Split from 0010 because these depend on its tables existing, and
because a partial failure is diagnosable when the two halves are separate.

**Three check constraints carry rules that would otherwise live only in prose:**

* An `ungrounded` finding must quote the words it objects to. Without it, the
  model can assert an absence it cannot support — the same fabrication AI-008
  forbids, pointed the other way. Slice 004 learned this when a single
  evidence-free verdict let a silent profile become a confident "you do not have
  this".
* An `uncovered` finding must carry no item. There is no item for an unaddressed
  requirement to attach to, and manufacturing one repeats slice 004's
  `unverified`-shortfall mistake: demanding a structured field the model has no
  honest basis to fill.
* `decision` is a closed set, because approval routes on it.

Revision ID: 0011_version_items_and_findings
Revises: 0010_resume_versions
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_version_items_and_findings"
down_revision: str | None = "0010_resume_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_version_items",
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
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        # Copied, not referenced. FR-031 and Principle IV require a version not
        # to change when the profile does; a reference would make an approved
        # diff mutate underneath it. The copy is the lineage snapshot.
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("proposed_text", sa.Text(), nullable=True),
        # Materialised rather than derived, so no reader re-implements the rule.
        sa.Column("final_text", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "decision IN ('pending', 'accepted', 'rejected', 'edited')",
            name="ck_resume_version_items_decision",
        ),
    )
    op.create_index(
        "ix_resume_version_items_resume_version_id", "resume_version_items", ["resume_version_id"]
    )
    op.create_index(
        "uq_resume_version_items_source",
        "resume_version_items",
        ["resume_version_id", "source_kind", "source_item_id"],
        unique=True,
        postgresql_where=sa.text("source_item_id IS NOT NULL"),
    )

    op.create_table(
        "reviewer_findings",
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
        sa.Column(
            "resume_version_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resume_version_items.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("quoted_text", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "kind IN ('ungrounded', 'overstated', 'uncovered')",
            name="ck_reviewer_findings_kind",
        ),
        sa.CheckConstraint(
            "kind <> 'ungrounded' OR (quoted_text IS NOT NULL AND length(quoted_text) > 0)",
            name="ck_reviewer_findings_ungrounded_quotes",
        ),
        sa.CheckConstraint(
            "kind <> 'uncovered' OR resume_version_item_id IS NULL",
            name="ck_reviewer_findings_uncovered_has_no_item",
        ),
    )
    op.create_index(
        "ix_reviewer_findings_tailoring_run_id", "reviewer_findings", ["tailoring_run_id"]
    )
    op.create_index(
        "ix_reviewer_findings_resume_version_item_id",
        "reviewer_findings",
        ["resume_version_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reviewer_findings_resume_version_item_id", table_name="reviewer_findings")
    op.drop_index("ix_reviewer_findings_tailoring_run_id", table_name="reviewer_findings")
    op.drop_table("reviewer_findings")
    op.drop_index("uq_resume_version_items_source", table_name="resume_version_items")
    op.drop_index("ix_resume_version_items_resume_version_id", table_name="resume_version_items")
    op.drop_table("resume_version_items")
