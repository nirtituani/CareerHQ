"""The deterministic evidence pack: every number the advisor may ever say.

Pure functions over loaded model instances — no session, no provider, no I/O
(the `finalisation_rules.py` shape). The reasoning step receives these facts
and cites them by id; it is **never** the source of a number (spec FR-005).
Percentages and medians are precomputed as rendered digits inside `value`, so
the model has no arithmetic left to do — a model doing arithmetic is the one
collapse that would break FR-005 while looking helpful (research.md D2).

Determinism is a contract, not a habit (FR-006): the pack is a function of
(rows, as-of, rules version). Facts are emitted in sorted-slug order, months
in calendar order, statuses in enum order — anything unstable here would make
SC-001's recompute-and-compare audit flaky instead of binding.

Fact-id grammar: `<family>.<measure>.<scope>` — e.g.
`outcome.rejection_rate.global`, `volume.month.2026-07`. Tier 2 families
(requirement frequencies over grouped skills) are added by US3 and follow the
same grammar under `tier2.`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from statistics import median

from careerhq.application.advisor_rules import ADVISOR_RULES_VERSION
from careerhq.domain.models import Application, MatchAnalysis, MatchStatus
from careerhq.domain.schemas.advisor import EvidenceFact, EvidencePack


def _pct(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0


def _sorted_ids(applications: Sequence[Application]) -> list:  # type: ignore[type-arg]
    return sorted((a.id for a in applications), key=str)


def build_evidence_pack(
    *,
    applications: Sequence[Application],
    analyses: Sequence[MatchAnalysis],
    now: datetime | None = None,
    extra_facts: Sequence[EvidenceFact] = (),
) -> EvidencePack:
    """Compute the Tier 1 pack. `extra_facts` is where US3's grouping-derived
    Tier 2 facts join, after deterministic counting over proposed groups."""
    as_of = now or datetime.now(UTC)
    facts: list[EvidenceFact] = []
    total = len(applications)

    if total:
        facts.extend(_status_distribution(applications, total))
        facts.extend(_rejection_rate(applications, total))
        facts.extend(_volume_by_month(applications, total))
        facts.extend(_time_to_apply(applications))
        facts.extend(_self_rating(applications, total))
        facts.extend(_coverage(applications, analyses, total))

    facts.extend(extra_facts)
    facts.sort(key=lambda fact: fact.fact_id)

    return EvidencePack(as_of=as_of, rules_version=ADVISOR_RULES_VERSION, facts=facts)


def _status_distribution(applications: Sequence[Application], total: int) -> list[EvidenceFact]:
    by_status: dict[str, list[Application]] = defaultdict(list)
    for application in applications:
        # `==` semantics: a fresh-session row holds a plain string.
        by_status[str(application.normalized_status)].append(application)

    return [
        EvidenceFact(
            fact_id=f"status.distribution.{status}",
            kind="status",
            scope_kind="status",
            scope_value=status,
            numerator=len(rows),
            denominator=total,
            value=(
                f"{len(rows)} of {total} applications ({_pct(len(rows), total)}%) "
                f"are currently '{status}'"
            ),
            record_ids=_sorted_ids(rows),
            basis="applications grouped by normalized_status",
        )
        for status, rows in sorted(by_status.items())
    ]


def _rejection_rate(applications: Sequence[Application], total: int) -> list[EvidenceFact]:
    rejected = [a for a in applications if str(a.normalized_status) == "rejected"]
    return [
        EvidenceFact(
            fact_id="outcome.rejection_rate.global",
            kind="outcome",
            scope_kind="global",
            numerator=len(rejected),
            denominator=total,
            value=(
                f"{len(rejected)} of {total} applications "
                f"({_pct(len(rejected), total)}%) ended rejected"
            ),
            record_ids=_sorted_ids(rejected),
            basis="applications whose normalized_status is rejected, over all applications",
        )
    ]


def _volume_by_month(applications: Sequence[Application], total: int) -> list[EvidenceFact]:
    by_month: dict[str, list[Application]] = defaultdict(list)
    for application in applications:
        by_month[application.date_added.strftime("%Y-%m")].append(application)

    return [
        EvidenceFact(
            fact_id=f"volume.month.{month}",
            kind="volume",
            scope_kind="global",
            numerator=len(rows),
            denominator=total,
            value=f"{len(rows)} of {total} applications were added in {month}",
            record_ids=_sorted_ids(rows),
            basis="applications grouped by the month of date_added",
        )
        for month, rows in sorted(by_month.items())
    ]


def _time_to_apply(applications: Sequence[Application]) -> list[EvidenceFact]:
    dated = [a for a in applications if a.date_applied is not None]
    if not dated:
        return []
    gaps = sorted((a.date_applied - a.date_added).days for a in dated)  # type: ignore[operator]
    days = int(median(gaps))
    return [
        EvidenceFact(
            fact_id="timing.median_days_to_apply.global",
            kind="timing",
            scope_kind="global",
            numerator=days,
            denominator=len(dated),
            value=(
                f"median {days} days from adding a job to applying, "
                f"over the {len(dated)} applications carrying both dates"
            ),
            record_ids=_sorted_ids(dated),
            basis=(
                "median of (date_applied - date_added) in days; numerator is the median, "
                "denominator the sample size"
            ),
        )
    ]


def _self_rating(applications: Sequence[Application], total: int) -> list[EvidenceFact]:
    rated = [a for a in applications if a.imported_match_rating]
    counts = Counter(a.imported_match_rating for a in rated)
    facts = [
        EvidenceFact(
            fact_id="selfrating.rated.global",
            kind="selfrating",
            scope_kind="global",
            numerator=len(rated),
            denominator=total,
            value=(f"{len(rated)} of {total} applications carry a self-assessed match rating"),
            record_ids=_sorted_ids(rated),
            basis=(
                "applications with imported_match_rating > 0 — the user's own "
                "self-assessment at import time, not a computed score"
            ),
        )
    ]
    facts.extend(
        EvidenceFact(
            fact_id=f"selfrating.value.{rating}",
            kind="selfrating",
            scope_kind="global",
            numerator=count,
            denominator=len(rated),
            value=f"{count} of the {len(rated)} self-rated applications were rated {rating}/5",
            record_ids=_sorted_ids([a for a in rated if a.imported_match_rating == rating]),
            basis="self-assessed ratings grouped by value; denominator is rated rows only",
        )
        for rating, count in sorted(counts.items())
    )
    return facts


def _coverage(
    applications: Sequence[Application], analyses: Sequence[MatchAnalysis], total: int
) -> list[EvidenceFact]:
    """FR-011's honesty fact: how much of the history skill-level claims may
    speak for. Only `ready` analyses count, and only one per application —
    a re-run is the same application, not more coverage."""
    ready_app_ids = {
        analysis.application_id
        for analysis in analyses
        if str(analysis.status) == str(MatchStatus.READY)
    }
    analysed = [a for a in applications if a.id in ready_app_ids]
    return [
        EvidenceFact(
            fact_id="coverage.analysed.global",
            kind="coverage",
            scope_kind="global",
            numerator=len(analysed),
            denominator=total,
            value=(
                f"{len(analysed)} of {total} applications have a completed match analysis — "
                "skill-level patterns can only speak for those"
            ),
            record_ids=_sorted_ids(analysed),
            basis=(
                "applications holding at least one ready match analysis; legacy rows "
                "without posting content cannot be analysed and are never counted"
            ),
        )
    ]
