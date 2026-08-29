"""Record which embedding model produced the corpus (T053).

**One nullable column, and nothing is backfilled.** Every existing document records
NULL, which means *unknown* rather than *mismatched*: the local corpus predates this and
nothing can recover which model wrote its vectors. Stamping the configured model onto
those rows would assert, in the column added to be trusted, something never verified —
so the guard treats NULL as "no claim" and lets ingestion proceed.

**Why the schema needs this at all.** `BAAI/bge-small-en-v1.5` and
`sentence-transformers/all-MiniLM-L6-v2` are both **384-dimension**, so
`EMBEDDING_DIMENSIONS`, the `vector(384)` column and the adapter's registry width check
all pass for either one. Ingestion's identity is `content_hash` over the **rule text**, so
changing only the model leaves every hash matching: ingestion embeds nothing, reports
0/0/0/0 and exits 0, while queries then run a different model against the stored vectors.
Measured on the real corpus — re-embedding a stored chunk gives cosine **1.000000** for
the model that wrote it and **0.345992** for the other. Nothing else in the schema can
tell those two apart.

**Deliberately not on `knowledge_chunks`.** The model is a property of the corpus, not of
a rule, and per-chunk storage would repeat one value 79 times while inviting a state where
chunks of one document disagree. `knowledge_documents` is also where ingestion already
writes, so the guard costs one query rather than a join.

**`content_hash` is untouched.** Folding the model into it would make every citation
recorded by an earlier run unresolvable the moment the model changed — exactly what FR-012
forbids.

No index: the column is read once per ingestion, over 18 rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_corpus_embedding_model"
down_revision = "0017_role_context_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "embedding_model")
