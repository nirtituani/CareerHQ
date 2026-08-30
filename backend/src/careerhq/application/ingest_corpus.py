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
from careerhq.config import get_settings
from careerhq.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument
from careerhq.infrastructure.corpus import CORPUS_ROOT, ParsedDocument, load_corpus

logger = logging.getLogger("careerhq.corpus")


class CorpusEmbeddingModelMismatch(RuntimeError):
    """The stored corpus was embedded by a different model than the one configured (T053).

    **A distinct type, raised before anything is read or written.** `run()` in
    `careerhq.ingest` catches broadly and returns 1, so this blocks a deploy with the
    cause in the operator's output, which is the whole point: without it the same
    situation is a silent `0/0/0/0` success.

    **It refuses and repairs nothing.** Not by re-embedding, which would rewrite a corpus
    the operator may not have meant to change and spend the embedding budget to hide a
    configuration error; and not by overwriting the recorded model, which would launder
    the drift into a row that then looks verified. The resolution is the operator's:
    restore the previous `EMBEDDING_MODEL`, or drop the corpus and re-ingest deliberately.
    """


class CorpusVerificationFailed(RuntimeError):
    """What ingestion left behind is not the corpus the files describe.

    **Raised after the work, not before it, and that is the difference from
    `CorpusEmbeddingModelMismatch`.** That one refuses on a precondition nothing else can
    see. This one refuses on an *outcome*: the loop ran, reported success, and the
    database still does not hold the rules the image ships.

    **It exists because success and total failure were indistinguishable.**
    `IngestionReport` counted movement alone — created, updated, deleted — so an unchanged
    corpus and a corpus that was never there both read `0/0/0/0`, `changed=False`, exit 0.
    Deployment `75cd8ea` shipped exactly that: a green deploy over an empty production
    corpus, invisible because retrieval falls back to the static rubric and records that
    it did (FR-009). T048 fixed the cause it had that day and added a test of the
    `preDeployCommand` *configuration*; nothing has ever checked the *outcome*.

    **`careerhq.ingest` catches this and returns 1**, so a corpus that failed to load
    fails the pre-deploy step and Railway keeps the previous version serving — the same
    gate the migration already relies on, using the exit code that is already wired.
    """


@dataclass(frozen=True, slots=True)
class CorpusPresence:
    """What the database holds, measured against what the files authorise.

    Separate from `IngestionReport` because it is a different kind of claim: the report
    says what one run *did*, this says what is *there* afterwards. A run can legitimately
    do nothing; it can never legitimately leave the corpus absent.
    """

    documents_expected: int
    documents_present: int
    chunks_expected: int
    chunks_present: int


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

    #: What the corpus files authorise, and what the database actually holds, measured
    #: after the work by re-reading both. **These are what make a no-op legible.** The
    #: four counters above are all zero for an unchanged corpus and all zero for a corpus
    #: that was never loaded; `chunks_present` is the field that tells those apart in a
    #: deploy log, which is the only place anyone sees this.
    chunks_expected: int = 0
    chunks_present: int = 0

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


async def _ensure_model_matches(session: AsyncSession, model: str) -> None:
    """Refuse if the stored corpus was embedded by a different model (T053).

    **Checked once, up front, before anything is embedded or written**, because the
    failure it prevents is precisely an ingestion that proceeds and reports `0/0/0/0`.
    `bge-small` and MiniLM are both 384-dimension, so `EMBEDDING_DIMENSIONS`, the
    `vector(384)` column and the adapter's registry width check all pass for either;
    nothing else in the schema can tell them apart. Measured on the real corpus:
    re-embedding a stored chunk gives cosine **1.000000** for the model that wrote it and
    **0.345992** for the other.

    **NULL is not a mismatch.** A corpus ingested before this column existed records
    nothing, and nothing can recover which model wrote those vectors. Refusing on NULL
    would strand a working deployment on a fact nobody has; stamping the configured model
    onto it would be worse. So an unrecorded corpus proceeds, and says so once.
    """
    # The SQL filters NULL and the comprehension narrows the type, which are the same
    # claim stated to two different checkers rather than a cast asserting one at the other.
    recorded = {
        value
        for value in await session.scalars(
            sa.select(KnowledgeDocument.embedding_model)
            .where(KnowledgeDocument.embedding_model.is_not(None))
            .distinct()
        )
        if value is not None
    }
    mismatched = recorded - {model}
    if mismatched:
        raise CorpusEmbeddingModelMismatch(
            f"the stored corpus was embedded with {', '.join(sorted(mismatched))} but "
            f"{model} is configured. Both models may share a vector width, so nothing "
            "else will catch this: queries would run against vectors a different model "
            "produced. Restore the previous EMBEDDING_MODEL, or drop the corpus and "
            "re-ingest it deliberately with the new one."
        )

    if not recorded:
        unrecorded = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeDocument))
        if unrecorded:
            logger.warning(
                "corpus predates embedding-model recording; drift cannot be detected "
                "for these documents until they are re-ingested",
                extra={"documents": unrecorded, "configured_embedding_model": model},
            )


