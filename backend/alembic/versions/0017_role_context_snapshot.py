"""Snapshot role context onto version items (T051).

**Additive and entirely nullable.** Five columns on `resume_version_items`, all NULL for
every existing row. Nothing is backfilled and nothing is rewritten: six versions predate
this — one of them **submitted**, with an `ExportedDocument` checksum recorded over bytes
that must never be re-derived — and inventing role context for them after the fact would
put values into a document the owner approved without them.

**Why nullable is a requirement rather than a convenience.** `_compose` renders an item
with no `role_ordinal` in a single unlabelled group, exactly as it did before this
migration. A NOT NULL column with a server default would instead give every historical
bullet the *same* fabricated role, which is worse than the gap it closes.

**`role_ordinal` is `work_experiences.ordinal`**, the profile's existing explicit order
field — snapshotted, not recomputed, because ordering a frozen document by a number that
can still move reintroduces the mutability the snapshot exists to prevent.

No index. The columns are only ever read alongside the item rows themselves, which are
already fetched by `resume_version_id`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_role_context_snapshot"
down_revision = "0016_export_and_submission"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("role_employer", sa.String(length=255)),
    ("role_title", sa.String(length=255)),
    ("role_start_date", sa.String(length=64)),
    ("role_end_date", sa.String(length=64)),
    ("role_ordinal", sa.Integer()),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("resume_version_items", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("resume_version_items", name)
