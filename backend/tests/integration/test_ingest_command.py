"""T050 — `python -m careerhq.ingest`, the caller `ingest_corpus` never had.

**Without this the whole slice does nothing.** Retrieval is wired, correct and tested, and
until now nothing outside the test suite has ever written a chunk — so a deployed backend
retrieved against an empty corpus and fell back to the static rubric on every run,
recording that it did (FR-009) and looking perfectly healthy while doing it.

**The decision this implements was taken at OQ-006-C and is not reopened here.** Ingestion
runs **pre-deploy**, after `alembic upgrade head`, joined by `&&` because the order is
load-bearing: `knowledge_chunks` has to exist before anything writes to it. The startup
hook is ruled out — it would pay a model load on every container start and let two
replicas booting together race `uq_knowledge_chunks_document_content`, and both failures
scale with replica count, so the configuration that produces them is a scaling change
nobody would connect to ingestion.

**The one thing a command like this gets wrong is the exit code.** A CLI that catches an
exception, logs it and exits 0 is the exact shape of a gate that never fails: the
pre-deploy step passes, the deploy proceeds, and the corpus is silently whatever it was
before. So the non-zero exit is asserted twice — once through `main()` and once through a
real subprocess, because only the second proves what the platform will actually observe.
"""

from __future__ import annotations

import ast
import os
import pathlib
import shlex
import subprocess
import sys
import tomllib
from collections.abc import AsyncIterator, Sequence

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq import ingest as ingest_command
from careerhq.application.ingest_corpus import IngestionReport
from careerhq.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument
from careerhq.infrastructure.corpus import loader as corpus_loader

pytestmark = pytest.mark.asyncio

BACKEND = pathlib.Path(__file__).resolve().parents[2]
REPO = BACKEND.parent

#: Read at import time. Every test here carries the module-wide `asyncio` mark, and
#: `pathlib` inside an async function is refused by ASYNC240 — read once rather than
#: suppress the rule.
_COMMAND_SOURCE = (BACKEND / "src" / "careerhq" / "ingest.py").read_text()


class _Embedder:
    """Deterministic vectors, no model. The command's wiring is what is under test."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def dimensions(self) -> int:
        return 384

    async def embed_passages(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls += 1
        return [[float((hash(t) % 1000) + i) / 1000.0 for i in range(384)] for t in texts]

    async def embed_query(self, text: str) -> Sequence[float]:  # pragma: no cover
        raise AssertionError("ingestion must never embed a query")


@pytest_asyncio.fixture(autouse=True)
async def _empty_corpus(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Clear the knowledge tables around every test in this file.

    **`conftest`'s truncation does not reach them, and cannot.** It truncates
    `professional_profiles` and `users` and lets `CASCADE` do the rest, which covers
    everything a user owns — and the corpus is deliberately *not* owned by a user (D1:
    one curated corpus, no per-user tables). Every other corpus test writes through a
    rolled-back session or a `tmp_path` corpus, so nothing has needed this before; this
    is the first test that ingests the **real** corpus and **commits** it, and rows left
    behind would silently become the fixture for every retrieval test that runs after.
    """

    async def _clear() -> None:
        async with session_factory() as session:
            await session.execute(sa.text("TRUNCATE knowledge_documents, knowledge_chunks CASCADE"))
            await session.commit()

    await _clear()
    yield
    await _clear()


@pytest.fixture
def wired(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> _Embedder:
    """The command, pointed at the test database and a fake embedder.

    Both boundaries are replaced at the names **the command itself resolves**, not at the
    modules they come from: that is what makes a command which built its own session or
    its own embedder somewhere else fail rather than quietly use the real one.
    """
    embedder = _Embedder()
    monkeypatch.setattr(ingest_command, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(ingest_command, "get_embedding_source", lambda: embedder)
    return embedder


async def _counts(session: AsyncSession) -> tuple[int, int]:
    documents = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeDocument))
    chunks = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeChunk))
    return int(documents or 0), int(chunks or 0)


# ======================================================================================
# The command
# ======================================================================================


