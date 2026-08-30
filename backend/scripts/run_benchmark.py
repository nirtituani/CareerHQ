"""The benchmark runner. **`run` spends money; nothing else does.**

    python scripts/run_benchmark.py plan                 # free: project and check the ceiling
    python scripts/run_benchmark.py report-existing      # free: metrics over runs already paid for
    python scripts/run_benchmark.py difficulty           # free: is the set hard enough to measure?
    python scripts/run_benchmark.py run                  # PAID — refuses without --i-have-approval

**The paid half is separated from the reporting half**, following
`scripts/measure_retrieval_cost.py`: the arithmetic must be re-checkable, and
drillable, without paying again (FR-032).

**The ceiling is enforced here, before any billable call** (FR-008, SC-011). It is
read from `eval_spend_ceiling_usd` and the case count from the loaded benchmark
set — neither is written down in this file, so a projection cannot silently
describe a different run from the one about to happen.

**`run` additionally refuses without an explicit approval flag.** D3 approved a
budget; it did not approve this command running because someone was exploring.
A ceiling stops a runaway, not a mistake.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import uuid
from decimal import Decimal
from typing import Any

from careerhq.application.evaluation.benchmark_set import difficulty_report, load_benchmark_set
from careerhq.application.evaluation.budget import (
    ESTIMATED_JUDGE_COST,
    MEASURED_REVISION_RATE,
    CeilingExceededError,
    expected_run_cost,
    project_pass_cost,
    project_run_cost,
)
from careerhq.application.evaluation.eligibility import IneligibleRunError, assert_reportable
from careerhq.application.evaluation.metrics import (
    METRIC_VERSION,
    GuidelineRecord,
    coverage,
    grounding,
)
from careerhq.application.evaluation.readers import (
    corpus_identity,
    guidance_used,
    read_claims,
    read_findings,
    read_guidelines,
    read_provenance,
    read_requirements,
    read_run_costs,
    read_run_summary,
)
from careerhq.application.evaluation.runner import plan_pass
from careerhq.application.finalisation_rules import FINALISATION_RULES_VERSION
from careerhq.config import get_settings
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.logging import configure_logging

BENCHMARK_ROOT = pathlib.Path(__file__).resolve().parents[1] / "benchmark"

#: The tailoring tasks a benchmark run must use, read from configuration rather
#: than written down. FR-010: the benchmark runs the mix that ships.
SHIPPING_TASKS = ("tailor_plan", "tailor_draft", "tailor_review")


def _shipping_mix() -> dict[str, str]:
    settings = get_settings()
    return {task: settings.model_for_task(task) for task in SHIPPING_TASKS}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _write_report(report: dict[str, Any], out: str | None) -> None:
    if out is None:
        _emit(report)
        return
    pathlib.Path(out).write_text(json.dumps(report, indent=2, default=str))
    print(f"wrote {out}")


async def cmd_plan(args: argparse.Namespace) -> int:
    """Project the cost and check it against the ceiling. **No model call.**"""
    settings = get_settings()
    benchmark = load_benchmark_set(args.set or settings.eval_benchmark_set, root=BENCHMARK_ROOT)
    ceiling = Decimal(args.ceiling) if args.ceiling else settings.eval_spend_ceiling_usd

    payload: dict[str, Any] = {
        "benchmark_set": benchmark.version,
        "cases": benchmark.case_count,
        "static_arms": args.static_arms,
        "judged": benchmark.case_count if args.judged is None else args.judged,
        "ceiling_usd": float(ceiling),
        "per_run_non_revising_usd": float(project_run_cost(revising=False)),
        "per_run_revising_usd": float(project_run_cost(revising=True)),
        "measured_revision_rate": float(MEASURED_REVISION_RATE),
        "judge_cost_usd_estimated": float(ESTIMATED_JUDGE_COST),
        "shipping_mix": _shipping_mix(),
    }
    # Weighted by the measured 37.5% revision rate — the forecast, matching
    # plan.md's $0.31/run. The ceiling below is checked against the conservative
    # figure instead, because a ceiling sized on an average is exceeded about half
    # the time.
    payload["expected_usd"] = float(
        project_pass_cost(
            cases=benchmark.case_count,
            static_arms=args.static_arms,
            judged=payload["judged"],
            expected=True,
        )
    )
    payload["expected_per_run_usd"] = float(expected_run_cost())
    try:
        plan = plan_pass(
            benchmark,
            ceiling=ceiling,
            static_arms=args.static_arms,
            judged=args.judged,
        )
    except CeilingExceededError as exc:
        payload.update(authorised=False, refusal=str(exc))
        _emit(payload)
        return 1

    payload.update(
        authorised=True,
        conservative_usd=float(plan.projection),
        headroom_usd=float(ceiling - plan.projection),
        note=(
            "conservative prices every run as though the Reviewer revised, which is the "
            "right basis for a ceiling and the wrong one for a forecast"
        ),
    )
    _emit(payload)
    return 0


async def cmd_difficulty(args: argparse.Namespace) -> int:
    """Is the set hard enough to measure anything? **No model call.**"""
    settings = get_settings()
    benchmark = load_benchmark_set(args.set or settings.eval_benchmark_set, root=BENCHMARK_ROOT)
    _emit({"benchmark_set": benchmark.version, **difficulty_report(benchmark)})
    return 0


async def cmd_report_existing(args: argparse.Namespace) -> int:
    """Every free metric, over runs this project has already paid for.

    **No model call and no new row.** This is the tier that proves the metric
    definitions before a benchmark case is billed — and it is also where a metric
    that cannot produce a number from thirteen real runs is caught being wrong.
    """
    import sqlalchemy as sa

    from careerhq.domain.models import TailoringRun

    session_factory = get_session_factory()
    async with session_factory() as session:
        runs = (
            await session.scalars(sa.select(TailoringRun).order_by(TailoringRun.started_at))
        ).all()

        report: dict[str, Any] = {
            "metric_version": METRIC_VERSION,
            "corpus": await corpus_identity(session),
            "runs_examined": len(runs),
            "shipping_mix": _shipping_mix(),
            "runs": [],
        }

        for run in runs:
            summary = await read_run_summary(session, run)
            provenance = await read_provenance(session, run, benchmark_profile_ids=set())
            try:
                # These are historical *user* runs, not benchmark runs, so the
                # FR-013 benchmark-profile rule does not apply to reading numbers
                # off them. Every other refusal still does.
                assert_reportable(
                    provenance,
                    shipping_mix=_shipping_mix(),
                    require_benchmark_profile=False,
                )
                summary["reportable"] = True
            except IneligibleRunError as exc:
                summary["reportable"] = False
                summary["refusal"] = str(exc)

            findings = await read_findings(session, run.id)
            claims = await read_claims(session, run.resume_version_id)
            summary["guidelines"] = len(await read_guidelines(session, run))

            # **The safety check, always, on every run.** `persisted_ungrounded` is
            # not an agent-quality metric — it is the Principle III release-blocker
            # (SC-006), and a run too ineligible to be scored is not too ineligible
            # to have leaked a fabricated claim. Withholding it would be the one
            # refusal that makes the system less safe.
            grounded = grounding(claims=claims, findings=findings)
            summary["persisted_ungrounded"] = grounded["persisted_ungrounded"]
            summary["ungrounded_caught"] = grounded["ungrounded_caught"]

            if not summary["reportable"]:
                # FR-030. The first draft of this command computed and printed every
                # metric beside the refusal, which is precisely the thing the refusal
                # exists to prevent — and it read convincingly: a **failed** run has
                # no `uncovered` findings, so its coverage computed to a confident
                # 1.00. Withheld rather than shown with a caveat, because a number
                # next to a caveat is still a number people quote.
                summary["metrics_withheld"] = (
                    "agent-quality metrics are not reported for an ineligible run"
                )
                report["runs"].append(summary)
                continue

            summary["grounding"] = {
                k: (v.as_dict() if hasattr(v, "as_dict") else v) for k, v in grounded.items()
            }
            analysis_requirements = await read_requirements(session, run.match_analysis_id)
            summary["coverage"] = {
                k: (v.as_dict() if hasattr(v, "as_dict") else v)
                for k, v in coverage(requirements=analysis_requirements, uncovered=findings).items()
            }
            report["runs"].append(summary)

        costs = await read_run_costs(session)
        report["denominator_sample"] = {
            "n": len(costs),
            "revised": sum(1 for c in costs if c.revised),
            "min_usd": float(min((c.cost for c in costs), default=0)),
            "max_usd": float(max((c.cost for c in costs), default=0)),
        }

    # Written through a synchronous helper: blocking file IO inside a coroutine is
    # exactly what ASYNC240 exists to catch, and a report is small enough that
    # correctness of the rule matters more than the microseconds.
    _write_report(report, args.out)
    return 0


async def cmd_validate(args: argparse.Namespace) -> int:
    """Drive the whole harness end to end with **zero model calls**.

    Everything a paid pass does except call a model: load and version the set,
    fingerprint the configuration, project the cost, check it against the ceiling,
    seed every case through the shipping preconditions, render the master the model
    would be shown, retrieve guidance for every posting (a local embedding and a
    pgvector scan — no provider), and run every free metric over what comes back.

    **This is the tier that has to pass before anything is billed.** It proves the
    plumbing; FR-030 then refuses to let any of it be reported as agent quality.

    **It refuses to run against a database holding evaluation evidence.** Seeding
    twelve cases adds rows, and those rows would sit beside $3.56 of paid evidence
    in every statistic computed afterwards. Point it at a scratch database.
    """
    import sqlalchemy as sa

    from careerhq.application.evaluation.eligibility import Fingerprint
    from careerhq.application.evaluation.metrics import retrieval_quality
    from careerhq.application.evaluation.runner import seed_case
    from careerhq.application.guidelines import GuidelineQuery
    from careerhq.application.retrieved_guidelines import RetrievedGuidelines, citation_snapshot
    from careerhq.application.tailor_resume import (
        V1_TARGET_MARKET,
        _render_master,
        check_preconditions,
    )
    from careerhq.domain.models import Application, TailoringRun
    from careerhq.infrastructure.embeddings import get_embedding_source

    settings = get_settings()
    benchmark = load_benchmark_set(args.set or settings.eval_benchmark_set, root=BENCHMARK_ROOT)
    ceiling = Decimal(args.ceiling) if args.ceiling else settings.eval_spend_ceiling_usd

    try:
        plan = plan_pass(
            benchmark, ceiling=ceiling, static_arms=args.static_arms, judged=args.judged
        )
    except CeilingExceededError as exc:
        print(f"REFUSED before any work: {exc}", file=sys.stderr)
        return 1

    session_factory = get_session_factory()
    report: dict[str, Any] = {
        "mode": "validate",
        "model_calls": 0,
        "benchmark_set": benchmark.version,
        "cases": benchmark.case_count,
        "projection_usd": float(plan.projection),
        "ceiling_usd": float(ceiling),
        "metric_version": METRIC_VERSION,
        "results": [],
    }

    async with session_factory() as session:
        # **The evidence guard.** A non-fixture run in this database means it holds
        # something that was paid for.
        paid = await session.scalar(
            sa.select(sa.func.count())
            .select_from(TailoringRun)
            .where(TailoringRun.is_fixture.is_(False))
        )
        if paid and not args.i_know_this_database_is_scratch:
            print(
                f"REFUSED: this database holds {paid} non-fixture tailoring run(s) — "
                "evaluation evidence that was paid for. Validation seeds twelve cases, "
                "and those rows would sit beside it in every statistic computed "
                "afterwards.\n"
                "  Point DATABASE_URL at a scratch database, or pass "
                "--i-know-this-database-is-scratch if you are certain.",
                file=sys.stderr,
            )
            return 4

        report["corpus"] = await corpus_identity(session)
        embedder = get_embedding_source()
        guidelines = RetrievedGuidelines(
            session, embedder=embedder, token_ceiling=settings.retrieval_token_ceiling
        )

        for case in benchmark.cases:
            seeded = await seed_case(session, benchmark, case, suffix="validate")
            application = await session.get(Application, seeded.application_id)
            assert application is not None

            # The shipping preconditions, not a reimplementation of them. The
            # analysis and master are discarded deliberately: what matters here is
            # that the real gate *accepted* the seeded case, not what it returned.
            _analysis, profile, _master = await check_preconditions(session, application)
            master_text, master_items = await _render_master(session, profile.id)

            guidance = await guidelines.guidelines_for(
                context=GuidelineQuery(
                    role_title=application.job_title,
                    requirements=list(case.requirements),
                    market=V1_TARGET_MARKET,
                )
            )
            snapshot = citation_snapshot(guidance)
            records = [
                GuidelineRecord(
                    document_slug=str(e.get("document_slug", "")),
                    source_type=(
                        "integrity"
                        if str(e.get("document_slug", "")).startswith("integrity")
                        else "other"
                    ),
                )
                for e in snapshot
            ]
            quality = retrieval_quality(guidelines=records, relevant_slugs=None)

            report["results"].append(
                {
                    "case_id": case.case_id,
                    "discipline": case.discipline,
                    "seniority": case.seniority,
                    "preconditions": "passed",
                    "master_chars": len(master_text),
                    "master_items": len(master_items),
                    "requirements": len(case.requirements),
                    "expected_gaps": len(case.expected_gaps),
                    "guidelines_retrieved": len(snapshot),
                    "guidance_used": guidance_used(snapshot),
                    "pinned": quality["pinned"],
                    "selected": quality["selected"],
                    "retrieval_ms": guidelines.last_retrieval_ms,
                    "fallback": guidelines.last_fallback_reason,
                    # SC-012 / SC-001 (006): which rules this posting *selected*.
                    # Pinned integrity rules are excluded — they are identical on
                    # every case by construction, so including them would make any
                    # two postings look similar and report a floor as a result.
                    "selected_slugs": sorted(
                        {r.document_slug for r in records if r.source_type != "integrity"}
                    ),
                }
            )

        report["fingerprint"] = Fingerprint(
            benchmark_set=benchmark.version,
            metric_version=METRIC_VERSION,
            finalisation_rules_version=FINALISATION_RULES_VERSION,
            guideline_source=settings.guideline_source,
            corpus_identity=report["corpus"],
            embedding_model=settings.embedding_model,
            pricing_basis="litellm",
            model_config=_shipping_mix(),
        ).as_dict()

        # Nothing is committed. Validation proves the plumbing; it does not need to
        # leave twelve seeded cases behind to have done so.
        await session.rollback()

    report["all_cases_retrieved"] = all(r["guidance_used"] == "corpus" for r in report["results"])
    report["distinct_guideline_counts"] = sorted(
        {r["guidelines_retrieved"] for r in report["results"]}
    )

    # **Does guidance actually track the posting?** SC-012, and SC-001 (006), which
    # no slice-006 task records having performed. Free: retrieval is a local
    # embedding and a pgvector scan, so this needs no model and no tailoring run.
    #
    # Two controls, because "the sets differ" is also what noise produces: the
    # pinned set must be identical everywhere, and each posting must return the same
    # selection twice.
    selections = {r["case_id"]: set(r["selected_slugs"]) for r in report["results"]}
    by_discipline: dict[str, set[str]] = {}
    for r in report["results"]:
        by_discipline.setdefault(r["discipline"], set()).update(r["selected_slugs"])

    pairs = [
        (a, b, len(selections[a] & selections[b]) / len(selections[a] | selections[b]))
        for i, a in enumerate(sorted(selections))
        for b in sorted(selections)[i + 1 :]
        if selections[a] | selections[b]
    ]
    same_discipline = [p for p in pairs if p[0].split("-")[0] == p[1].split("-")[0]]
    cross_discipline = [p for p in pairs if p[0].split("-")[0] != p[1].split("-")[0]]

    report["retrieval_quality"] = {
        "distinct_selections": len({frozenset(s) for s in selections.values()}),
        "cases": len(selections),
        "union_of_selected_rules": len(set().union(*selections.values())),
        "pinned_identical_everywhere": len({r["pinned"] for r in report["results"]}) == 1,
        "mean_overlap_same_discipline": (
            round(sum(p[2] for p in same_discipline) / len(same_discipline), 3)
            if same_discipline
            else None
        ),
        "mean_overlap_cross_discipline": (
            round(sum(p[2] for p in cross_discipline) / len(cross_discipline), 3)
            if cross_discipline
            else None
        ),
        "least_similar_pair": min(pairs, key=lambda p: p[2])[:2] if pairs else None,
        "rules_per_discipline": {k: len(v) for k, v in sorted(by_discipline.items())},
    }
    _write_report(report, args.out)
    return 0


async def _execute_arm(
    session: Any,
    *,
    benchmark: Any,
    case: Any,
    guidance: str,
    guarded: Any,
    settings: Any,
) -> dict[str, Any]:
    """Run one case through the shipping path, once, under one guidance source.

    `guidance` is the **intent**; what the run actually used is read back from its
    snapshot. The two disagreeing is a fallback, and that is how it is detected —
    with no schema column (data-model §0).
    """
    from careerhq.application.evaluation.readers import guidance_used
    from careerhq.application.evaluation.runner import render_version, seed_case, version_items
    from careerhq.application.guidelines import StaticGuidelines
    from careerhq.application.retrieved_guidelines import RetrievedGuidelines
    from careerhq.application.tailor_resume import create_pending_version, run_tailoring
    from careerhq.domain.models import Application, ResumeVersion, TailoringRun
    from careerhq.infrastructure.embeddings import get_embedding_source

    seeded = await seed_case(session, benchmark, case, suffix=f"{guidance}-{args_suffix()}")
    await session.commit()

    application = await session.get(Application, seeded.application_id)
    assert application is not None
    version = await create_pending_version(session, application)
    await session.commit()

    source = (
        StaticGuidelines()
        if guidance == "static"
        else RetrievedGuidelines(
            session,
            embedder=get_embedding_source(),
            token_ceiling=settings.retrieval_token_ceiling,
        )
    )
    await run_tailoring(session, version_id=version.id, completion=guarded, guidelines=source)
    await session.commit()

    refreshed = await session.get(ResumeVersion, version.id)
    assert refreshed is not None
    run = await session.get(TailoringRun, refreshed.tailoring_run_id)
    assert run is not None

    items = await version_items(session, version.id)
    return {
        "case_id": case.case_id,
        "guidance_intended": guidance,
        "guidance_used": guidance_used(run.guidelines_used),
        "run_id": str(run.id),
        "version_id": str(version.id),
        "status": str(run.status),
        "failure_reason": run.failure_reason,
        "attempts": run.attempts,
        "cost": float(run.cost),
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "review_confidences": run.review_confidences,
        "guidelines": len(run.guidelines_used or []),
        "items": len(items),
        "_resume": render_version(items),
        "_seeded": seeded,
    }


_SUFFIX = {"value": "t040"}


def args_suffix() -> str:
    return _SUFFIX["value"]


async def cmd_run(args: argparse.Namespace) -> int:
    """**PAID.** T040 and T045, exactly as approved. Refuses without approval."""
    from careerhq.api.deps import get_structured_completion
    from careerhq.application.eval_judge import RUBRIC_VERSION, judge_resume
    from careerhq.application.evaluation.eligibility import Fingerprint
    from careerhq.application.evaluation.guarded import GuardedCompletion
    from careerhq.application.evaluation.metrics import coverage, grounding
    from careerhq.application.evaluation.readers import read_findings, read_requirements
    from careerhq.application.finalisation_rules import FINALISATION_RULES_VERSION
    from careerhq.domain.models import TailoringRun

    if not args.i_have_approval:
        print(
            "REFUSED: a paid pass needs --i-have-approval.\n"
            "  D3 approved a $10 ceiling, 12 cases and one full paid pass. It did not\n"
            "  approve this command running because someone was exploring. Run\n"
            "  `plan` first — it is free and reports exactly what this would spend.",
            file=sys.stderr,
        )
        return 2

    _SUFFIX["value"] = args.suffix
    settings = get_settings()
    benchmark = load_benchmark_set(args.set or settings.eval_benchmark_set, root=BENCHMARK_ROOT)
    ceiling = Decimal(args.ceiling) if args.ceiling else settings.eval_spend_ceiling_usd

    try:
        plan = plan_pass(
            benchmark, ceiling=ceiling, static_arms=args.static_arms, judged=args.judged
        )
    except CeilingExceededError as exc:
        print(f"REFUSED before any billable call: {exc}", file=sys.stderr)
        return 1

    # Spend already committed in an earlier phase counts against the same ceiling.
    if args.already_spent:
        plan.guard.record(Decimal(args.already_spent), task="carried-forward")

    # `skip` exists so an approved pass can be resumed without re-running a case
    # that has already been paid for. Case 1 was the judge-cost calibration; the
    # remainder starts after it.
    selected = benchmark.cases[args.skip :]
    cases = selected[: args.limit] if args.limit else selected
    static_cases = cases[: args.static_arms]
    judged_limit = args.judged if args.judged is not None else len(cases)
    judged_cases = {c.case_id for c in cases[:judged_limit]}

    guarded = GuardedCompletion(inner=get_structured_completion(), guard=plan.guard)
    session_factory = get_session_factory()

    report: dict[str, Any] = {
        "phase": args.suffix,
        "benchmark_set": benchmark.version,
        "projection_usd": float(plan.projection),
        "ceiling_usd": float(ceiling),
        "already_spent_usd": float(args.already_spent or 0),
        "metric_version": METRIC_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "arms": [],
        "judged": [],
        "refusals": [],
    }

    stopped = None
    async with session_factory() as session:
        report["corpus"] = await corpus_identity(session)
        report["fingerprint"] = Fingerprint(
            benchmark_set=benchmark.version,
            metric_version=METRIC_VERSION,
            finalisation_rules_version=FINALISATION_RULES_VERSION,
            guideline_source=settings.guideline_source,
            corpus_identity=report["corpus"],
            embedding_model=settings.embedding_model,
            pricing_basis="litellm",
            model_config=_shipping_mix(),
        ).as_dict()

        arms: list[tuple[Any, str]] = [(c, "retrieval") for c in cases]
        arms += [(c, "static") for c in static_cases]

        for case, guidance in arms:
            try:
                arm = await _execute_arm(
                    session,
                    benchmark=benchmark,
                    case=case,
                    guidance=guidance,
                    guarded=guarded,
                    settings=settings,
                )
            except CeilingExceededError as exc:
                stopped = str(exc)
                report["refusals"].append({"case_id": case.case_id, "reason": stopped})
                break

            resume = arm.pop("_resume")
            arm.pop("_seeded")
            print(
                f"  {arm['case_id']:26} {guidance:9} {arm['status']:10} "
                f"${arm['cost']:.4f}  cum ${plan.guard.spent:.4f}",
                file=sys.stderr,
            )

            judge_this = (
                arm["status"] == "succeeded"
                and guidance == "retrieval"
                and case.case_id in judged_cases
            )
            if judge_this:
                try:
                    verdict, usage, rubric = await judge_resume(
                        completion=guarded, posting=case.posting_text, resume=resume
                    )
                    report["judged"].append(
                        {
                            "case_id": case.case_id,
                            "version_id": arm["version_id"],
                            "rubric_version": rubric,
                            "overall": verdict.overall,
                            "dimensions": {d.dimension: d.score for d in verdict.dimensions},
                            "justifications": {
                                d.dimension: d.justification for d in verdict.dimensions
                            },
                            "strongest": verdict.strongest,
                            "weakest": verdict.weakest,
                            "cost": float(usage.cost),
                        }
                    )
                except CeilingExceededError as exc:
                    stopped = str(exc)
                    report["refusals"].append({"case_id": case.case_id, "reason": stopped})
                    break
                except Exception as exc:
                    # **The case is unjudged and the run continues** — the judge
                    # contract says so, and the first real judge call proved the
                    # handler did not honour it: `ExtractionFailedError` is neither
                    # a `ValueError` nor a `JudgeUnavailableError`, so it escaped
                    # and killed the pass after the tailoring run had already been
                    # paid for. A missing score is a fact; losing the run that
                    # produced it is a defect.
                    report["refusals"].append(
                        {
                            "case_id": case.case_id,
                            "reason": f"unjudged: {type(exc).__name__}: {exc}",
                        }
                    )

            report["arms"].append(arm)

        # Metrics over what was produced. Free.
        for arm in report["arms"]:
            if arm["status"] != "succeeded":
                continue
            run = await session.get(TailoringRun, uuid.UUID(arm["run_id"]))
            assert run is not None
            findings = await read_findings(session, run.id)
            claims = await read_claims(session, run.resume_version_id)
            g = grounding(claims=claims, findings=findings)
            reqs = await read_requirements(session, run.match_analysis_id)
            c = coverage(requirements=reqs, uncovered=findings)
            arm["grounding"] = {
                k: (v.as_dict() if hasattr(v, "as_dict") else v) for k, v in g.items()
            }
            arm["coverage"] = {
                k: (v.as_dict() if hasattr(v, "as_dict") else v) for k, v in c.items()
            }

        costs = await read_run_costs(session)
        report["denominator_sample"] = {
            "n": len(costs),
            "revised": sum(1 for x in costs if x.revised),
            "min_usd": float(min((x.cost for x in costs), default=0)),
            "max_usd": float(max((x.cost for x in costs), default=0)),
        }

    report["calls"] = guarded.calls
    report["model_calls"] = len(guarded.calls)
    report["actual_spend_usd"] = float(plan.guard.spent)
    report["remaining_under_ceiling_usd"] = float(plan.guard.remaining)
    report["stopped_early"] = stopped

    _write_report(report, args.out)
    print(
        f"\nSPEND ${plan.guard.spent:.6f} of ${ceiling:.2f} ceiling "
        f"({len(guarded.calls)} model calls, {len(report['arms'])} arms, "
        f"{len(report['judged'])} judged)",
        file=sys.stderr,
    )
    return 1 if stopped else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", default=None, help="benchmark set version (default: configured)")
    parser.add_argument("--ceiling", default=None, help="override the spend ceiling, in USD")
    parser.add_argument("--static-arms", type=int, default=5, help="SC-008 paired static arms")
    parser.add_argument("--judged", type=int, default=None, help="judged outputs (default: cases)")
    parser.add_argument("--out", default=None, help="write the report to this path")
    parser.add_argument(
        "--i-have-approval",
        action="store_true",
        help="required by `run`; confirms the author approved this paid pass",
    )
    parser.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    parser.add_argument("--skip", type=int, default=0, help="skip the first N cases (already paid)")
    parser.add_argument("--suffix", default="t040", help="phase label for seeded rows")
    parser.add_argument(
        "--already-spent", default=None, help="spend from an earlier phase, charged to the ceiling"
    )
    parser.add_argument(
        "--i-know-this-database-is-scratch",
        action="store_true",
        help="allow validation against a database that already holds paid runs",
    )
    parser.add_argument(
        "command",
        choices=("plan", "difficulty", "validate", "report-existing", "run"),
        help="plan/difficulty/validate/report-existing are free; run spends money",
    )
    return parser


async def run() -> int:
    """Awaitable, so the behaviour and the exit code are testable in-process.

    A command whose only entry point is synchronous can be tested *only* by
    spawning a process, and a suite that spawns one per claim tests almost none of
    them. `asyncio.run` cannot be called from inside a running loop.
    """
    args = build_parser().parse_args()
    handlers = {
        "plan": cmd_plan,
        "difficulty": cmd_difficulty,
        "validate": cmd_validate,
        "report-existing": cmd_report_existing,
        "run": cmd_run,
    }
    return await handlers[args.command](args)


def main() -> int:
    # **Configure logging, as every other one-shot entry point does.** Without it,
    # `run_tailoring` writes its failure detail into `extra` and nothing prints it —
    # the record says `BadRequestError` and the reason is lost. That is the right
    # split for a browser (type out, detail to the operator) and useless at a
    # terminal where this *is* the operator.
    configure_logging(get_settings().log_level)
    return asyncio.run(run())


if __name__ == "__main__":
    # `raise SystemExit(main())`, never a bare `main()`: a guard that discards the
    # return value exits 0 on every failure.
    raise SystemExit(main())
