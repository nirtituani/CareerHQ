"""Enable required PostgreSQL extensions.

Enabled now, before anything needs them, so that later slices require no
environment change (FR-004).

``vector`` is enabled in a migration rather than a database init script on
purpose: init scripts run only when the data volume is first created, so a
developer with an existing volume would silently lack the extension and only
discover it much later. A migration is versioned and reproducible.

Revision ID: 0001_extensions
Revises:
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_extensions"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Vector similarity search, used by the Knowledge Context from slice 004.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # gen_random_uuid(), for UUID primary keys.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    # RESTRICT rather than CASCADE: if something still depends on these, the
    # downgrade should fail loudly rather than silently dropping columns.
    op.execute("DROP EXTENSION IF EXISTS pgcrypto RESTRICT")
    op.execute("DROP EXTENSION IF EXISTS vector RESTRICT")
