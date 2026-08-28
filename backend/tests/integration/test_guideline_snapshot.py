"""T028 — the citation a run recorded, and why it is a snapshot rather than a pointer.

FR-011 and FR-012 together make one claim: *what a run was advised must stay resolvable
after the corpus changes*. A pointer cannot satisfy it. The corpus is deliberately not
insert-only — the review deleted two unsupported ATS claims (T026) — so a citation that
stored only `content_hash` would resolve to nothing the moment a rule was corrected, and
the run's record would read as if it had been advised by a rule that no longer exists.

**The snapshot is written from the retrieved objects, never from `TailoringState`.** The
state key stays `list[dict[str, str]]`: it is the prompt-facing representation and its
two keys are all a node may see (FR-003, asserted at T018). Persistence needs seven
fields, and putting them in state to get them persisted would push retrieval detail
through every node to reach the one line that writes a row.

**A static fallback records no citation.** It has none — `StaticGuidelines` is a
constant, not a corpus chunk — and emitting empty strings for the citation fields would
produce a record indistinguishable from the drift T016 exists to detect.
"""

from __future__ import annotations

import hashlib
import math
import pathlib
import re
import uuid
import zlib
from collections.abc import Sequence

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.guidelines import GuidelineQuery, StaticGuidelines
from careerhq.application.ingest_corpus import ingest_corpus
from careerhq.application.retrieved_guidelines import RetrievedGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import RunStatus, TailoringRun
from careerhq.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

#: The seven fields `data-model.md` requires of a recorded citation, plus the rendered
#: `source` the API has exposed since slice 005 and the frontend types against.
_CITATION_FIELDS = {
    "document_slug",
    "document_version",
    "content_hash",
    "locator",
    "text",
    "market",
    "trust_level",
}


class LexicalEmbedder:
    """Content-derived vectors — the same double T013 uses, and for the same reason.

    `zlib.crc32` rather than `hash()`, which is salted per process.
    """

    @property
    def dimensions(self) -> int:
        return 384

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * 384
        for token in re.findall(r"[a-z]{3,}", text.lower()):
            vector[zlib.crc32(token.encode()) % 384] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed_passages(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> Sequence[float]:
        return self._vector(text)


_DOC = """---
slug: t028-fixture
source_type: resume_best_practices
market: global
trust_level: vendor_documented
role_family: any
seniority: any
resume_section: any
topic: [experience-bullets]
origin_source_ids: [S-007]
---

# A snapshot fixture

Preamble prose that must never become a chunk.

## Rules

- Lead each bullet with the outcome the work produced, because a reader scanning a
  column of bullets reads the first few words of each and nothing else.

- State the scale a system operated at where the profile records it, because scale is
  what distinguishes comparable-sounding work at two different employers.
"""


@pytest.fixture
def corpus_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "corpus"
    (root / "universal").mkdir(parents=True)
    (root / "universal" / "t028-fixture.md").write_text(_DOC)
    return root


def _plan() -> dict[str, object]:
    return {
        "emphasise": [
            {
                "what": "Six years owning a payments platform",
                "serves_requirement": "5+ years backend services",
            }
        ],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with platform ownership at scale.",
    }


def _draft(bullet_id: uuid.UUID) -> dict[str, object]:
    return {
        "items": [
            {
                "source_item_id": str(bullet_id),
                "source_kind": "experience_bullet",
                "position": 0,
                "included": True,
                "text": "Owned the payments platform end to end.",
                "reason": "Leads with the posting's primary requirement.",
            }
        ]
    }


def _script(bullet: uuid.UUID) -> dict[str, list[dict[str, object]]]:
    """A clean first-pass run: one plan, one draft, one review that clears."""
    return {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet)],
        "tailor_review": [{"confidence": 91, "findings": []}],
    }


async def _run(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    sub: str,
    guidelines: object,
) -> TailoringRun:
    seeded = await seed_tailorable(db_session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_script(seeded.bullet_ids[0])),
            guidelines=guidelines,  # type: ignore[arg-type]
        )
        await session.commit()

    run = await db_session.scalar(
        sa.select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
    )
    assert run is not None
    await db_session.refresh(run)
    return run