async def test_the_command_ingests_the_corpus_and_commits(
    wired: _Embedder, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Exit 0, and the rows are visible to a session that never saw the write.

    **Committing is the point.** `ingest_corpus` deliberately leaves the transaction to
    its caller, so a command that ran it and exited without committing would report a
    perfect ingestion, log a full report, exit 0, and change nothing — indistinguishable
    from success in every observable except the database.
    """
    assert await ingest_command.run() == 0

    async with session_factory() as check:
        documents, chunks = await _counts(check)
    assert documents > 0, "the command exited 0 without writing anything"
    assert chunks > 0
    assert wired.calls > 0, "nothing was embedded, so nothing was really ingested"


async def test_re_running_an_unchanged_corpus_changes_nothing_and_embeds_nothing(
    wired: _Embedder, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T026's property, preserved through the command rather than assumed to survive it.

    Idempotence is measured in **embedding calls**, not only in row counts: a second run
    that inserts nothing but re-embeds everything has cost what the first one did, and a
    pre-deploy step that expensive is one somebody eventually removes.
    """
    assert await ingest_command.run() == 0
    async with session_factory() as check:
        first = await _counts(check)
    embedded_once = wired.calls

    assert await ingest_command.run() == 0

    async with session_factory() as check:
        assert await _counts(check) == first, "a second run changed the corpus"
    assert wired.calls == embedded_once, (
        f"the second run embedded again ({wired.calls - embedded_once} extra calls)"
    )


async def test_a_failing_ingestion_exits_non_zero(
    wired: _Embedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the pre-deploy placement buys anything.

    If this returns 0, Railway proceeds: the deploy succeeds, the corpus is whatever it
    was, and the failure is a line in a log nobody reads.
    """

    async def _boom(*args: object, **kwargs: object) -> IngestionReport:
        raise RuntimeError("the corpus is unreadable")

    monkeypatch.setattr(ingest_command, "ingest_corpus", _boom)

    assert await ingest_command.run() != 0


async def test_a_failure_is_reported_rather_than_swallowed(
    wired: _Embedder, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-zero exit says *that* it failed; the log has to say *what* failed.

    The exception text and its type both reach the record — an operator reading a blocked
    deploy has the command's output and nothing else, and "ingestion failed" without a
    cause turns a one-line fix into an investigation.
    """

    async def _boom(*args: object, **kwargs: object) -> IngestionReport:
        raise RuntimeError("the corpus is unreadable")

    monkeypatch.setattr(ingest_command, "ingest_corpus", _boom)

    with caplog.at_level("ERROR"):
        assert await ingest_command.run() != 0

    failures = [r for r in caplog.records if r.levelname == "ERROR"]
    assert failures, "the failure was swallowed"
    assert failures[0].exc_info is not None, "the traceback was discarded"
    assert "the corpus is unreadable" in str(failures[0].exc_info[1])


async def test_a_failure_commits_nothing(
    wired: _Embedder,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A partial corpus is worse than none: retrieval would answer from half a rulebook.

    The failure is raised *after* the real ingestion has written its rows, which is the
    case that matters — an exception before anything happens proves nothing about the
    transaction.
    """
    real = ingest_command.ingest_corpus

    async def _write_then_fail(session: AsyncSession, **kwargs: object) -> IngestionReport:
        await real(session, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("interrupted after writing")

    monkeypatch.setattr(ingest_command, "ingest_corpus", _write_then_fail)

    assert await ingest_command.run() != 0

    async with session_factory() as check:
        assert await _counts(check) == (0, 0), "a failed ingestion left rows behind"


async def test_the_report_reaches_the_log_as_structured_fields(
    wired: _Embedder, caplog: pytest.LogCaptureFixture
) -> None:
    """`extra={…}`, not a formatted sentence.

    **Railway blanks the `message` field of a parsed JSON log** and keeps the structured
    ones, so a report interpolated into the message is a report that does not exist in
    production. This is the one place the deploy tells anyone what ingestion did.
    """
    with caplog.at_level("INFO"):
        assert await ingest_command.run() == 0

    # **Scoped to this command's own logger, and a drill is why.** `ingest_corpus` already
    # logs the same fields under `careerhq.corpus`, so a version of this test that
    # searched every record passed happily against a command whose report was interpolated
    # into a message string — it was reading the use case's record and calling it the
    # command's. The claim is about what *this* module emits.
    reports = [
        r for r in caplog.records if r.name == "careerhq.ingest" and hasattr(r, "chunks_created")
    ]
    assert reports, (
        "the command's own ingestion report never reached a log record as fields; "
        f"it logged {[r.getMessage() for r in caplog.records if r.name == 'careerhq.ingest']}"
    )
    record = reports[-1]
    assert record.chunks_created > 0
    for field in (
        "documents_created",
        "documents_updated",
        "chunks_deleted",
        "changed",
        # The presence counts are part of the deploy's record, not a debugging extra:
        # they are the only fields that distinguish an unchanged corpus from an absent
        # one, and Railway keeps structured fields while blanking the message.
        "chunks_expected",
        "chunks_present",
    ):
        assert hasattr(record, field), f"{field} is missing from the structured report"


async def test_a_corpus_missing_from_the_image_exits_non_zero_and_commits_nothing(
    wired: _Embedder,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """The outcome check, end to end: the real command, the real use case, the real loader.

    **This is the failure `75cd8ea` shipped, in the form still reachable after T048.** That
    deploy never ran ingestion at all, and the `preDeployCommand` test now guards the
    ordering — but nothing guarded the *result*. A corpus absent from the image (a
    `.dockerignore` edit, a moved directory) still reaches this command, still finds
    nothing to do, and without the verification still reports `0/0/0/0` and exits **0**,
    letting Railway promote a version whose retrieval silently falls back to the static
    rubric.

    **`CORPUS_ROOT` is repointed rather than `load_corpus` replaced**, so the loader under
    test is the real one: substituting it would prove only that a double returns what it
    was told to.
    """
    empty = tmp_path / "image-without-a-corpus"
    empty.mkdir()
    monkeypatch.setattr(corpus_loader, "CORPUS_ROOT", empty)

    assert await ingest_command.run() == 1, (
        "an empty corpus exited 0; Railway would promote a deployment with no guidance"
    )

    async with session_factory() as check:
        assert (await _counts(check)) == (0, 0)
    assert wired.calls == 0, "an unverifiable ingestion still embedded"


async def test_the_command_calls_the_shared_ingestion_path(
    wired: _Embedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One implementation of ingestion, and the command is not a second one.

    Asserted by replacing `ingest_corpus`: if the command still writes, it is doing the
    work itself, and T026's idempotence, the `content_hash` identity and the deletion
    rule all apply to code nobody tested. Stated structurally too — the module imports no
    corpus loader and no knowledge model, so it *cannot* reimplement any of it.
    """
    calls: list[object] = []

    async def _spy(session: AsyncSession, **kwargs: object) -> IngestionReport:
        calls.append(kwargs.get("embedder"))
        return IngestionReport()

    monkeypatch.setattr(ingest_command, "ingest_corpus", _spy)

    assert await ingest_command.run() == 0
    assert calls == [wired], "the command did not hand its own embedder to the use case"

    # **Parsed, not grepped.** The module's own docstring explains `content_hash` and the
    # deletion rule, and a text search would count that explanation as a violation — the
    # same distinction `test_architecture.py` draws between a mention and a read.
    tree = ast.parse(_COMMAND_SOURCE)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    assert imported, "nothing was parsed; the check examined nothing"
    assert "careerhq.application.ingest_corpus.ingest_corpus" in imported, (
        "the command does not import the shared ingestion path at all"
    )
    # The *internals* — the loader and the models. `application.ingest_corpus` is the
    # seam and is required; what must not be reachable is the material it is built from,
    # because that is what a second implementation would need.
    internals = ("infrastructure.corpus", "models.knowledge", "load_corpus", "Knowledge")
    offenders = {name for name in imported if any(w in name for w in internals)}
    assert not offenders, (
        f"the command imports corpus internals and could reimplement ingestion: {sorted(offenders)}"
    )


def test_main_hands_the_exit_code_to_the_process() -> None:
    """`main` is the process boundary and holds no behaviour of its own.

    Read rather than executed, because executing it means `asyncio.run` and therefore a
    second process — which the test below does once, for the claim that needs it. What
    matters here is that the two lines are the two lines: configure logging, and return
    what `run` decided. A `main` that computed its own exit code would be a second
    implementation of the only rule this command has.
    """
    body = _COMMAND_SOURCE[_COMMAND_SOURCE.index("def main() -> int:") :]

    assert "return asyncio.run(run())" in body, "main does not return what run decided"
    assert "raise SystemExit(main())" in body, (
        "the __main__ guard discards the exit code; every failure would exit 0"
    )


def test_the_module_exits_non_zero_when_run_for_real() -> None:
    """`python -m careerhq.ingest`, as a process, because that is what Railway observes.

    `main()` returning 1 is not the same claim: a module with no `__main__` guard, or one
    whose guard ignored the return value, would satisfy every test above and exit **0**
    for the platform. Pointed at a database that is not there, so the failure is real and
    needs no fixture.
    """
    environment = dict(os.environ)
    environment["DATABASE_URL"] = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nothing"

    finished = subprocess.run(
        [sys.executable, "-m", "careerhq.ingest"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert finished.returncode != 0, (
        "a failed ingestion exited 0; the pre-deploy step would let the deploy proceed:\n"
        f"{finished.stdout[-800:]}{finished.stderr[-800:]}"
    )


# ======================================================================================
# Where it is wired, and where it deliberately is not
# ======================================================================================


def test_the_pre_deploy_command_migrates_before_it_ingests() -> None:
    """The order, the `&&`, and the shell that makes the `&&` mean anything.

    Read out of the file rather than trusted: this is the whole of the deployment
    behaviour, it lives in one string, and a reordering would fail on the first deploy
    against a fresh database — with an error naming a missing table, which reads as a
    migration problem rather than an ordering one.

    **Parsed with `tomllib`, not by stripping quotes** (T048). The previous version did
    `line.split("=", 1)[1].strip().strip('"')`, which silently cannot unwrap a TOML
    *literal* (single-quoted) string — so it was reading the quoting as part of the
    command. Asking the TOML parser what the value is means this test checks the command
    Railway is actually configured with rather than a substring of the file.

    **The `/bin/sh -c` wrapper is asserted because it is load-bearing, not stylistic.**
    `preDeployCommand` is a *single* command — Railway's schema types it as a string or a
    one-element array — and under `builder = "DOCKERFILE"` nothing interprets an operator,
    so an unwrapped `a && b` runs only `a`. That is not hypothetical: deployment `75cd8ea`
    migrated cleanly, reported SUCCESS, and never ran ingestion, leaving production with an
    empty corpus while every health check passed. Dropping the wrapper would restore
    exactly that silent half-failure, which is why it is a guarantee rather than a detail.
    """
    config = tomllib.loads((BACKEND / "railway.toml").read_text())
    command = config["deploy"]["preDeployCommand"]
    assert isinstance(command, str), f"expected a string command, got {type(command)}"

    # The shell is invoked explicitly, and the whole chain is one argument to it —
    # `shlex` rather than a substring search, so `/bin/sh` mentioned in a comment or
    # appended after the chain could not satisfy this.
    argv = shlex.split(command)
    assert argv[:2] == ["/bin/sh", "-c"], f"the pre-deploy command invokes no shell: {argv}"
    assert len(argv) == 3, f"the chain must be one argument to the shell, got {argv}"

    chain = argv[2]
    assert "&&" in chain, "a separator that runs both regardless is not an ordering"
    assert chain.index("alembic upgrade head") < chain.index("careerhq.ingest"), chain


def test_ingestion_is_not_in_the_entrypoint() -> None:
    """Ruled out at OQ-006-C, and this is what keeps it ruled out.

    A stale *schema* breaks the application, so migrations belong here; a stale *corpus*
    does not — retrieval falls back to the static rubric and records that it did (FR-009).
    Putting ingestion here would buy safety it does not need and pay a model load on every
    container start, plus the multi-replica race the pre-deploy placement exists to avoid.

    **The migration line is asserted too**, so this cannot pass by reading an empty or
    missing file — the failure mode where a gate examines nothing and reports success.
    """
    entrypoint = (BACKEND / "entrypoint.sh").read_text()

    assert "alembic upgrade head" in entrypoint, "this test is reading the wrong file"
    assert "careerhq.ingest" not in entrypoint
    assert "ingest" not in entrypoint


def test_ingestion_is_not_run_at_application_startup() -> None:
    """The same rule, at the other place it could be reintroduced as a convenience."""
    startup = (BACKEND / "src" / "careerhq" / "main.py").read_text()

    assert "ingest" not in startup, "ingestion was added to application startup"


def test_the_local_command_is_documented() -> None:
    """An operator command nobody has written down is an operator command nobody runs.

    The corpus is edited by hand, and the files and the database disagreeing about what
    guidance exists is exactly the drift `content_hash` exists to detect — arriving by
    process rather than by bug.
    """
    local = "docker compose exec backend python -m careerhq.ingest"

    readme = (REPO / "README.md").read_text()
    quickstart = (REPO / "specs" / "006-document-retrieval" / "quickstart.md").read_text()

    assert local in readme, "the local ingestion command is not in README.md"
    assert local in quickstart, "the local ingestion command is not in quickstart.md"
