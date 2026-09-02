"""Snapshot a skill's category onto the version item that carries it.

One nullable column, following the role-context snapshot (0017) exactly. A Skills
section is grouped by category, and the category lived only on the profile — so an
export either reached back into live profile data to group its rows, or could not group
them at all. It did the second, and every skill rendered on its own line.

**A snapshot rather than a live read, for the reason 0017 gives.** Export must be able
to re-render a locked version to the same bytes its checksum was recorded over
(FR-021/FR-023). A category read live would let a later profile edit reshape a document
somebody has already approved and sent.

**Nullable, no default, no backfill.** A skill may genuinely have no category, and every
row that predates this has no snapshot to recover — reading one from the profile now
would be exactly the live read this column exists to avoid. Those items compose as plain
rows, which is what they did before.

**Named `source_category`, not `skill_category`.** It sits beside `source_kind` and
`source_item_id` and describes the source row's own grouping label. Only `SKILL` carries
one today; nothing about the column assumes that stays true.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0023_skill_category_snapshot"
down_revision: str | None = "0022_resume_theme"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "resume_version_items",
        sa.Column("source_category", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("resume_version_items", "source_category")
