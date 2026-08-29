"""SC-008 — retrieval's cost per run, measured against a static baseline. **Spends money.**

    docker compose exec backend python scripts/measure_retrieval_cost.py run <application-id>
    docker compose exec backend python scripts/measure_retrieval_cost.py report

**`run` makes real, billed model calls** — two full tailoring runs, roughly $0.65 at the
prices below. It is separated from `report` for that reason: the arithmetic can be
re-checked, and drilled, without paying again.

**The two arms.** One application, one process, one pricing window: `guideline_source`
`static` and then `retrieval`, everything else identical. SC-008 requires both arms *"under
the same pricing and model conditions"*, because Sonnet 5's introductory rate ends
2026-08-31 and a percentage with a baseline on one side of that date and a retrieval run on
the other reports a pricing change as a retrieval regression.

**Why the total-cost ratio is not the answer, and this is the whole methodological point.**
Run cost is dominated by whether the Reviewer triggers a revision — a step function worth an
extra Sonnet call and an extra Opus call, about a third of a run. Slice 005 measured four
runs of the same pipeline at $0.295 to $0.548, an 85% spread. **A threshold of 2% cannot be
resolved through that.** The first paid pair here makes the point at full volume: the static
arm revised and the retrieval arm did not, so retrieval came out **54% cheaper** — which is
evidence about the revision loop and nothing whatever about retrieval.

**What is measured instead is the part that is actually controlled.** Retrieval *replaces*
the static guidance block in the two prompts that consume guidance. The **Plan** call is a
perfect control: same posting, same analysis, same profile, same prompt, differing only in
that block. Its input-token delta is therefore exactly the guidance delta, and the Draft
call — which also carries a differing plan — corroborates it. Both numbers come from the
provider's own accounting via `tailoring_run_calls`, so this is measured, not modelled.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import uuid
from decimal import Decimal

import sqlalchemy as sa

from careerhq.api.deps import get_structured_completion
from careerhq.api.routes.tailoring import build_guideline_source
from careerhq.application.retrieved_guidelines import RetrievedGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.config import get_settings
from careerhq.domain.models import Application, ResumeVersion, TailoringRun, TailoringRunCall
from careerhq.domain.models.knowledge import KnowledgeChunk
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.embeddings import get_embedding_source

#: Written inside the container, read back by `report`. A fixed path so a measurement can
#: be re-checked and drilled after the paid half has run.
RESULTS = pathlib.Path(os.environ.get("SC008_RESULTS", "sc008.json"))
THRESHOLD_PERCENT = Decimal("2")

#: Which calls receive the guidance block. `prompts.py` interpolates `{guidelines}` into
#: exactly these two; Review and Revise do not consume it, so a run that revises spends
#: more without adding any retrieval cost — which is why the denominator moves and the
#: numerator does not.
GUIDANCE_CONSUMING = ("tailor_plan", "tailor_draft")


async def _arm(name: str, application_id: uuid.UUID) -> dict[str, object]:
    settings = get_settings().model_copy(update={"guideline_source": name})
    factory = get_session_factory()

    async with factory() as session:
        application = await session.get(Application, application_id)
        assert application is not None, application_id
        version = await create_pending_version(session, application)
        await session.commit()
        version_id = version.id

    async with factory() as session:
        source = build_guideline_source(session, settings)
        # **The arms cannot be swapped silently.** Each is asserted to be the
        # implementation its label claims, so a mislabelled pair fails here rather than
        # producing a ratio of one thing against itself.
        if name == "retrieval":
            assert isinstance(source, RetrievedGuidelines), type(source).__name__
        else:
            assert not isinstance(source, RetrievedGuidelines), type(source).__name__
        await run_tailoring(
            session,
            version_id=version_id,
            completion=get_structured_completion(),
            guidelines=source,
        )
        await session.commit()
        fallback = getattr(source, "last_fallback_reason", None)

    async with factory() as session:
        finished = await session.get(ResumeVersion, version_id)
        assert finished is not None and finished.tailoring_run_id is not None
        run = await session.get(TailoringRun, finished.tailoring_run_id)
        assert run is not None
        calls = list(
            (
                await session.execute(
                    sa.select(TailoringRunCall)
                    .where(TailoringRunCall.tailoring_run_id == run.id)
                    .order_by(TailoringRunCall.sequence)
                )
            ).scalars()
        )

    return {
        "arm": name,
        "run_id": str(run.id),
        "version_id": str(version_id),
        "status": str(run.status),
        "is_fixture": bool(run.is_fixture),
        "fallback": fallback,
        # **Durable evidence that retrieval actually produced the guidance**, and stronger
        # than the in-memory flag beside it: a run that fell back snapshots the *static*
        # rubric, whose entries carry no `content_hash`. The snapshot is the audit record
        # OQ-006-A requires, so this survives the process that measured it.
        "retrieved_citations": sum(
            1 for g in (run.guidelines_used or []) if isinstance(g, dict) and g.get("content_hash")
        ),
        "guidelines": len(run.guidelines_used or []),
        "cost": str(run.cost),
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "calls": [
            {
                "sequence": c.sequence,
                "task": c.task,
                "model": c.model,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cost": str(c.cost),
                "run_id": str(c.tailoring_run_id),
            }
            for c in calls
        ],
    }


def _write(results: list[dict[str, object]]) -> None:
    """Outside the coroutine: `pathlib` in an async function is refused by ASYNC240."""
    RESULTS.write_text(json.dumps(results, indent=2))


async def run(application_id: uuid.UUID) -> int:
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        chunks = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeChunk))
    if not chunks:
        print("REFUSED: the corpus is empty; the retrieval arm would measure the fallback.")
        return 1
    await get_embedding_source().warm_up()

    print(
        f"application {application_id}  corpus {chunks} chunks  "
        f"ceiling {settings.retrieval_token_ceiling}"
    )
    results = [await _arm(name, application_id) for name in ("static", "retrieval")]
    _write(results)
    print(f"\nwritten to {RESULTS}")
    return report(results)


async def collect(static_run: uuid.UUID, retrieval_run: uuid.UUID) -> int:
    """Rebuild the two arms from the database. **Free** — the runs already happened.

    The database is the authoritative record of a paid run: `tailoring_runs` holds the
    cost and the guideline snapshot, `tailoring_run_calls` the per-call usage. Re-reading
    it is how a measurement can be re-checked, or its arithmetic drilled, without paying
    for another pair.
    """
    factory = get_session_factory()
    results: list[dict[str, object]] = []
    async with factory() as session:
        for name, run_id in (("static", static_run), ("retrieval", retrieval_run)):
            run = await session.get(TailoringRun, run_id)
            assert run is not None, run_id
            calls = list(
                (
                    await session.execute(
                        sa.select(TailoringRunCall)
                        .where(TailoringRunCall.tailoring_run_id == run.id)
                        .order_by(TailoringRunCall.sequence)
                    )
                ).scalars()
            )
            results.append(
                {
                    "arm": name,
                    "run_id": str(run.id),
                    "version_id": str(run.resume_version_id),
                    "status": str(run.status),
                    "is_fixture": bool(run.is_fixture),
                    "fallback": None,
                    "retrieved_citations": sum(
                        1
                        for g in (run.guidelines_used or [])
                        if isinstance(g, dict) and g.get("content_hash")
                    ),
                    "guidelines": len(run.guidelines_used or []),
                    "cost": str(run.cost),
                    "input_tokens": run.input_tokens,
                    "output_tokens": run.output_tokens,
                    "calls": [
                        {
                            "sequence": c.sequence,
                            "task": c.task,
                            "model": c.model,
                            "input_tokens": c.input_tokens,
                            "output_tokens": c.output_tokens,
                            "cost": str(c.cost),
                            "run_id": str(c.tailoring_run_id),
                        }
                        for c in calls
                    ],
                }
            )
    _write(results)
    return report(results)


def report(results: list[dict[str, object]] | None = None) -> int:
    """The arithmetic, and every refusal that keeps it honest. Reads; never pays."""
    import litellm

    if results is None:
        results = json.loads(RESULTS.read_text())
    arms = {str(r["arm"]): r for r in results}

    if set(arms) != {"static", "retrieval"}:
        print(f"REFUSED: expected a static and a retrieval arm, got {sorted(arms)}.")
        return 1

    for name, r in arms.items():
        # **A mocked or fixture arm cannot satisfy this.** The fixture gateway records a
        # zero cost, and a run that failed has no comparable token usage — either would
        # otherwise flatter the comparison enormously.
        if r["status"] != "succeeded":
            print(f"REFUSED: the {name} arm {r['status']}; a failed run is not a measurement.")
            return 1
        if r["is_fixture"] or Decimal(str(r["cost"])) <= 0:
            print(f"REFUSED: the {name} arm cost {r['cost']} — no paid call was made.")
            return 1
        if any(c["run_id"] != r["run_id"] for c in r["calls"]):  # type: ignore[union-attr]
            print(f"REFUSED: the {name} arm's per-call usage belongs to another run.")
            return 1
    if arms["static"]["run_id"] == arms["retrieval"]["run_id"]:
        print("REFUSED: both arms report the same run.")
        return 1
    if not arms["retrieval"]["retrieved_citations"]:
        print(
            "REFUSED: the retrieval arm's snapshot carries no content hashes — it fell "
            "back to the static rubric."
        )
        return 1
    if arms["static"]["retrieved_citations"]:
        print("REFUSED: the static arm snapshotted retrieved guidance; the arms are swapped.")
        return 1
    if arms["retrieval"]["guidelines"] == arms["static"]["guidelines"]:
        print("REFUSED: both arms used the same guidance; the arms did not differ.")
        return 1

    tasks = {name: {c["task"]: c for c in r["calls"]} for name, r in arms.items()}  # type: ignore[union-attr]
    models = {
        name: {c["task"]: c["model"] for c in r["calls"]}  # type: ignore[union-attr]
        for name, r in arms.items()
    }
    shared = set(models["static"]) & set(models["retrieval"])
    for task in shared:
        if models["static"][task] != models["retrieval"][task]:
            print(
                f"REFUSED: {task} ran on {models['static'][task]} vs "
                f"{models['retrieval'][task]}; the arms are not comparable."
            )
            return 1

    delta = 0
    for task in GUIDANCE_CONSUMING:
        if task not in tasks["static"] or task not in tasks["retrieval"]:
            print(f"REFUSED: {task} is missing from an arm; the delta cannot be attributed.")
            return 1
        delta += int(tasks["retrieval"][task]["input_tokens"]) - int(
            tasks["static"][task]["input_tokens"]
        )

    # **Priced from the provider table the gateway itself uses**, read now rather than
    # written down here: a constant in this file would keep reporting yesterday's answer
    # after a price change, which is the one thing SC-008's own note warns about.
    model = str(models["retrieval"]["tailor_plan"])
    info = litellm.get_model_info(f"anthropic/{model}" if "/" not in model else model)
    input_price = Decimal(str(info["input_cost_per_token"]))
    baseline = Decimal(str(arms["static"]["cost"]))
    attributable = Decimal(delta) * input_price
    percent = attributable / baseline * 100

    print(f"\nguidance-consuming calls: {', '.join(GUIDANCE_CONSUMING)}")
    for task in GUIDANCE_CONSUMING:
        s, r = tasks["static"][task], tasks["retrieval"][task]
        print(
            f"  {task:14s} input {s['input_tokens']:6d} -> {r['input_tokens']:6d}  "
            f"delta +{int(r['input_tokens']) - int(s['input_tokens'])}"
        )
    print(f"\nattributable input tokens  +{delta}")
    print(
        f"input price                ${input_price * 1_000_000:.2f}/MTok  ({model}, from litellm)"
    )
    print(f"attributable cost          ${attributable:.6f}")
    print(f"static baseline (same session) ${baseline}")
    print(
        f"\nSC-008 (<= {THRESHOLD_PERCENT}%): {percent:.2f}%  "
        f"{'MET' if percent <= THRESHOLD_PERCENT else 'MISSED'}"
    )
    print(
        f"\n(for the record, and NOT an SC-008 reading: total cost "
        f"${baseline} vs ${arms['retrieval']['cost']} — dominated by whether the "
        f"Reviewer triggered a revision, not by retrieval.)"
    )
    return 0 if percent <= THRESHOLD_PERCENT else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        raise SystemExit(asyncio.run(run(uuid.UUID(sys.argv[2]))))
    if len(sys.argv) > 3 and sys.argv[1] == "collect":
        raise SystemExit(asyncio.run(collect(uuid.UUID(sys.argv[2]), uuid.UUID(sys.argv[3]))))
    raise SystemExit(report())
