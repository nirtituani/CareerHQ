"""The Career Advisor use case: reserve a run, execute it, apply what survives.

The lifecycle is `analyze_match.py`'s, deliberately (research.md D1): a
`pending` row committed before any provider call — so the interface has
something to poll and a failure has somewhere to record itself — one in flight
per **user** enforced by a partial unique index where it cannot be raced, and
an abandonment deadline so a process restart mid-run cannot strand the feature
behind a 409 forever (that lesson cost hand-written SQL three times).

The pipeline itself is linear and owns everything (research.md D13 — no
LangGraph: there is no conditional edge and no revision loop):

    evidence pack (deterministic) -> [grouping? Haiku] -> counting ->
    reasoning (Sonnet) -> grounding gate -> one transaction

The model is never the source of a number; `advisor_evidence.py` is. The gate
in `advisor_grounding.py` discards what it cannot verify before anything is
persisted, and everything that survives — memory inserts, status transitions,
disposition rows, the run's own completion — commits together, so a failure
anywhere leaves the memory set byte-for-byte unchanged (SC-005).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.advisor_evidence import build_evidence_pack, tier2_facts
from careerhq.application.advisor_grounding import (
    DispositionDefect,
    GateOutcome,
    apply_gate,
    freeze_evidence,
    validate_grouping,
)
from careerhq.application.advisor_rules import (
    ACTIVE_MEMORY_CAP,
    ADVISOR_RULES_VERSION,
    RUN_ABANDONED_AFTER,
    SMALL_SAMPLE_FLOOR,
)
from careerhq.application.ports import StructuredCompletion, UsageRecorder
from careerhq.domain.models import (
    USER_DISMISSED,
    AdvisorRun,
    AdvisorRunStatus,
    Application,
    CareerMemory,
    DispositionAction,
    MatchAnalysis,
    MatchRequirement,
    MatchStatus,
    MemoryDisposition,
    MemoryStatus,
    User,
)
from careerhq.domain.schemas.advisor import (
    AdvisorReasoning,
    EvidenceFact,
    EvidenceGrouping,
    EvidencePack,
    GroupingProposal,
)

logger = logging.getLogger(__name__)

#: Task names, resolved to models by `model_for_task` — configuration, never a
#: branch (docs/08 §3.2.3). Both have explicit `llm_model_*` entries; the
#: fallback is Opus and says nothing while it overcharges.
GROUPING_TASK = "advisor_grouping"
REASON_TASK = "advisor_reason"


def is_abandoned(run: AdvisorRun, *, now: datetime | None = None) -> bool:
    """Whether a `pending` row has outlived any completion that could finish it.

    Generous on purpose: a run is at most two completions, and an over-eager
    deadline would let two real runs race. Compares status with ``==`` — a row
    from a fresh session holds a plain string, and ``is`` against the enum
    member silently never matches (shipped twice).
    """
    if run.status != AdvisorRunStatus.PENDING:
        return False
    started = run.created_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - started > RUN_ABANDONED_AFTER


async def create_pending_run(session: AsyncSession, user: User) -> AdvisorRun | None:
    """Reserve a row for the run, or decline because there is nothing to read.

    Returns `None` for a user with no applications at all: the spec's
    no-history rule is that the honest empty state costs nothing — no run row,
    no completion, nothing for a poller to watch fail.

    The one-in-flight rule is **not** checked here: the partial unique index
    is the enforcement, and the caller's flush is where a lost race surfaces.
    An application-level pre-check would be the raceable copy of it.
    """
    application_count = await session.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == user.id)
    )
    if not application_count:
        logger.info(
            "advisor run declined",
            extra={"user_id": str(user.id), "reason": "no_history"},
        )
        return None

    run = AdvisorRun(
        user_id=user.id,
        status=AdvisorRunStatus.PENDING,
        rules_version=ADVISOR_RULES_VERSION,
        dispositions=[],
    )
    session.add(run)
    await session.flush()
    return run


# -- prompt rendering (T014/T024/T036) ---------------------------------------

_RULES = f"""You are the Career Advisor: you maintain a small set of career memories —
falsifiable, evidence-backed claims about this person's job search — and you
revise them as evidence accumulates.

Rules, in order of importance:

1. Every number in a claim must appear verbatim among the facts you cite.
   You never compute a number yourself; the facts already carry every count,
   percentage and median you may need.
