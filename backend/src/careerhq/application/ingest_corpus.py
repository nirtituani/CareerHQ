"""Loading the authored corpus into the database, repeatably.

**Re-running this on an unchanged corpus must do nothing at all — including no
embedding.** That is the property the whole command is built around, and it is a
correctness argument as much as a cost one: embedding is the expensive half, so an
ingestion that re-embeds 79 chunks to discover they are identical becomes something an
operator avoids running, and a corpus nobody re-ingests drifts away from the files that
define it.

**`content_hash` is the identity, so an edited rule is a new chunk rather than an updated
one** (FR-012). That is what keeps a recorded citation checkable: recompute the hash over
the text a past run was advised with, and a match proves the guidance existed unaltered
while a miss proves drift. Updating a chunk in place would quietly rewrite history and
`uq_knowledge_chunks_document_content` would not notice, because the row is the same row.

**Chunks that leave the corpus leave the database.** Insert-only ingestion is the obvious
shape and it is wrong here: the corpus review deleted an unsupported ATS header/footer
claim and an unsupported mixed-script claim, and under insert-only both would stay
retrievable for ever, having been removed precisely because they were unsupported.
Deleting them does not invalidate earlier citations — `tailoring_runs.guidelines_used`
snapshots the text it used, which is why that snapshot exists.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.embeddings import EmbeddingSource
from careerhq.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument
from careerhq.infrastructure.corpus import ParsedDocument, load_corpus

logger = logging.getLogger("careerhq.corpus")


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """What one ingestion actually did.

    Returned rather than logged only, because "re-running changed nothing" is a claim a
    test has to be able to assert. A command that reports success without saying what it
    touched cannot be checked for idempotence at all.
    """

    documents_created: int = 0
    documents_updated: int = 0
    chunks_created: int = 0
    chunks_deleted: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.documents_created
            or self.documents_updated
            or self.chunks_created
            or self.chunks_deleted
        )


def _metadata_differs(existing: KnowledgeDocument, parsed: ParsedDocument) -> bool:
    """Whether anything about the document itself changed.

    Checked separately from the chunks because the two move independently: the corpus
    review retagged a document's `trust_level` without touching a rule, and ingestion
    that keyed only on chunk hashes would have left the old level in place — the files
    and the database then disagreeing about the standing of every rule in that document.
    """
    return (
        existing.source_type != parsed.source_type
        or existing.title != parsed.title
        or existing.market != parsed.market
        or existing.trust_level != parsed.trust_level
        or list(existing.origin_source_ids) != list(parsed.origin_source_ids)
    )


async def ingest_corpus(
    session: AsyncSession,
    *,
    embedder: EmbeddingSource,
    root: pathlib.Path | None = None,
) -> IngestionReport:
    """Bring the database in line with the authored corpus. Safe to re-run.

    The session is committed by the caller, so an ingestion that raises part-way leaves
    nothing behind — the same transaction discipline the tailoring use case follows.
    """
    documents_created = documents_updated = chunks_created = chunks_deleted = 0

    for parsed in load_corpus(root):
        existing = await session.scalar(
            sa.select(KnowledgeDocument)
            .where(KnowledgeDocument.slug == parsed.slug)
            .options(sa.orm.selectinload(KnowledgeDocument.chunks))
        )

        if existing is None:
            document = KnowledgeDocument(
                slug=parsed.slug,
                source_type=parsed.source_type,
                title=parsed.title,
                version=parsed.version,
                market=parsed.market,
                trust_level=parsed.trust_level,
                origin_source_ids=list(parsed.origin_source_ids),
                is_active=True,
                # Assigned at construction. A lazy load on a freshly added object
                # raises MissingGreenlet under async SQLAlchemy, which this project
                # has hit twice.
                chunks=[],
            )
            session.add(document)
            await session.flush()
            documents_created += 1
            existing_hashes: set[str] = set()
        else:
            document = existing
            existing_hashes = {c.content_hash for c in existing.chunks}

        wanted = {c.content_hash: c for c in parsed.chunks}

        # Embed only what is genuinely new. This is the line that makes an unchanged
        # re-run free, and the reason the report counts embedding-worthy work rather
        # than rows alone.
        new = [c for c in parsed.chunks if c.content_hash not in existing_hashes]
        vectors = await embedder.embed_passages([c.text for c in new]) if new else []

        for chunk, vector in zip(new, vectors, strict=True):
            session.add(
                KnowledgeChunk(
                    document_id=document.id,
                    content_hash=chunk.content_hash,
                    text_=chunk.text,
                    chunk_order=chunk.chunk_order,
                    token_count=chunk.token_count,
                    embedding=list(vector),
                    meta=dict(chunk.metadata),
                )
            )
            chunks_created += 1

        stale = existing_hashes - set(wanted)
        if stale:
            await session.execute(
                sa.delete(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == document.id,
                    KnowledgeChunk.content_hash.in_(stale),
                )
            )
            chunks_deleted += len(stale)

        # `chunk_order` is a property of the file, not of insertion order, so a rule
        # that moved without changing text still has to be re-seated. Done for every
        # surviving chunk rather than only the new ones: reordering two rules changes
        # neither hash, so nothing else here would notice.
        for chunk in parsed.chunks:
            await session.execute(
                sa.update(KnowledgeChunk)
                .where(
                    KnowledgeChunk.document_id == document.id,
                    KnowledgeChunk.content_hash == chunk.content_hash,
                    KnowledgeChunk.chunk_order != chunk.chunk_order,
                )
                .values(chunk_order=chunk.chunk_order)
            )

        content_changed = bool(new or stale)
        if existing is not None and (content_changed or _metadata_differs(existing, parsed)):
            document.source_type = parsed.source_type
            document.title = parsed.title
            document.market = parsed.market
            document.trust_level = parsed.trust_level
            document.origin_source_ids = list(parsed.origin_source_ids)
            # Bumped on any change, content or metadata. A citation recorded against
            # version N stays resolvable because the run snapshotted its text; the
            # bump is what lets a reader tell that the document has moved on.
            document.version = existing.version + 1
            documents_updated += 1

        await session.flush()

    report = IngestionReport(
        documents_created=documents_created,
        documents_updated=documents_updated,
        chunks_created=chunks_created,
        chunks_deleted=chunks_deleted,
    )
    logger.info(
        "corpus ingested",
        extra={
            "documents_created": report.documents_created,
            "documents_updated": report.documents_updated,
            "chunks_created": report.chunks_created,
            "chunks_deleted": report.chunks_deleted,
            "changed": report.changed,
        },
    )
    return report


__all__ = ["IngestionReport", "ingest_corpus"]
