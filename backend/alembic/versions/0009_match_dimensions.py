"""Keep the four rated dimensions, not just their weighted total.

Slice 004. The score is a weighted sum of `direct`, `transferable`, `adjacent`
and `impact`; those were computed, used, and thrown away, so the interface could
show a total with no way to say where it came from.

That is exactly the "pseudo-scientific fit percentage" one of the rubric sources
warns against — a bare number implies a measurement nobody can audit. Stored
beside it, the total becomes arithmetic a person can check against four stated
judgements, with the weights on screen. The parts are what earn the number.

Nullable rather than defaulted: an analysis written before this migration has a
correct total that simply cannot be explained, and inventing dimensions that sum
to it would be fabricating the explanation.

Revision ID: 0009_match_dimensions
Revises: 0008_unverified_no_shortfall
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_match_dimensions"
down_revision: str | None = "0008_unverified_no_shortfall"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("direct", "transferable", "adjacent", "impact")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("match_analyses", sa.Column(column, sa.SmallInteger(), nullable=True))

    op.create_check_constraint(
        "ck_match_analysis_dimensions",
        "match_analyses",
        " AND ".join(f"({c} IS NULL OR {c} BETWEEN 0 AND 100)" for c in _COLUMNS),
    )


def downgrade() -> None:
    op.drop_constraint("ck_match_analysis_dimensions", "match_analyses", type_="check")
    for column in _COLUMNS:
        op.drop_column("match_analyses", column)