2. Every claim states at least one cited fact's numerator and denominator,
   as "N of M" or "N/M". A claim that cannot state its denominator is not
   worth remembering.
3. Word co-occurrence as co-occurrence. Never assert that one thing causes
   another.
4. A claim whose cited evidence includes any denominator below the
   floor of {SMALL_SAMPLE_FLOOR} is tentative — say so in its `tentative` field.
5. You may keep at most {ACTIVE_MEMORY_CAP} active memories. At that limit, creating a new
   one means retiring one you now value less, and saying why.
6. Every prior memory listed as [memory: <id>] below MUST appear in exactly
   one disposition: confirm it (cite the current facts that still support
   it), supersede it (point at your replacement claim, which states what
   changed), retire it (say why), or leave it open (say why the evidence is
   absent either way). Leaving a memory open is a decision you state, never
   a silence.
7. A memory marked [dismissed: ...] was dismissed by this person. Do not
   recreate its claim unless the evidence has materially changed.
8. Assign `priority` (0-100, with `priority_reason`) only to memories the
   person could act on."""


def _fact_lines(pack: EvidencePack) -> str:
    lines = []
    for fact in pack.facts:
        span = ""
        if fact.date_range:
            span = f", {fact.date_range[0].isoformat()} to {fact.date_range[1].isoformat()}"
        lines.append(
            f"[fact: {fact.fact_id}] {fact.value} (n={fact.numerator}/{fact.denominator}{span})"
        )
    return "\n".join(lines)


def _frozen_figures(memory: CareerMemory) -> str:
    facts = memory.evidence.get("facts", []) if isinstance(memory.evidence, dict) else []
    return "; ".join(
        f"{fact.get('fact_id')}: {fact.get('numerator')}/{fact.get('denominator')}"
        for fact in facts
        if isinstance(fact, dict)
    )


def render_reasoning_prompt(
    *,
    pack: EvidencePack,
    active: Sequence[CareerMemory],
    dismissed: Sequence[CareerMemory],
    history: Sequence[CareerMemory] = (),
) -> str:
    """The reasoning step's whole world.

    Only **active and tentative** memories render as `[memory: ...]` — they
    are the prior state a run must disposition (FR-013/FR-014). Superseded and
    retired rows are history and are deliberately not rendered at all
    (`history` is accepted so call sites cannot accidentally widen the active
    set: passing them here changes nothing, and the G3 test pins that).
    Dismissed rows render separately, marked, because their role is a
    prohibition rather than a prior (FR-021).
    """
    del history  # accepted and unused, on purpose — see the docstring

    sections = [_RULES, "\n## The evidence (cite facts by id)\n", _fact_lines(pack)]

    if active:
        sections.append("\n## Your current memories — disposition every one\n")
        for memory in active:
            sections.append(
                f"[memory: {memory.id}] ({memory.status}, kind={memory.kind}, "
                f"scope={memory.scope_kind}"
                + (f":{memory.scope_value}" if memory.scope_value else "")
                + f", confirmed {memory.last_confirmed_at.date().isoformat()}) "
                + f'"{memory.claim}" — frozen evidence: {_frozen_figures(memory)}'
            )
    else:
        sections.append(
            "\n## Your current memories\n\nNone yet — this is your first analysis "
            "of this person's history."
        )

    if dismissed:
        sections.append("\n## Dismissed by the user\n")
        for memory in dismissed:
            sections.append(
                f'[dismissed: {memory.id}] "{memory.claim}" — dismissed by the user; '
                "do not recreate this claim unless its evidence has materially changed."
            )

    sections.append(
        "\n## Your answer\n\nPropose the memories worth keeping (created), and "
        "disposition every [memory: ...] id above exactly once."
    )
    return "\n".join(sections)


# -- the run itself (T015/T023) ----------------------------------------------


async def _load_inputs(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[list[Application], list[MatchAnalysis], list[CareerMemory], list[CareerMemory]]:
    applications = list(
        (
            await session.scalars(
                select(Application)
                .where(Application.user_id == user_id)
                .order_by(Application.date_added)
            )
        ).all()
    )
    application_ids = [application.id for application in applications]
    analyses = (
        list(
            (
                await session.scalars(
                    select(MatchAnalysis).where(
                        MatchAnalysis.application_id.in_(application_ids),
                        MatchAnalysis.status == MatchStatus.READY,
                    )
                )
            ).all()
        )
        if application_ids
        else []
    )
    prior = list(
        (
            await session.scalars(
                select(CareerMemory)
                .where(
                    CareerMemory.user_id == user_id,
                    CareerMemory.status.in_([MemoryStatus.ACTIVE, MemoryStatus.TENTATIVE]),
                )
                .order_by(CareerMemory.created_at)
            )
        ).all()
    )
    dismissed = list(
        (
            await session.scalars(
                select(CareerMemory).where(
                    CareerMemory.user_id == user_id,
                    CareerMemory.status == MemoryStatus.RETIRED,
                    CareerMemory.retired_reason == USER_DISMISSED,
                )
            )
        ).all()
    )
    return applications, analyses, prior, dismissed


async def _apply_outcome(
    session: AsyncSession,
    run: AdvisorRun,
    outcome: GateOutcome,
    pack: EvidencePack,
    prior_by_id: dict[uuid.UUID, CareerMemory],
    now: datetime,
) -> None:
    """Persist everything the gate let through — in the caller's transaction,
    which commits once. A failure before that commit leaves the memory set
    byte-for-byte unchanged (SC-005)."""
    # Lineage is content and content is frozen at insert (the guard below the
    # model enforces exactly that), so a create that supersedes must be born
    # with its `supersedes_id` — resolved from the dispositions first.
    supersedes_by_create: dict[int, uuid.UUID] = {}
    for disposition in outcome.dispositions:
        index = disposition.superseding_create
        if disposition.action == DispositionAction.SUPERSEDED and index is not None:
            supersedes_by_create.setdefault(index, disposition.memory_id)

    created_rows: list[CareerMemory] = []
    for position, planned in enumerate(outcome.creates):
        proposal = planned.proposal
        memory = CareerMemory(
            user_id=run.user_id,
            advisor_run_id=run.id,
            claim=proposal.claim,
            kind=proposal.kind,
            scope_kind=proposal.scope_kind,
            scope_value=proposal.scope_value,
            evidence=freeze_evidence(proposal, pack),
            priority=proposal.priority,
            priority_reason=proposal.priority_reason,
            status=MemoryStatus.TENTATIVE if planned.tentative else MemoryStatus.ACTIVE,
            supersedes_id=supersedes_by_create.get(position),
            recreates_dismissed_id=planned.recreates_dismissed_id,
        )
        session.add(memory)
        created_rows.append(memory)

    # The journal rows below reference the new memories' server-generated ids,
    # so the inserts must reach the database (same transaction) first.
    if created_rows:
        await session.flush()

    # B4 (reproduced): the prior set is a pre-run snapshot, and a user
    # dismissal can land while the provider call is in flight. Re-read the
    # rows' statuses in THIS transaction, locked, and skip any memory that
    # went terminal — a background task must never overwrite `user_dismissed`
    # (FR-021's marker) or resurrect a terminal row. The user always wins.
    fresh_status: dict[uuid.UUID, str] = {}
    if prior_by_id:
        rows = await session.execute(
            select(CareerMemory.id, CareerMemory.status)
            .where(CareerMemory.id.in_(list(prior_by_id)))
            .with_for_update()
        )
        fresh_status = {row.id: str(row.status) for row in rows}

    for disposition in outcome.dispositions:
        memory = prior_by_id[disposition.memory_id]
        if fresh_status.get(disposition.memory_id) not in ("active", "tentative"):
            logger.info(
                "advisor disposition skipped",
                extra={
                    "run_id": str(run.id),
                    "gate": "stale_memory",
                    "detail": (
                        f"{disposition.memory_id} went terminal while the run was in "
                        "flight; its disposition is discarded"
                    ),
                },
            )
            continue
        if disposition.action == DispositionAction.CONFIRMED:
            memory.last_confirmed_at = now
            # A tentative memory whose fresh confirmation clears the floor is
            # promoted — the T033 path. Frozen evidence stays frozen; the
            # promotion reads the *delta*.
            if memory.status == MemoryStatus.TENTATIVE and disposition.evidence_delta:
                fresh = disposition.evidence_delta.get("facts", [])
                if fresh and all(
                    int(fact.get("denominator", 0)) >= SMALL_SAMPLE_FLOOR for fact in fresh
                ):
                    memory.status = MemoryStatus.ACTIVE
        elif disposition.action == DispositionAction.SUPERSEDED:
            memory.status = MemoryStatus.SUPERSEDED
        elif disposition.action == DispositionAction.RETIRED:
            memory.status = MemoryStatus.RETIRED
            memory.retired_reason = disposition.reason
        # LEFT_OPEN changes nothing on the row — that is its meaning.

        session.add(
            MemoryDisposition(
                run_id=run.id,
                memory_id=disposition.memory_id,
                action=disposition.action,
                reason=disposition.reason,
                evidence_delta=disposition.evidence_delta,
            )
        )

    # Creations are logged in the same journal, so "what did this run do" has
    # one answer. `created` rows carry no reason (the claim is the reason).
    for memory in created_rows:
        session.add(
            MemoryDisposition(
                run_id=run.id,
                memory_id=memory.id,
                action=DispositionAction.CREATED,
                reason=None,
                evidence_delta=None,
            )
        )


def _fail_run(run: AdvisorRun, recorder: UsageRecorder, reason: str, now: datetime) -> None:
    run.status = AdvisorRunStatus.FAILED
    run.error = reason
    run.completed_at = now
    _record_usage(run, recorder)


def _record_usage(run: AdvisorRun, recorder: UsageRecorder) -> None:
    """Constitution V, on both paths: what the run actually spent, per call,
    with per-task model attribution (a two-model run reported as one model is
    a recorded lesson)."""
    run.input_tokens = recorder.total_input_tokens
    run.output_tokens = recorder.total_output_tokens
    run.cost = recorder.total_cost
    run.is_fixture = recorder.any_fixture
    for call in recorder.calls:
        if call.task == GROUPING_TASK:
            run.grouping_model = call.model
        elif call.task == REASON_TASK:
            run.reason_model = call.model


async def run_advisor(
    session: AsyncSession, *, run_id: uuid.UUID, completion: StructuredCompletion
) -> None:
    """Fill in a pending run. Never raises — a background task has nowhere to
    raise to, and a failure that escaped would strand the row `pending`."""
    run = await session.get(AdvisorRun, run_id)
    # `==`, never `is`: this session did not create the row, so `status` is a
    # plain string here (the twice-shipped gotcha).
    if run is None or run.status != AdvisorRunStatus.PENDING:
        return

    recorder = UsageRecorder(inner=completion)
    now = datetime.now(UTC)

    try:
        applications, analyses, prior, dismissed = await _load_inputs(session, run.user_id)
        if not applications:
            _fail_run(run, recorder, "There is no application history to analyse.", now)
            await session.flush()
            return

        groupings, extra = await _grouping_step(session, recorder, run, applications, analyses)
        pack = build_evidence_pack(
            applications=applications,
            analyses=analyses,
            now=now,
            extra_facts=extra,
            groupings=groupings,
        )
        prompt = render_reasoning_prompt(pack=pack, active=prior, dismissed=dismissed)
        result = await recorder.complete(task=REASON_TASK, schema=AdvisorReasoning, prompt=prompt)

        outcome = apply_gate(
            result.value, pack=pack, active=prior, dismissed=dismissed, run_id=run.id
        )

        # B3 (reproduced): claim the transition atomically BEFORE writing
        # anything. A run reaped `failed` while this task was still alive must
        # stay failed — the entry-time pending check is stale by now, and an
        # unconditional write resurrected a terminal row and interleaved two
        # runs' memory writes. rowcount 0 means someone else ended this run:
        # roll back and discard the zombie's work entirely.
        claimed = await session.execute(
            update(AdvisorRun)
            .where(AdvisorRun.id == run.id, AdvisorRun.status == AdvisorRunStatus.PENDING)
            .values(status=AdvisorRunStatus.READY)
        )
        if getattr(claimed, "rowcount", 0) != 1:
            logger.warning(
                "advisor run went terminal while executing; discarding its work",
                extra={"run_id": str(run.id)},
            )
            await session.rollback()
            return

        await _apply_outcome(session, run, outcome, pack, {m.id: m for m in prior}, now)

        run.status = AdvisorRunStatus.READY
        run.completed_at = datetime.now(UTC)
        run.rules_version = pack.rules_version
        run.evidence_pack = pack.model_dump(mode="json")
        run.ops_proposed = outcome.proposed
        run.ops_applied = outcome.applied
        run.ops_discarded = outcome.discarded
        _record_usage(run, recorder)
        await session.flush()

        logger.info(
            "advisor run ready",
            extra={
                "run_id": str(run.id),
                "ops_proposed": outcome.proposed,
                "ops_applied": outcome.applied,
                "ops_discarded": outcome.discarded,
                "cost": str(recorder.total_cost),
            },
        )
    except DispositionDefect as defect:
        logger.warning(
            "advisor run defective",
            extra={"run_id": str(run_id), "defect": str(defect)},
        )
        await session.rollback()
        run = await session.get(AdvisorRun, run_id)
        if run is not None:
            _fail_run(
                run,
                recorder,
                "The reasoning step returned an incomplete answer.",
                datetime.now(UTC),
            )
            await session.flush()
    except Exception as exc:  # Recorded on the row, never re-raised.
        logger.warning(
            "advisor run failed",
            extra={"run_id": str(run_id), "error": exc.__class__.__name__},
        )
        await session.rollback()
        run = await session.get(AdvisorRun, run_id)
        if run is not None:
            _fail_run(run, recorder, "The analysis could not be completed.", datetime.now(UTC))
            await session.flush()


# -- the grouping step (US3, research.md D3) ---------------------------------

_GROUPING_RULES = """You bucket the enumerated items into named groups so that counting can
run over them. Rules:

