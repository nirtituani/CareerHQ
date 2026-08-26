"""Record the master position a proposal displaced (T095).

One nullable column: `resume_version_items.displaced_position`. `position`
holds the proposed value when a proposal arrives and the master's when none
does, so on its own it destroys the master's ordering for exactly the items the
draft touched — 13 of 140 rows at the time this was written. The master's
ordering at creation becomes `COALESCE(displaced_position, position)` for every
item, which is what FR-030 requires and what a reorder needs in order to be
distinguishable from an item the draft never named.

**No backfill, deliberately.** Existing rows keep NULL. Whether a proposal
arrived for them was never recorded, and while their master positions happen to
be re-derivable today — the profile has not changed since before any run — a
derived value written into a column is inference presented as record. They are
read as `unknown_position`, never as "no proposal arrived".

Revision ID: 0014_displaced_position
Revises: 0013_review_passes
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_displaced_position"
down_revision: str | None = "0013_review_passes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resume_version_items",
        sa.Column("displaced_position", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("resume_version_items", "displaced_position")
