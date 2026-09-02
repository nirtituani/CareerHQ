"""Carry an imported CV's design from the upload to the exported document.

Two nullable JSONB columns and nothing else, because the theme has to survive
exactly one hop: it is readable only while the upload is in memory, and it is
needed only when a version is rendered.

- `imported_resumes.theme` stages it beside the extracted items. By approval
  time the only remaining copy of the bytes is the retained original, and
  reading that back to derive a capability is what
  `tests/unit/test_architecture.py` refuses — so it cannot be recovered later.
- `resume_profiles.theme` is FR-006's presentation-preferences seam
  (`docs/01` §FR-006: *"Resume Profiles shall define presentation preferences
  without duplicating data"*), which the schema has carried a place for since
  slice 003 and never populated.

**Nullable, with no server default and no backfill.** NULL means "the plain ATS
template", which is what every existing row means and what every DOCX import
will keep meaning. A default would assert a design for CVs nobody measured.

**No separate table.** A theme has no identity of its own, is one-to-one with
its owner, and is never queried across rows; a table would add a join and a
lifecycle to a value that is written once and read whole.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_resume_theme"
down_revision: str | None = "0021_career_advisor"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "imported_resumes",
        sa.Column("theme", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "resume_profiles",
        sa.Column("theme", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("resume_profiles", "theme")
    op.drop_column("imported_resumes", "theme")