1. member_ids may contain ONLY ids listed below. Never invent an id.
2. Group requirement rows ([req: ...]) that name the same skill under one
   'skill' group — '5+ years of AWS' and 'Amazon Web Services' are the same
   skill worded twice. An id belongs to at most one skill group.
3. Group application titles ([app: ...]) into 'role_family' groups — 'Backend
   Engineer' and 'Backend Developer' are one family. An id belongs to at most
   one role_family group.
4. Omit a group you cannot fill with at least 2 members unless the item is
   clearly a skill worth tracking alone."""


def render_grouping_prompt(
    *,
    titles: dict[uuid.UUID, str],
    requirement_rows: Sequence[MatchRequirement],
) -> str:
    lines = [_GROUPING_RULES, "\n## Application titles\n"]
    lines.extend(
        f"[app: {application_id}] {title}"
        for application_id, title in sorted(titles.items(), key=lambda item: str(item[0]))
    )
    if requirement_rows:
        lines.append("\n## Requirement rows (verbatim posting wording)\n")
        lines.extend(
            f"[req: {row.id}] {row.text_} (verdict: {row.verdict}, importance: {row.importance})"
            for row in requirement_rows
        )
    return "\n".join(lines)


async def _grouping_step(
    session: AsyncSession,
    recorder: UsageRecorder,
    run: AdvisorRun,
    applications: Sequence[Application],
    analyses: Sequence[MatchAnalysis],
) -> tuple[list[EvidenceGrouping], list[EvidenceFact]]:
    """The optional Haiku call. **Skipped entirely when no ready analysis
    exists** — role-family facts need match scores and skill facts need
    requirement rows, so with zero analysed applications the call could only
    return groups nothing can count over, and a run must not spend a
    completion to learn nothing. (Amends the plan's title-count condition:
    titles alone produce no countable Tier 2 fact.)"""
    if not analyses:
        return [], []

    requirement_rows = list(
        (
            await session.scalars(
                select(MatchRequirement).where(
                    MatchRequirement.analysis_id.in_([analysis.id for analysis in analyses])
                )
            )
        ).all()
    )
    titles = {application.id: application.job_title for application in applications}

    prompt = render_grouping_prompt(titles=titles, requirement_rows=requirement_rows)
    result = await recorder.complete(task=GROUPING_TASK, schema=GroupingProposal, prompt=prompt)

    known: set[uuid.UUID] = {row.id for row in requirement_rows} | set(titles)
    surviving, _dropped = validate_grouping(result.value, known_ids=known, run_id=run.id)

    analysis_to_application = {analysis.id: analysis.application_id for analysis in analyses}
    extra = tier2_facts(
        groupings=surviving,
        requirement_rows=requirement_rows,
        analysis_to_application=analysis_to_application,
        analysed_application_ids=set(analysis_to_application.values()),
        analyses=analyses,
    )
    return surviving, extra
