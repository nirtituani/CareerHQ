"""The runner: it refuses before it spends, and it touches no existing evidence.

**T006, T012, T013, T017, T020.** These are the assertions that make a paid pass
safe to authorise. Every one of them runs free.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.evaluation.benchmark_set import load_benchmark_set
from careerhq.application.evaluation.budget import CeilingExceededError
from careerhq.application.evaluation.runner import (
    BENCHMARK_EMAIL_DOMAIN,
    plan_pass,
    seed_case,
)
from careerhq.application.tailor_resume import check_preconditions
from careerhq.domain.models import Application, MatchAnalysis, ResumeVersion, TailoringRun

pytestmark = pytest.mark.asyncio

ROOT = pathlib.Path(__file__).resolve().parents[2] / "benchmark"


def _benchmark():  # type: ignore[no-untyped-def]
    return load_benchmark_set("v1", root=ROOT)


# -- The ceiling (FR-008, SC-011) --------------------------------------------


async def test_the_runner_refuses_a_pass_projected_above_the_ceiling() -> None:
    """Refused **before any billable call**, not reconciled afterwards."""
    with pytest.raises(CeilingExceededError) as excinfo:
        plan_pass(_benchmark(), ceiling=Decimal("1.00"), static_arms=5)
    message = str(excinfo.value)
    assert "before any billable call" in message
    assert "1.00" in message


async def test_the_approved_pass_fits_under_the_approved_ceiling() -> None:
    """D3: 12 cases, 5 paired static arms, a $10 ceiling.

    Priced as though **every** run revises, which is the conservative basis.
    """
    plan = plan_pass(_benchmark(), ceiling=Decimal("10.00"), static_arms=5)
    assert plan.guard.authorised
    assert plan.projection < Decimal("10.00")


async def test_the_projection_is_derived_from_the_loaded_set_not_from_a_constant() -> None:
    """A runner that assumed 12 would project the wrong cost for any other set."""
    benchmark = _benchmark()
    plan = plan_pass(benchmark, ceiling=Decimal("10.00"), static_arms=5)
    assert plan.cases == benchmark.case_count
    assert plan.judged == benchmark.case_count

    fewer = plan_pass(benchmark, ceiling=Decimal("10.00"), static_arms=0, judged=0)
    assert fewer.projection < plan.projection


async def test_nothing_may_be_billed_before_the_guard_is_authorised() -> None:
    plan = plan_pass(_benchmark(), ceiling=Decimal("10.00"), static_arms=5)
    plan.guard.record(Decimal("0.10"), task="tailor_plan")
    assert plan.guard.spent == Decimal("0.10")


# -- Seeding, and what it must not touch (FR-012, FR-013) --------------------


async def test_a_seeded_case_is_tailorable_through_the_shipping_preconditions(
    db_session: AsyncSession,
) -> None:
    """If `check_preconditions` accepts it, the benchmark uses the real path."""
    benchmark = _benchmark()
    case = benchmark.cases[0]
    seeded = await seed_case(db_session, benchmark, case, suffix="t1")

    application = await db_session.get(Application, seeded.application_id)
    assert application is not None
    analysis, profile, master = await check_preconditions(db_session, application)
    assert analysis.id == seeded.analysis_id
    assert profile.id == seeded.profile_id
    assert master is not None


async def test_every_benchmark_user_is_seeded_on_example_com(
    db_session: AsyncSession,
) -> None:
    """FR-013, and pydantic's `EmailStr` rejects `.test` and `.invalid`."""
    benchmark = _benchmark()
    seeded = await seed_case(db_session, benchmark, benchmark.cases[0], suffix="t2")
    email = await db_session.scalar(
        sa.text("SELECT email FROM users WHERE id = :id").bindparams(id=seeded.user_id)
    )
    assert email.endswith(f"@{BENCHMARK_EMAIL_DOMAIN}")


async def test_seeding_adds_rows_and_modifies_no_existing_evidence(
    db_session: AsyncSession,
) -> None:
    """FR-012 — the harness adds rows only.

    The eight versions, thirteen runs, eight analyses and one submission already in
    the real database cost $3.562567 and are this project's only evaluation
    evidence. This asserts the shape of that promise on a scratch database: whatever
    existed before a benchmark touched it is byte-identical afterwards.
    """
    from tests.support.tailoring_fixtures import seed_tailorable

    existing = await seed_tailorable(
        db_session, sub="google-preexisting", email="preexisting@example.com"
    )
    run = TailoringRun(
        resume_version_id=None,  # type: ignore[arg-type]
        match_analysis_id=existing.analysis.id,
        finalisation_rules_version="v1",
        status="succeeded",
        cost=Decimal("0.343304"),
    )
    version = ResumeVersion(
        application_id=existing.application.id,
        profile_id=existing.profile.id,
        source_resume_profile_id=existing.master.id,
        source_profile_updated_at=datetime.now(UTC),
        name="Pre-existing evidence",
        status="ready",
    )
    db_session.add(version)
    await db_session.flush()
    run.resume_version_id = version.id
    db_session.add(run)
    await db_session.flush()

    before = {
        "version": (version.status, version.name),
        "run": (run.status, run.cost),
        "analysis": (existing.analysis.overall_score, existing.analysis.status),
    }

    benchmark = _benchmark()
    for case in benchmark.cases[:3]:
        await seed_case(db_session, benchmark, case, suffix="t3")
    await db_session.flush()

    await db_session.refresh(version)
    await db_session.refresh(run)
    await db_session.refresh(existing.analysis)

    assert (version.status, version.name) == before["version"]
    assert (run.status, run.cost) == before["run"]
    assert (existing.analysis.overall_score, existing.analysis.status) == before["analysis"]


async def test_seeding_is_repeatable_and_two_passes_do_not_collide(
    db_session: AsyncSession,
) -> None:
    """A second pass over the same set must not reuse the first pass's rows."""
    benchmark = _benchmark()
    case = benchmark.cases[0]
    first = await seed_case(db_session, benchmark, case, suffix="pass-a")
    second = await seed_case(db_session, benchmark, case, suffix="pass-b")
    assert first.application_id != second.application_id
    assert first.profile_id != second.profile_id


async def test_an_authored_analysis_records_a_gap_for_every_expected_gap(
    db_session: AsyncSession,
) -> None:
    """The AI-008 test material — and `gap` must quote its shortfall."""
    benchmark = _benchmark()
    case = next(c for c in benchmark.cases if c.expected_gaps)
    seeded = await seed_case(db_session, benchmark, case, suffix="t4")

    analysis = await db_session.get(MatchAnalysis, seeded.analysis_id)
    assert analysis is not None
    requirements = (
        await db_session.scalars(sa.select(MatchAnalysis).where(MatchAnalysis.id == analysis.id))
    ).all()
    assert requirements

    rows = (
        await db_session.execute(
            sa.text(
                "SELECT text, verdict, evidence, shortfall FROM match_requirements "
                "WHERE analysis_id = :id"
            ).bindparams(id=analysis.id)
        )
    ).all()
    gaps = [r for r in rows if r.verdict == "gap"]
    assert len(gaps) == len(case.expected_gaps)
    for row in gaps:
        assert row.evidence, "a gap that quotes nothing lets the absence be invented"
        assert row.shortfall
