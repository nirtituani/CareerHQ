"""T030 — retrieval wired into a real run, once, before the graph.

Three claims, and none of them is about retrieval's own behaviour — that is T013-T029.
This is composition:

1. **FR-029: once per run.** A seven-call run must ask the `GuidelineSource` exactly one
   question. Retrieval inside the loop would re-embed and re-rank on every revision, for
   a query that has not changed, and slice 007 would be comparing runs that consulted
   different guidance at different points.
2. **The selector is honoured.** `guideline_source` chooses the implementation at the
   005/006 seam — the API layer, which is where composition lives so `application/`
   imports no infrastructure.
3. **`warm_up()` has a real caller.** Deferred from T008 because nothing held an embedder
   until now. Without it the first run of a cold process pays seconds of model load
   inside the figure T029 measures, and SC-007 becomes unmeasurable rather than merely
   worse — which is why this task, not T029, is where SC-007 becomes measurable at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.api.routes.tailoring import build_guideline_source
from careerhq.application.guidelines import Guideline, GuidelineQuery, StaticGuidelines
from careerhq.application.retrieved_guidelines import RetrievedGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.config import Settings, get_settings
from careerhq.domain.models import RunStatus, TailoringRun
from careerhq.main import lifespan
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


class CountingGuidelines:
    """Wraps a real source and counts the questions asked of it.

    Counting **calls**, not chunks: FR-029 is about how many times the workflow consults
    guidance, and a source that returned the right rules twice would satisfy every other
    test in this slice while doubling the embedding work of a revised run.
    """

    def __init__(self) -> None:
        self._inner = StaticGuidelines()
        self.calls: list[GuidelineQuery] = []

    async def guidelines_for(self, *, context: GuidelineQuery) -> Sequence[Guideline]:
        self.calls.append(context)
        return await self._inner.guidelines_for(context=context)


def _plan() -> dict[str, object]:
    return {
        "emphasise": [
            {
                "action": "keep",
                "what": "Six years on payments",
                "serves_requirement": "5+ years backend services",
            }
        ],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with platform ownership at scale.",
    }


def _draft(bullet_id: uuid.UUID, text: str) -> dict[str, object]:
    return {
        "items": [
            {
                "source_item_id": str(bullet_id),
                "source_kind": "experience_bullet",
                "position": 0,
                "included": True,
                "text": text,
                "reason": "Leads with the posting's primary requirement.",
            }
        ]
    }


def _clean_script(bullet: uuid.UUID) -> dict[str, list[dict[str, object]]]:
    """One plan, one draft, one review that clears. The shortest path."""
    return {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet, "Owned the payments platform end to end.")],
        "tailor_review": [{"confidence": 91, "findings": []}],
    }


def _exhausting_script(bullet: uuid.UUID) -> dict[str, list[dict[str, object]]]:
    """Three review passes and two revisions — the full budget, seven calls.

    The longest path the graph has. If guidance were fetched per node rather than per
    run, this is the run that would show it.
    """
    objection = [{"kind": "uncovered", "detail": "Kubernetes is never addressed."}]
    return {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet, "First attempt.")],
        "tailor_revise": [_draft(bullet, "Second attempt.")],
        "tailor_revise_escalated": [_draft(bullet, "Third attempt.")],
        "tailor_review": [
            {"confidence": 40, "findings": objection},
            {"confidence": 45, "findings": objection},
            {"confidence": 50, "findings": objection},
        ],
    }


async def test_guidance_is_retrieved_exactly_once_for_a_run_that_revises_twice(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-029, on the longest path the graph has."""
    seeded = await seed_tailorable(db_session, sub="wiring-once", email="wiring-once@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    guidelines = CountingGuidelines()
    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_exhausting_script(seeded.bullet_ids[0])),
            guidelines=guidelines,  # type: ignore[arg-type]
        )
        await session.commit()

    run = await db_session.scalar(
        sa.select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
    )
    assert run is not None
    await db_session.refresh(run)
    assert run.status == RunStatus.SUCCEEDED, f"the run did not complete: {run.failure_reason}"
    assert run.attempts == 2, f"expected the full revision budget, got {run.attempts}"

    assert len(guidelines.calls) == 1, (
        f"guidance was fetched {len(guidelines.calls)} times for one run; FR-029 says once"
    )


def _settings(**overrides: object) -> Settings:
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def test_the_selector_chooses_retrieval(db_session: AsyncSession) -> None:
    """The 005/006 seam, and the only line that decides which slice is live."""
    source = build_guideline_source(db_session, _settings(guideline_source="retrieval"))

    assert isinstance(source, RetrievedGuidelines)


async def test_the_selector_can_still_choose_the_static_rubric(db_session: AsyncSession) -> None:
    """`static` is the documented FR-009 fallback, not dead code.

    It is also the only way to take the SC-008 cost baseline in the same session as the
    retrieval measurement, which is what makes that comparison mean anything.
    """
    source = build_guideline_source(db_session, _settings(guideline_source="static"))

    assert isinstance(source, StaticGuidelines)


