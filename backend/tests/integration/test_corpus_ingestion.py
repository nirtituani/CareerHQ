"""T026 — corpus ingestion, and the property that makes it safe to re-run.

**Idempotence here is not tidiness, it is the cost and the correctness argument at once.**
Re-running an unchanged corpus must insert nothing *and embed nothing*: embedding is the
expensive half, and a run that re-embeds 79 chunks to discover they are identical has
made re-ingestion something an operator avoids, which is how a corpus drifts from the
files that define it.

The honesty half is FR-012. A rule that is edited becomes a **new** chunk rather than an
updated one, because `content_hash` is the citation identity — and a rule that is deleted
must actually leave the database, or the two rules removed during the corpus review
(the ATS header/footer claim and the mixed-script claim) would stay retrievable after
being removed for being unsupported.
"""

from __future__ import annotations

import pathlib
from collections.abc import Sequence

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.ingest_corpus import (
    CorpusEmbeddingModelMismatch,
    IngestionReport,
    ingest_corpus,
)
from careerhq.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument

pytestmark = pytest.mark.asyncio


class CountingEmbedder:
    """An `EmbeddingSource` that reports how much work it was asked to do.

    The point of the test double: idempotence is measured in **embedding calls**, not
    only in row counts. A second ingestion that inserts nothing but re-embeds everything
    still costs what the first one did.
    """

    def __init__(self) -> None:
        self.embedded: list[str] = []
        self.calls = 0

    @property
    def dimensions(self) -> int:
        return 384

    async def embed_passages(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls += 1
        self.embedded.extend(texts)
        # Deterministic and distinct per text, so a mismatched vector is visible.
        return [[float((hash(t) % 1000) + i) / 1000.0 for i in range(384)] for t in texts]

    async def embed_query(self, text: str) -> Sequence[float]:  # pragma: no cover
        raise AssertionError("ingestion must never embed a query")


_DOC = """---
slug: ingest-fixture
source_type: integrity
market: global
trust_level: internal
role_family: any
seniority: any
resume_section: any
topic: [integrity]
origin_source_ids: []
---

# An ingestion fixture

Preamble prose that must never become a chunk.

## Rules

- The first rule is long enough to clear the corpus lint's fragment threshold and says
  something actionable about writing a resume.

- The second rule is also long enough to clear that threshold and says something else
  actionable, carrying its own condition where one applies.
"""


@pytest.fixture
def corpus_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "corpus"
    (root / "integrity").mkdir(parents=True)
    (root / "integrity" / "ingest-fixture.md").write_text(_DOC)
    return root


async def _counts(session: AsyncSession) -> tuple[int, int]:
    docs = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeDocument))
    chunks = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeChunk))
    return int(docs or 0), int(chunks or 0)


async def test_first_ingestion_creates_documents_and_chunks(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    embedder = CountingEmbedder()

    report = await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)

    assert (await _counts(db_session)) == (1, 2)
    assert report.documents_created == 1
    assert report.chunks_created == 2
    assert report.chunks_deleted == 0
    assert len(embedder.embedded) == 2


