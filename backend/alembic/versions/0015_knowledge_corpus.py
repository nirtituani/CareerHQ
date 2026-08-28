"""The guideline corpus: `knowledge_documents` and `knowledge_chunks` (T004).

Derived from `alembic revision --autogenerate` against the models T006 already
wrote, then **reviewed rather than accepted**. Autogenerate proposed two things
this file deliberately does not carry:

1. It rendered the embedding column as `pgvector.sqlalchemy.vector.VECTOR` and
   emitted **no import for it**. The generated file raises `NameError` on the
   first upgrade. Imported explicitly below.
2. It proposed **eleven `alter_column ... server_default=None` operations**
   across `applications`, `match_analyses`, `resume_version_items`,
   `resume_versions`, `tailoring_runs` and `reviewer_findings` — five tables
   holding the project's only paid evaluation data, none of them this slice's
   business. They are real, **pre-existing** drift: migrations 0004-0013 wrote
   `server_default=`, while the models declare Python-side `default=`, so
   `compare_server_default=True` reads the database's default as an unwanted
   extra every time. Stripping those defaults would silently change what an
   INSERT that omits the column does, in slice 003/004/005 code paths, inside a
   migration whose stated subject is the corpus. Recorded in `HANDOFF.md` §4 so
   the next autogenerate is not surprised by it; not fixed here.

**384 is written out rather than imported from `EMBEDDING_DIMENSIONS`.** A
migration is a historical record of what the schema became on this date. If it
read the constant, changing the embedding model would retroactively rewrite what
this migration did, and the one artifact that can reconstruct the database from
nothing would no longer describe any database that ever existed.

**No ANN index on `embedding`, deliberately.** Corpus V1 is ~95-130 chunks. An
`hnsw` or `ivfflat` index over a table that small is slower than the sequential
scan it replaces — the planner would decline it — and both are *approximate*, so
it would trade exact recall for nothing. FR-014's ceiling and SC-007's ≤500 ms
are both met by a full scan at this size. When the corpus grows past a few
thousand chunks this becomes a real decision, with a measurement behind it.

Revision ID: 0015_knowledge_corpus
Revises: 0014_displaced_position
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0015_knowledge_corpus"
down_revision: str | None = "0014_displaced_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("trust_level", sa.String(length=24), nullable=False),
        sa.Column("origin_source_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("market IN ('global', 'israel')", name="ck_knowledge_documents_market"),
        sa.CheckConstraint(
            "trust_level IN ('internal', 'institutional', 'vendor_documented', 'industry')",
            name="ck_knowledge_documents_trust_level",
        ),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_documents_version"),
        sa.PrimaryKeyConstraint("id"),
        # `slug` is the natural key a recorded citation resolves through, so it
        # is unique in the schema rather than by convention.
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_order", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        # `vector(384)` — `BAAI/bge-small-en-v1.5` through fastembed/ONNX. The
        # width is a schema commitment: a model of a different width is another
        # migration, not a configuration change.
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("token_count > 0", name="ck_knowledge_chunks_token_count"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Idempotent ingestion (FR-012) rests on this: re-running an unchanged
        # corpus must add zero chunks, and the same rule text in the same
        # document cannot be stored twice. In the schema, where a concurrent
        # ingestion cannot race it.
        sa.UniqueConstraint(
            "document_id", "content_hash", name="uq_knowledge_chunks_document_content"
        ),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