async def test_the_wired_source_uses_the_configured_ceiling(db_session: AsyncSession) -> None:
    """FR-014's limit is configuration, and a hard-coded 1500 here would silently
    outrank it — the ceiling would look configurable and not be."""
    source = build_guideline_source(
        db_session, _settings(guideline_source="retrieval", retrieval_token_ceiling=900)
    )

    assert isinstance(source, RetrievedGuidelines)
    assert source._ceiling == 900


class RecordingEmbedder:
    def __init__(self, *, fails: bool = False) -> None:
        self.warmed = 0
        self._fails = fails

    async def warm_up(self) -> None:
        self.warmed += 1
        if self._fails:
            raise RuntimeError("weights are missing")


async def test_startup_warms_the_embedder_when_retrieval_is_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T008 deferred this because nothing held an embedder. Something does now.

    Asserted on the model actually being warmed, not on a log line: the whole point is
    that the cost is paid before a request, and only the call proves that.
    """
    embedder = RecordingEmbedder()
    monkeypatch.setattr("careerhq.main.get_embedding_source", lambda: embedder, raising=True)

    app = FastAPI()
    app.state.settings = _settings(guideline_source="retrieval")
    async with lifespan(app):
        pass

    assert embedder.warmed == 1, "startup did not warm the embedding model"


async def test_startup_does_not_warm_the_embedder_when_the_rubric_is_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading 64 MB of weights a static run will never consult is pure startup cost."""
    embedder = RecordingEmbedder()
    monkeypatch.setattr("careerhq.main.get_embedding_source", lambda: embedder, raising=True)

    app = FastAPI()
    app.state.settings = _settings(guideline_source="static")
    async with lifespan(app):
        pass

    assert embedder.warmed == 0


async def test_a_failed_warm_up_does_not_prevent_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """FR-010 decides this, not a preference.

    Retrieval may never fail a tailoring run, so it may certainly never fail the process:
    an embedder that cannot load means every run falls back to the static rubric and
    records that it did, which is a degraded platform rather than no platform.
    """
    embedder = RecordingEmbedder(fails=True)
    monkeypatch.setattr("careerhq.main.get_embedding_source", lambda: embedder, raising=True)

    app = FastAPI()
    app.state.settings = _settings(guideline_source="retrieval")
    async with lifespan(app):
        pass

    assert embedder.warmed == 1
    assert any(
        r.name == "careerhq" and r.levelname == "WARNING" and "embedding" in r.getMessage()
        for r in caplog.records
    ), "a failed warm-up started silently; the first run would pay for the model load"


async def test_an_unrecognised_guideline_source_is_refused_at_configuration() -> None:
    """A typo must not choose an implementation for you.

    The selector is a two-way branch, so *any* unrecognised value would land on one side
    of it silently. `statik` selecting retrieval is the worse direction of the two: it is
    exactly how SC-008's static baseline would be taken against retrieval and reported as
    a comparison. Refused where every other configuration error in this project surfaces
    — at `Settings`, with the field named.
    """
    with pytest.raises(ValidationError) as exc_info:
        _settings(guideline_source="statik")

    assert "guideline_source" in str(exc_info.value)


async def test_every_run_asks_for_israeli_market_guidance(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """OQ-006-B, decided 2026-08-28: **V1 targets the Israeli market on every run.**

    Before this, `market` was never populated and defaulted to `global`, so the FR-038
    precedence pass T027 built and R13 argued for never fired outside its own tests.

    **A stated product decision, not an inference.** Nothing here reads the posting, the
    company's location or the profile to guess a market — inventing an Israeli
    distinction where evidence does not support one is what FR-038 and S-001's
    disposition note both forbid, and a heuristic doing it would be invisible once
    shipped. One named constant, one place to change, and the extension path is a real
    product-level selection rather than a better guess.

    **The port's own default stays `global`**, which is the conservative answer for any
    caller that has not decided. Asserted separately below, because a decision expressed
    by moving a default is a decision nobody can see at the call site.
    """
    seeded = await seed_tailorable(
        db_session, sub="wiring-market", email="wiring-market@example.com"
    )
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    guidelines = CountingGuidelines()
    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_clean_script(seeded.bullet_ids[0])),
            guidelines=guidelines,  # type: ignore[arg-type]
        )
        await session.commit()

    assert len(guidelines.calls) == 1
    assert guidelines.calls[0].market == "israel", (
        f"the run asked for {guidelines.calls[0].market!r} guidance; V1 targets Israel"
    )


async def test_the_port_still_defaults_to_global_for_a_caller_that_has_not_decided() -> None:
    """The V1 market is a decision the *use case* states, not one the port assumes.

    Moving the default would make every future caller Israeli by omission — the same
    invisible-inference failure OQ-006-B was decided to avoid, relocated one layer down.
    """
    assert GuidelineQuery(role_title="anything", requirements=()).market == "global"