async def verify_corpus_ingested(
    session: AsyncSession, *, root: pathlib.Path | None = None
) -> CorpusPresence:
    """Confirm the database holds every chunk the corpus files authorise.

    **It re-reads the files and re-queries the database rather than trusting the counters
    ingestion just produced.** A loop that miscounts is precisely what this guards
    against, and a run that marks its own homework catches nothing — so the corpus is
    loaded a second time here. That costs parsing 18 small files once per deploy, which
    is not a budget anybody is defending.

    **An empty corpus is a refusal, not a pass, and that check is the load-bearing one.**
    Every other assertion here has the form *"everything expected is present"*, which a
    corpus of nothing satisfies vacuously. A corpus absent from the image — a
    `.dockerignore` edit, a moved directory — is the realistic way that happens, and it
    would otherwise ingest "successfully" into an empty database. This project has shipped
    a gate with nothing to examine five times; this is the line that stops the sixth.

    **Matched per document and by `content_hash`, not by a global `COUNT(*)`.** A bare
    total would be satisfied by the right number of the wrong rows, and it would also
    count chunks belonging to documents that have since left the corpus — which are drift
    to be reported elsewhere, not evidence that today's corpus arrived.

    Read-only, and safe to call outside ingestion.
    """
    parsed_documents = load_corpus(root)
    chunks_expected = sum(len(parsed.chunks) for parsed in parsed_documents)

    if not chunks_expected:
        raise CorpusVerificationFailed(
            "no corpus was found to ingest: "
            f"{len(parsed_documents)} documents and {chunks_expected} chunks were read "
            f"from {root or CORPUS_ROOT}. An ingestion that writes nothing because there "
            "was nothing to write reports the same 0/0/0/0 as an unchanged corpus, so "
            "this refuses rather than letting the deploy proceed over an empty database."
        )

    documents_present = 0
    chunks_present = 0
    for parsed in parsed_documents:
        document_id = await session.scalar(
            sa.select(KnowledgeDocument.id).where(KnowledgeDocument.slug == parsed.slug)
        )
        if document_id is None:
            continue
        documents_present += 1
        found = await session.scalar(
            sa.select(sa.func.count())
            .select_from(KnowledgeChunk)
            .where(
                KnowledgeChunk.document_id == document_id,
                KnowledgeChunk.content_hash.in_([c.content_hash for c in parsed.chunks]),
            )
        )
        chunks_present += int(found or 0)

    if chunks_present != chunks_expected:
        raise CorpusVerificationFailed(
            f"the ingested corpus is incomplete: {chunks_present} of {chunks_expected} "
            f"authored chunks are in the database, across {documents_present} of "
            f"{len(parsed_documents)} documents. Retrieval would fall back to the static "
            "rubric and record that it did (FR-009), which is a working system and an "
            "invisible failure, so the deploy is refused instead."
        )

    return CorpusPresence(
        documents_expected=len(parsed_documents),
        documents_present=documents_present,
        chunks_expected=chunks_expected,
        chunks_present=chunks_present,
    )


async def ingest_corpus(
    session: AsyncSession,
    *,
    embedder: EmbeddingSource,
    root: pathlib.Path | None = None,
    embedding_model: str | None = None,
) -> IngestionReport:
    """Bring the database in line with the authored corpus. Safe to re-run.

    The session is committed by the caller, so an ingestion that raises part-way leaves
    nothing behind — the same transaction discipline the tailoring use case follows.
    """
    # **Passed in rather than asked of the embedder** (T053). `EmbeddingSource`
    # deliberately carries no model name, so the identity travels as a plain string from
    # the caller, which builds the embedder from the same setting.
    model = embedding_model or get_settings().embedding_model
    await _ensure_model_matches(session, model)

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
                # Known first-hand: every chunk of a document created now is
                # embedded now, by this model. An existing document is left alone.
                embedding_model=model,
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

    # **Verified before the report exists, so there is no success record to contradict.**
    # The rows are flushed but not committed — the caller owns the transaction — so a
    # refusal here means nothing is written at all, exactly as the model-mismatch refusal
    # behaves. It reads the files and the database afresh rather than the counters above.
    presence = await verify_corpus_ingested(session, root=root)

    report = IngestionReport(
        documents_created=documents_created,
        documents_updated=documents_updated,
        chunks_created=chunks_created,
        chunks_deleted=chunks_deleted,
        chunks_expected=presence.chunks_expected,
        chunks_present=presence.chunks_present,
    )
    logger.info(
        "corpus ingested",
        extra={
            "documents_created": report.documents_created,
            "documents_updated": report.documents_updated,
            "chunks_created": report.chunks_created,
            "chunks_deleted": report.chunks_deleted,
            "changed": report.changed,
            "chunks_expected": report.chunks_expected,
            "chunks_present": report.chunks_present,
        },
    )
    return report


__all__ = [
    "CorpusEmbeddingModelMismatch",
    "CorpusPresence",
    "CorpusVerificationFailed",
    "IngestionReport",
    "ingest_corpus",
    "verify_corpus_ingested",
]