async def test_a_run_records_every_citation_field_for_the_guidance_it_used(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    corpus_dir: pathlib.Path,
) -> None:
    """FR-011. The full recorded citation, from the retrieved objects.

    The count is asserted against what retrieval actually returns rather than against a
    literal: a snapshot of the right shape covering the wrong number of guidelines is the
    failure this project has shipped four times under a different name.
    """
    embedder = LexicalEmbedder()
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)
    expected = await source.guidelines_for(
        context=GuidelineQuery(role_title="Senior Backend Engineer", requirements=())
    )
    assert len(expected) == 2, f"fixture corpus should yield 2 rules, got {len(expected)}"

    run = await _run(
        db_session,
        session_factory,
        sub="snapshot-fields",
        guidelines=RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500),
    )

    recorded = run.guidelines_used
    assert recorded is not None and len(recorded) == len(expected)

    for entry in recorded:
        assert _CITATION_FIELDS <= set(entry), (
            f"missing citation fields: {sorted(_CITATION_FIELDS - set(entry))}"
        )
        assert entry["source"], "the rendered citation the API exposes was dropped"
        assert entry["document_slug"] == "t028-fixture"
        assert entry["document_version"] == 1
        assert entry["market"] == "global"
        assert entry["trust_level"] == "vendor_documented"
        assert hashlib.sha256(entry["text"].encode()).hexdigest() == entry["content_hash"], (
            "the persisted text does not verify against the persisted hash"
        )

    assert {e["locator"] for e in recorded} == {"rule 1", "rule 2"}


async def test_the_recorded_citation_survives_a_later_corpus_edit(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    corpus_dir: pathlib.Path,
) -> None:
    """FR-011 and FR-012, the claim that makes this a snapshot and not a pointer.

    After the corpus moves on, three things must all hold at once: the recorded row is
    **byte-for-byte what it was**, its hash **no longer resolves in the corpus** — so the
    drift is detectable rather than silent — and the recorded text still verifies against
    the recorded hash, which is what "remains resolvable" means for a rule that is gone.
    """
    embedder = LexicalEmbedder()
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    run = await _run(
        db_session,
        session_factory,
        sub="snapshot-frozen",
        guidelines=RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500),
    )
    before = run.guidelines_used
    assert before is not None
    cited = next(e for e in before if e.get("locator") == "rule 1")
    assert {"text", "content_hash"} <= set(cited), (
        "a record that stores no text is a pointer, not a snapshot: after the corpus "
        "moves on there is nothing left to resolve"
    )

    path = corpus_dir / "universal" / "t028-fixture.md"
    path.write_text(_DOC.replace("the outcome the work produced", "the outcome it produced"))
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    await db_session.refresh(run)
    assert run.guidelines_used == before, "a corpus edit rewrote what a past run was advised"

    surviving = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.content_hash == cited["content_hash"])
    )
    assert surviving == 0, "the edited rule kept its hash; the drift would be undetectable"
    assert hashlib.sha256(cited["text"].encode()).hexdigest() == cited["content_hash"]