async def test_re_ingesting_an_unchanged_corpus_changes_nothing_and_embeds_nothing(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """The T026 headline. **Drill it** by dropping the content-hash comparison.

    Zero on every counter, and — the part a row count cannot show — **zero embedding
    calls**. An ingestion that re-embeds to discover nothing changed has not been
    made idempotent, it has been made quiet.
    """
    first = CountingEmbedder()
    await ingest_corpus(db_session, embedder=first, root=corpus_dir)

    second = CountingEmbedder()
    report = await ingest_corpus(db_session, embedder=second, root=corpus_dir)

    assert (await _counts(db_session)) == (1, 2)
    assert report.chunks_created == 0
    assert report.chunks_deleted == 0
    assert report.documents_created == 0
    assert report.documents_updated == 0
    assert second.calls == 0, f"re-ingestion embedded {second.embedded}"


async def test_editing_a_rule_replaces_its_chunk_and_bumps_the_document_version(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """FR-012: an edited rule is a *new* chunk, because the hash is the identity."""
    await ingest_corpus(db_session, embedder=CountingEmbedder(), root=corpus_dir)
    before = await db_session.scalar(
        sa.select(KnowledgeChunk.content_hash).where(KnowledgeChunk.chunk_order == 0)
    )

    path = corpus_dir / "integrity" / "ingest-fixture.md"
    path.write_text(_DOC.replace("says\n  something actionable", "says\n  something different"))

    embedder = CountingEmbedder()
    report = await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)

    assert (await _counts(db_session)) == (1, 2), "the edited rule must replace, not accumulate"
    assert report.chunks_created == 1
    assert report.chunks_deleted == 1
    assert len(embedder.embedded) == 1, "only the changed rule is re-embedded"

    after = await db_session.scalar(
        sa.select(KnowledgeChunk.content_hash).where(KnowledgeChunk.chunk_order == 0)
    )
    assert after != before

    version = await db_session.scalar(sa.select(KnowledgeDocument.version))
    assert version == 2


async def test_a_removed_rule_leaves_the_database(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """A rule deleted from the corpus must stop being retrievable.

    Not hypothetical: the corpus review removed an unsupported ATS header/footer claim
    and an unsupported mixed-script claim. If ingestion only ever inserts, both stay
    retrievable for ever, having been deleted precisely because they were wrong.
    """
    await ingest_corpus(db_session, embedder=CountingEmbedder(), root=corpus_dir)

    path = corpus_dir / "integrity" / "ingest-fixture.md"
    path.write_text(_DOC.split("- The second rule")[0].rstrip() + "\n")

    report = await ingest_corpus(db_session, embedder=CountingEmbedder(), root=corpus_dir)

    assert (await _counts(db_session)) == (1, 1)
    assert report.chunks_deleted == 1
    assert report.chunks_created == 0


async def test_document_metadata_changes_are_applied(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """The trust-level correction the review made must reach the database.

    F2 retagged a document's trust level without touching a rule. Ingestion that keys
    only on chunk hashes would leave the old level in place and the corpus files and the
    database would disagree about the standing of every rule in the file.
    """
    await ingest_corpus(db_session, embedder=CountingEmbedder(), root=corpus_dir)

    path = corpus_dir / "integrity" / "ingest-fixture.md"
    path.write_text(_DOC.replace("trust_level: internal", "trust_level: industry"))

    embedder = CountingEmbedder()
    report = await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)

    assert report.documents_updated == 1
    assert report.chunks_created == 0 and report.chunks_deleted == 0
    assert embedder.calls == 0, "a metadata change must not re-embed unchanged rules"

    level = await db_session.scalar(sa.select(KnowledgeDocument.trust_level))
    assert level == "industry"


async def test_ingesting_the_real_corpus_matches_the_authored_rule_count(
    db_session: AsyncSession,
) -> None:
    """End to end against the corpus that actually ships."""
    embedder = CountingEmbedder()

    report = await ingest_corpus(db_session, embedder=embedder)

    assert report.documents_created == 18
    assert report.chunks_created == 79
    assert (await _counts(db_session)) == (18, 79)

    again = CountingEmbedder()
    second: IngestionReport = await ingest_corpus(db_session, embedder=again)
    assert second.chunks_created == 0 and second.chunks_deleted == 0
    assert again.calls == 0


# -- T053: the corpus records which model embedded it -------------------------
#
# **The failure this exists to make impossible to miss.** Both `bge-small` and MiniLM are
# 384-dimension, so `EMBEDDING_DIMENSIONS`, `vector(384)` and the adapter's registry width
# check all pass for either. Ingestion's identity is `content_hash` over the **rule text**,
# so changing only the model leaves every hash matching: ingestion embeds nothing, reports
# 0/0/0/0 and exits 0, while every query then runs a different model against the stored
# vectors. Measured on the real local corpus: re-embedding a stored chunk gives cosine
# **1.000000** for the model that wrote it and **0.345992** for the other one.


async def test_first_ingestion_records_the_configured_embedding_model(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """A document created now was embedded now, so its model is known first-hand."""
    await ingest_corpus(
        db_session, embedder=CountingEmbedder(), root=corpus_dir, embedding_model="model-a"
    )

    recorded = list(await db_session.scalars(sa.select(KnowledgeDocument.embedding_model)))
    assert recorded == ["model-a"]


async def test_an_unchanged_corpus_on_the_same_model_is_still_a_no_op(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """**The property T026 is built around must survive the guard.** A check that made
    every re-run re-embed would have destroyed the thing it was added to protect."""
    await ingest_corpus(
        db_session, embedder=CountingEmbedder(), root=corpus_dir, embedding_model="model-a"
    )

    second = CountingEmbedder()
    report = await ingest_corpus(
        db_session, embedder=second, root=corpus_dir, embedding_model="model-a"
    )

    assert (report.documents_created, report.documents_updated) == (0, 0)
    assert (report.chunks_created, report.chunks_deleted) == (0, 0)
    assert second.calls == 0, f"re-ingestion embedded {second.embedded}"


async def test_a_changed_model_is_refused_and_names_both_models(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """**The whole point.** Without this the run is a silent 0/0/0/0.

    The message must name **both** models: an operator seeing only "mismatch" has to go
    and find what the corpus was built with, and the answer is in a column they do not
    know exists.
    """
    await ingest_corpus(
        db_session, embedder=CountingEmbedder(), root=corpus_dir, embedding_model="model-a"
    )

    after = CountingEmbedder()
    with pytest.raises(CorpusEmbeddingModelMismatch) as caught:
        await ingest_corpus(db_session, embedder=after, root=corpus_dir, embedding_model="model-b")

    message = str(caught.value)
    assert "model-a" in message, "the refusal must name what the corpus was embedded with"
    assert "model-b" in message, "the refusal must name what is now configured"
    assert "re-ingest" in message.lower(), "the refusal must say what resolves it"


async def test_a_refused_ingestion_embeds_nothing_and_changes_nothing(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """**It refuses; it does not repair.** Re-embedding on mismatch would silently rewrite
    a corpus an operator may not have meant to change, and stamping the new model over the
    old rows would launder the drift into a record that then looks verified."""
    await ingest_corpus(
        db_session, embedder=CountingEmbedder(), root=corpus_dir, embedding_model="model-a"
    )
    before = await _counts(db_session)

    after = CountingEmbedder()
    with pytest.raises(CorpusEmbeddingModelMismatch):
        await ingest_corpus(db_session, embedder=after, root=corpus_dir, embedding_model="model-b")

    assert after.calls == 0, "a refused ingestion must not embed"
    assert (await _counts(db_session)) == before, "a refused ingestion must not write rows"
    still = set(await db_session.scalars(sa.select(KnowledgeDocument.embedding_model)))
    assert still == {"model-a"}, "the recorded model must not be overwritten by the refusal"


async def test_a_corpus_predating_the_column_is_not_falsely_accused(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """**NULL means unknown, not mismatched.**

    The corpus ingested before migration 0018 records no model, and nothing can recover
    which one wrote those vectors. Refusing would strand a working deployment on a fact
    nobody has; **stamping the configured model onto it would be worse** — asserting, in a
    column built to be trusted, something never verified. So NULL is left alone and
    ingestion proceeds.
    """
    await ingest_corpus(
        db_session, embedder=CountingEmbedder(), root=corpus_dir, embedding_model="model-a"
    )
    await db_session.execute(sa.update(KnowledgeDocument).values(embedding_model=None))
    await db_session.flush()

    later = CountingEmbedder()
    report = await ingest_corpus(
        db_session, embedder=later, root=corpus_dir, embedding_model="model-b"
    )

    assert report.chunks_created == 0, "an unchanged corpus is still unchanged"
    assert later.calls == 0
    recorded = set(await db_session.scalars(sa.select(KnowledgeDocument.embedding_model)))
    assert recorded == {None}, "an unverifiable corpus must not be stamped as verified"


async def test_the_model_is_not_part_of_chunk_identity(
    db_session: AsyncSession, corpus_dir: pathlib.Path
) -> None:
    """`content_hash` stays a hash of the **rule text only** (FR-012).

    Folding the model into it would make every citation recorded by an earlier run
    unresolvable the moment the model changed, which is the exact thing FR-012 forbids.
    The guard is a separate recorded fact precisely so identity can stay textual.
    """
    await ingest_corpus(
        db_session, embedder=CountingEmbedder(), root=corpus_dir, embedding_model="model-a"
    )
    before = sorted(await db_session.scalars(sa.select(KnowledgeChunk.content_hash)))

    await db_session.execute(sa.update(KnowledgeDocument).values(embedding_model="model-b"))
    await db_session.flush()
    await ingest_corpus(
        db_session, embedder=CountingEmbedder(), root=corpus_dir, embedding_model="model-b"
    )

    after = sorted(await db_session.scalars(sa.select(KnowledgeChunk.content_hash)))
    assert after == before, "content_hash changed with the embedding model"
