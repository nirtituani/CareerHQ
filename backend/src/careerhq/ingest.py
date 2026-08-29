"""`python -m careerhq.ingest` — the caller `ingest_corpus` never had (T050).

**Without this the slice does nothing.** Retrieval is wired and correct, and until this
existed nothing outside the test suite ever wrote a chunk: a deployed backend retrieved
against an empty corpus, fell back to the static rubric on every run, recorded that it did
(FR-009), and looked perfectly healthy doing it.

**Where it runs was decided at OQ-006-C and is not reopened here.** Pre-deploy, after
`alembic upgrade head`, joined by `&&`:

    preDeployCommand = "alembic upgrade head && python -m careerhq.ingest"

The order is load-bearing — `knowledge_chunks` has to exist before anything writes to it —
and pre-deploy means **once per deploy, not once per replica**. The startup hook is *ruled
out*: it would pay a model load on every container start and let two replicas booting
together race `uq_knowledge_chunks_document_content`, and both failures scale with replica
count, so the configuration that produces them is a scaling change nobody would connect to
ingestion. It is not in `entrypoint.sh` either: a stale *schema* breaks the application, a
stale *corpus* does not.

**The exit code is the whole point.** A command that catches an exception, logs it and
exits 0 is the exact shape of a gate that never fails — Railway proceeds, the deploy
succeeds, and the corpus stays whatever it was. So a failure returns non-zero, and the
`__main__` guard hands that to the process.

**The report goes into `extra={…}`, not into the message.** Railway blanks the `message`
field of a parsed JSON log and keeps the structured fields, and this is the only place a
deploy says what ingestion actually did.

**No CLI framework, and no corpus logic.** This is a one-shot module invocation: build a
session and an embedder, call `ingest_corpus`, commit. The loader, the `content_hash`
identity, the deletion rule and the idempotence all live in the use case, and this module
imports none of them — a test asserts that, because a second implementation of ingestion
would be one nothing has ever measured.
"""

from __future__ import annotations

import asyncio
import logging

from careerhq.application.ingest_corpus import IngestionReport, ingest_corpus
from careerhq.config import get_settings
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.embeddings import get_embedding_source
from careerhq.infrastructure.logging import configure_logging

logger = logging.getLogger("careerhq.ingest")


async def _ingest() -> IngestionReport:
    """One session, one transaction, committed here.

    **The commit belongs to this module.** `ingest_corpus` deliberately leaves the
    transaction to its caller — the discipline every use case in this project follows — so
    a command that ran it and exited would report a perfect ingestion, log a full report,
    exit 0 and change nothing.
    """
    async with get_session_factory()() as session:
        report = await ingest_corpus(session, embedder=get_embedding_source())
        await session.commit()
        return report


async def run() -> int:
    """Ingest the corpus and decide the exit code. **All of the behaviour is here.**

    Separate from `main` so the exit code is reachable from a test without a second
    process: `asyncio.run` cannot be called from inside a running loop, and a command
    whose only entry point is synchronous can only be tested by spawning something. It is
    still tested that way once — but as the *process* claim, not as every claim.
    """
    try:
        report = await _ingest()
    except Exception:
        # Broad on purpose. Whatever went wrong — an unreachable database, a corpus file
        # that no longer parses, a model that will not load — the deploy must not
        # proceed, and the cause has to be in the output an operator gets.
        logger.exception("corpus ingestion failed")
        return 1

    logger.info(
        "corpus ingestion finished",
        extra={
            "documents_created": report.documents_created,
            "documents_updated": report.documents_updated,
            "chunks_created": report.chunks_created,
            "chunks_deleted": report.chunks_deleted,
            "changed": report.changed,
        },
    )
    return 0


def main() -> int:
    """The process boundary, and deliberately nothing else.

    Logging is configured here because nothing else has: this runs as its own process,
    not under the API, so without it the report would go to a default handler in a format
    the log pipeline does not parse. Configured **here rather than in `run`** so a test
    holding the root handlers keeps them.
    """
    configure_logging(get_settings().log_level)
    return asyncio.run(run())


if __name__ == "__main__":
    # `SystemExit`, with the value — a guard that called `main()` and discarded what it
    # returned would exit 0 on every failure, which is precisely the gate this command
    # exists to be.
    raise SystemExit(main())