async def test_a_static_fallback_records_no_citation_it_cannot_support(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The static rubric is a constant, not a corpus chunk.

    Emitting `content_hash: ""` to keep the shape uniform would write a record that fails
    its own verification — indistinguishable from the tampering T016 exists to catch. The
    honest record is the two fields it actually has.
    """
    run = await _run(
        db_session, session_factory, sub="snapshot-static", guidelines=StaticGuidelines()
    )

    recorded = run.guidelines_used
    static = list(await StaticGuidelines().guidelines_for(context=GuidelineQuery("x", ())))
    assert recorded is not None and len(recorded) == len(static) > 0

    for entry in recorded:
        assert set(entry) == {"text", "source"}, (
            f"the static rubric recorded citation fields it has no basis for: {sorted(entry)}"
        )


@pytest.fixture(autouse=True)
async def _clear_corpus(db_session: AsyncSession) -> object:
    """The knowledge tables are not in conftest's truncation list and these tests commit.

    Without this, an ingested corpus outlives the test and the next file's empty-corpus
    fallback assertion finds 79 chunks.
    """
    yield None
    await db_session.execute(sa.delete(KnowledgeChunk))
    await db_session.execute(sa.delete(KnowledgeDocument))
    await db_session.commit()


# --------------------------------------------------------------------------------------
# OQ-006-A — decided 2026-08-28: **a run that retrieved guidance records it, even if the
# run then fails.**
#
# Implemented by snapshotting **immediately after retrieval, before the graph**, not by
# adding a branch to the failure path. Three of the four things Principle V names —
# "inputs, model configuration, token usage, and cost" — already survive a failure
# because `match_analysis_id`, `finalisation_rules_version` and `model_config_used` are
# written at run creation. `guidelines_used` was the only input written at the end, on
# the success path alone, which was an accident of when the field was added rather than a
# decision. Writing it where the guidance first exists removes the asymmetry instead of
# adding a fourth special case, and removes a branch rather than adding one.
#
# **The two failure classes are different and both are asserted.** A failure *before*
# retrieval leaves `NULL` — nothing was fetched, and `NULL` means unknowable, the
# convention `review_confidences` already sets two fields away. A failure *after*
# retrieval records the full citation, because those guidelines were rendered into the
# Plan prompt and billed for. **`[]` is never written for either**: an empty list asserts
# that a run was advised nothing, which is a different claim from not knowing.
# --------------------------------------------------------------------------------------


async def _run_expecting_failure(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    sub: str,
    guidelines: object,
    script: dict[str, list[dict[str, object]]] | None = None,
) -> TailoringRun:
    """A run that fails inside the graph: an empty script exhausts on the first call.

    `ScriptedSeam` raises rather than repeating its last answer, which is what makes an
    in-graph failure expressible at all without reaching for a mock.
    """
    seeded = await seed_tailorable(db_session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=script or {}),
            guidelines=guidelines,  # type: ignore[arg-type]
        )
        await session.commit()

    run = await db_session.scalar(
        sa.select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
    )
    assert run is not None
    await db_session.refresh(run)
    assert run.status == RunStatus.FAILED, "this test needs a failed run and did not get one"
    return run


async def test_a_run_that_fails_after_retrieval_still_records_what_it_was_advised(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    corpus_dir: pathlib.Path,
) -> None:
    """OQ-006-A. The guidance was rendered into the Plan prompt and billed for.

    The precedent is `UsageRecorder`, verbatim: *a run that reads as free is worse than
    one that reads as unrecorded, because nobody investigates a free run.* A failed run
    that reads as **unguided** is the same defect in a different column.
    """
    embedder = LexicalEmbedder()
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    run = await _run_expecting_failure(
        db_session,
        session_factory,
        sub="snapshot-failed",
        guidelines=RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500),
    )

    recorded = run.guidelines_used
    assert recorded is not None, "a failed run recorded no guidance it demonstrably had"
    assert recorded != [], "`[]` asserts the run was advised nothing; it was advised two rules"
    assert len(recorded) == 2

    for entry in recorded:
        assert _CITATION_FIELDS <= set(entry), (
            f"the failure path recorded a partial citation: {sorted(set(entry))}"
        )
        assert hashlib.sha256(entry["text"].encode()).hexdigest() == entry["content_hash"]


async def test_a_run_that_fails_before_retrieval_records_null_not_an_empty_list(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    corpus_dir: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the decision, and the half that keeps the first one honest.

    Nothing was retrieved, so there is nothing to record. **`NULL` means unknowable** —
    the convention `review_confidences` sets two fields away in the same table — and
    writing `[]` here would assert that the run was advised nothing, which is a claim
    about a retrieval that never happened.

    The failure is injected at `_render_master`, which runs **before** the retrieval call
    and after the run row exists: a real pre-retrieval failure rather than a simulated one.
    """
    embedder = LexicalEmbedder()
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    def _explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError("the profile could not be rendered")

    monkeypatch.setattr("careerhq.application.tailor_resume._render_master", _explode)

    run = await _run_expecting_failure(
        db_session,
        session_factory,
        sub="snapshot-early",
        guidelines=RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500),
    )

    assert run.guidelines_used is None, (
        f"a run that never retrieved recorded {run.guidelines_used!r}; NULL means unknowable"
    )


async def test_a_later_failure_neither_removes_nor_replaces_the_snapshot(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    corpus_dir: pathlib.Path,
) -> None:
    """The snapshot is written once, where the guidance exists, and nothing later edits it.

    Asserted by comparing a failed run's record against what retrieval returns for the
    same corpus — so a failure path that wrote a *different* or truncated set would be
    caught, not only one that wrote nothing.
    """
    embedder = LexicalEmbedder()
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)
    expected = await source.guidelines_for(
        context=GuidelineQuery(role_title="Senior Backend Engineer", requirements=())
    )

    run = await _run_expecting_failure(
        db_session,
        session_factory,
        sub="snapshot-intact",
        guidelines=RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500),
    )

    recorded = run.guidelines_used
    assert recorded is not None
    assert [e["content_hash"] for e in recorded] == [
        g.content_hash  # type: ignore[attr-defined]
        for g in expected
    ], "the failed run's snapshot is not the set retrieval returned"


async def test_a_failed_runs_snapshot_survives_a_later_corpus_edit(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    corpus_dir: pathlib.Path,
) -> None:
    """FR-011 and FR-012 apply to a failed run's record exactly as they do to a
    successful one — otherwise the record OQ-006-A decided to keep would be one the
    corpus could silently rewrite, which is worth less than not keeping it."""
    embedder = LexicalEmbedder()
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    run = await _run_expecting_failure(
        db_session,
        session_factory,
        sub="snapshot-failed-frozen",
        guidelines=RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500),
    )
    before = run.guidelines_used
    assert before is not None
    cited = next(e for e in before if e.get("locator") == "rule 1")

    path = corpus_dir / "universal" / "t028-fixture.md"
    path.write_text(_DOC.replace("the outcome the work produced", "the outcome it produced"))
    await ingest_corpus(db_session, embedder=embedder, root=corpus_dir)
    await db_session.commit()

    await db_session.refresh(run)
    assert run.guidelines_used == before, "a corpus edit rewrote what a failed run was advised"

    surviving = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.content_hash == cited["content_hash"])
    )
    assert surviving == 0
    assert hashlib.sha256(cited["text"].encode()).hexdigest() == cited["content_hash"]
