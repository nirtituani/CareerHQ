"""`unverified` carries no shortfall, because it cannot know one.

Slice 004. Corrects the rule shipped in 0006, which required a shortfall on
every verdict except `confirmed`.

A real completion failed validation on exactly this: four `unverified`
requirements with no shortfall. **The model was right.** `unverified` means the
profile says nothing about the requirement, so choosing between `wording`,
`evidence` and `capability` means guessing *why* it is silent — no skill,
different words, or simply never written down. Nothing in the profile answers
that, and demanding an answer reintroduces the invented absence the five-verdict
taxonomy exists to prevent, in the very field added to make shortfalls
actionable.

The action for `unverified` needs no classification anyway: put it on your CV if
you have it.

Revision ID: 0008_unverified_no_shortfall
Revises: 0007_requirement_importance
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_unverified_no_shortfall"
down_revision: str | None = "0007_requirement_importance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_match_requirement_shortfall", "match_requirements", type_="check")
    op.create_check_constraint(
        "ck_match_requirement_shortfall",
        "match_requirements",
        "(verdict IN ('confirmed', 'unverified')) = (shortfall IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_match_requirement_shortfall", "match_requirements", type_="check")
    op.create_check_constraint(
        "ck_match_requirement_shortfall",
        "match_requirements",
        "(verdict = 'confirmed') = (shortfall IS NULL)",
    )
