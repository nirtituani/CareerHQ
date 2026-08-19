"""Per-requirement importance, judged rather than read off the heading.

Slice 004, criteria `v2-importance`.

A posting's "must have" heading is routinely a wishlist. Banding on it means
either every job caps at `stretch` — a uselessly pessimistic signal — or the cap
never fires. So the model judges what each requirement is actually worth to this
recruiter for this role, informed by how the posting is written: what comes
first, what is repeated, what the role is named after.

`kind` stays. It is the employer's own words, and the same split as `status`
against `normalized_status`: the source is preserved and the value the system
reasons over is derived, so neither can be quietly lost.

**Existing rows default to 50** — below `CAP_IMPORTANCE`, so a v1 analysis
cannot start capping retroactively under a rule it was never scored against.
Those rows carry `criteria_version = 'v1-weighted'` and stay distinguishable
(FR-018).

Revision ID: 0007_requirement_importance
Revises: 0006_match_analysis
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_requirement_importance"
down_revision: str | None = "0006_match_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "match_requirements",
        sa.Column(
            "importance",
            sa.SmallInteger(),
            nullable=False,
            server_default="50",
        ),
    )
    op.create_check_constraint(
        "ck_match_requirement_importance",
        "match_requirements",
        "importance >= 0 AND importance <= 100",
    )


def downgrade() -> None:
    op.drop_constraint("ck_match_requirement_importance", "match_requirements", type_="check")
    op.drop_column("match_requirements", "importance")
