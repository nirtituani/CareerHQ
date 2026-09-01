"""The deterministic evidence pack (T010, spec FR-005/FR-006, research.md D2).

Pure functions over model instances — no session, no provider, no I/O — which
is what makes "the LLM is never the source of a number" testable at all: every
fact here is arithmetic the suite can redo.

The properties that matter:

* **Determinism** — same rows, same pack, byte for byte (FR-006). SC-001's
  audit recomputes frozen facts later; that only means anything if the
  computation is a function of its inputs.
* **Denominators and record ids on every fact** — a fact that cannot say what
  it counted cannot be audited.
* **Percentages precomputed** — the model must never have a reason to do
  arithmetic, so any percentage a claim could want is already a rendered
  number in some fact's `value`.
* **Legacy rows stay out of skill denominators** — `requirements IS NULL`
  rows are refused by scoreability and must not inflate any analysed-postings
  count (FR-011).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from careerhq.application.advisor_evidence import build_evidence_pack
from careerhq.domain.models import Application, MatchAnalysis, MatchStatus, NormalizedStatus

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _application(
    *,
    status: NormalizedStatus = NormalizedStatus.APPLIED,
    added_days_ago: int = 30,
    applied_days_ago: int | None = 25,
    rating: int = 0,
    requirements: list[str] | None = None,
    title: str = "Backend Engineer",
) -> Application:
    application = Application(
        user_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        job_title=title,
        status=status.value.title(),
        normalized_status=status,
        imported_match_rating=rating,
        requirements=requirements,
    )
    application.id = uuid.uuid4()
    application.date_added = NOW - timedelta(days=added_days_ago)
    application.date_applied = (
        NOW - timedelta(days=applied_days_ago) if applied_days_ago is not None else None
    )
    return application


def _analysis(application: Application, *, score: int = 70) -> MatchAnalysis:
    analysis = MatchAnalysis(
        application_id=application.id,
        status=MatchStatus.READY,
        criteria_version="test",
        overall_score=score,
        requirements=[],
    )
    analysis.id = uuid.uuid4()
    return analysis


def _fact(pack, fact_id: str):  # type: ignore[no-untyped-def]
    matches = [fact for fact in pack.facts if fact.fact_id == fact_id]
    assert matches, f"no fact {fact_id}; pack has {sorted(f.fact_id for f in pack.facts)}"
    return matches[0]


def _sample() -> tuple[list[Application], list[MatchAnalysis]]:
    applications = [
        _application(status=NormalizedStatus.REJECTED, added_days_ago=90, applied_days_ago=85),
        _application(status=NormalizedStatus.REJECTED, added_days_ago=60, applied_days_ago=50),
        _application(status=NormalizedStatus.APPLIED, added_days_ago=40, applied_days_ago=35),
        _application(
            status=NormalizedStatus.INTERVIEWING,
            added_days_ago=20,
            applied_days_ago=15,
            requirements=["Python", "AWS"],
            rating=4,
        ),
        _application(status=NormalizedStatus.WISHLIST, added_days_ago=5, applied_days_ago=None),
    ]
    analyses = [_analysis(applications[3])]
    return applications, analyses


def test_the_pack_is_deterministic() -> None:
    applications, analyses = _sample()
    first = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    second = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    assert first.model_dump() == second.model_dump()
    assert first.rules_version


def test_every_fact_carries_denominator_and_records() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    assert len(pack.facts) >= 6, f"examined {len(pack.facts)} facts"
    for fact in pack.facts:
        assert fact.denominator > 0, f"{fact.fact_id} has no denominator"
        assert fact.record_ids, f"{fact.fact_id} names no records"
        assert fact.basis
        assert str(fact.numerator) in fact.value or fact.numerator == 0


def test_rejection_rate_counts_and_precomputes_the_percentage() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    fact = _fact(pack, "outcome.rejection_rate.global")
    assert fact.numerator == 2
    assert fact.denominator == 5
    assert "40" in fact.value, "the percentage must be precomputed, not left to the model"
    assert set(fact.record_ids) == {a.id for a in applications if a.normalized_status == "rejected"}


def test_status_distribution_covers_every_present_status() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    for status, expected in (("rejected", 2), ("applied", 1), ("interviewing", 1), ("wishlist", 1)):
        fact = _fact(pack, f"status.distribution.{status}")
        assert fact.numerator == expected
        assert fact.denominator == 5


def test_time_to_apply_states_its_sample_size() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    fact = _fact(pack, "timing.median_days_to_apply.global")
    # Four applications carry both dates; the median gap is 5 days.
    assert fact.denominator == 4
    assert fact.numerator == 5
    assert set(fact.record_ids) == {a.id for a in applications if a.date_applied is not None}


def test_coverage_is_the_honesty_fact() -> None:
    """FR-011: the insufficient-data answer cites this fact's own numbers."""
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    fact = _fact(pack, "coverage.analysed.global")
    assert fact.numerator == 1
    assert fact.denominator == 5
    assert "1" in fact.value and "5" in fact.value


def test_legacy_rows_enter_no_analysed_denominator() -> None:
    """`requirements IS NULL` rows cannot be analysed; no fact scoped to
    analysed postings may count them (the data-honesty rule)."""
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    analysed_scoped = [f for f in pack.facts if f.fact_id.startswith("coverage.analysed")]
    assert analysed_scoped, "the coverage fact is missing"
    legacy_ids = {a.id for a in applications if a.requirements is None}
    for fact in analysed_scoped:
        assert fact.numerator <= 1  # only the one analysed application
        assert not (set(fact.record_ids[: fact.numerator]) & legacy_ids)


def test_self_rating_distribution_is_labelled_self_assessment() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    fact = _fact(pack, "selfrating.rated.global")
    assert fact.numerator == 1  # one application rated > 0
    assert fact.denominator == 5
    assert "self" in fact.basis.lower()


def test_volume_by_month_sums_to_the_total() -> None:
    applications, analyses = _sample()
    pack = build_evidence_pack(applications=applications, analyses=analyses, now=NOW)
    monthly = [f for f in pack.facts if f.fact_id.startswith("volume.month.")]
    assert monthly, "no monthly volume facts"
    assert sum(f.numerator for f in monthly) == 5
    for fact in monthly:
        assert fact.denominator == 5


# -- Tier 2: grouped skill and role-family facts (T032, US3) -----------------


def test_tier2_facts_count_through_the_grouping_and_respect_verdicts() -> None:
    from careerhq.application.advisor_evidence import tier2_facts
    from careerhq.domain.models import (
        MatchRequirement,
        RequirementKind,
        RequirementVerdict,
    )
    from careerhq.domain.schemas.advisor import EvidenceGrouping

    applications, _ = _sample()
    analysed = [applications[0], applications[1], applications[3]]
    analyses = [_analysis(app, score=60 + i * 10) for i, app in enumerate(analysed)]
    analysis_to_app = {a.id: a.application_id for a in analyses}

    def requirement(analysis, text: str, verdict: RequirementVerdict):  # type: ignore[no-untyped-def]
        row = MatchRequirement(
            analysis_id=analysis.id,
            ordinal=0,
            text_=text,
            kind=RequirementKind.MUST_HAVE,
            importance=70,
            verdict=verdict,
            evidence=None if verdict == RequirementVerdict.UNVERIFIED else "quoted",
        )
        row.id = uuid.uuid4()
        return row

    rows = [
        requirement(analyses[0], "AWS", RequirementVerdict.GAP),
        requirement(analyses[1], "5+ years of AWS", RequirementVerdict.PARTIAL),
        requirement(analyses[2], "Amazon Web Services", RequirementVerdict.CONFIRMED),
        requirement(analyses[0], "Python", RequirementVerdict.CONFIRMED),
    ]
    aws_members = [rows[0].id, rows[1].id, rows[2].id]
    groupings = [
        EvidenceGrouping(group_id="g_aws", label="AWS", group_kind="skill", member_ids=aws_members),
        EvidenceGrouping(
            group_id="g_backend",
            label="Backend",
            group_kind="role_family",
            member_ids=[app.id for app in analysed],
        ),
    ]

    facts = tier2_facts(
        groupings=groupings,
        requirement_rows=rows,
        analysis_to_application=analysis_to_app,
        analysed_application_ids={app.id for app in analysed},
        analyses=analyses,
    )
    by_id = {fact.fact_id: fact for fact in facts}
    assert len(by_id) >= 3, f"examined {sorted(by_id)}"

    frequency = by_id["tier2.requirement.g_aws"]
    assert frequency.numerator == 3, "AWS appears in all three analysed postings"
    assert frequency.denominator == 3, "denominator is analysed postings, never all applications"
    assert set(frequency.record_ids) == set(aws_members), "counts trace to real requirement rows"

    gap = by_id["tier2.gap.g_aws"]
    assert gap.numerator == 2, "gap counts gap and partial verdicts, never confirmed"
    assert gap.denominator == 3
    assert set(gap.record_ids) == {rows[0].id, rows[1].id}

    score = by_id["tier2.match_score.g_backend"]
    assert score.numerator == 70, "mean of 60/70/80, precomputed"
    assert score.denominator == 3


# -- T045 regression: imported dates can be inconsistent (date_applied < date_added) --


def test_inconsistent_dates_do_not_crash_and_surface_as_their_own_fact() -> None:
    """Real imported history has applications whose date_applied precedes
    date_added (JobTracker set the two independently). A negative 'days to
    apply' is not a duration — it means the dates are inconsistent. The pack
    must build, compute the median only over coherent rows, and surface the
    inconsistent ones as evidence rather than hiding them."""
    coherent = _application(added_days_ago=40, applied_days_ago=35)  # applied after added
    backwards_1 = _application(added_days_ago=10, applied_days_ago=30)  # applied BEFORE added
    backwards_2 = _application(added_days_ago=5, applied_days_ago=20)
    applications = [coherent, backwards_1, backwards_2]

    pack = build_evidence_pack(applications=applications, analyses=[], now=NOW)

    median = _fact(pack, "timing.median_days_to_apply.global")
    assert median.numerator >= 0, "the median is computed over coherent rows only"
    assert median.numerator == 5 and median.denominator == 1
    assert set(median.record_ids) == {coherent.id}

    flagged = _fact(pack, "timing.inconsistent_dates.global")
    assert flagged.numerator == 2, "both backwards rows are surfaced"
    assert flagged.denominator == 3, "denominator is all rows carrying both dates"
    assert set(flagged.record_ids) == {backwards_1.id, backwards_2.id}
    assert "before" in flagged.value.lower()


def test_all_dates_inconsistent_yields_only_the_data_quality_fact() -> None:
    """The real account's shape: nearly every row is backwards. No median is
    emitted (nothing coherent to measure), only the honest inconsistency fact."""
    applications = [
        _application(added_days_ago=5, applied_days_ago=30),
        _application(added_days_ago=3, applied_days_ago=25),
    ]
    pack = build_evidence_pack(applications=applications, analyses=[], now=NOW)
    ids = {fact.fact_id for fact in pack.facts}
    assert "timing.median_days_to_apply.global" not in ids
    assert "timing.inconsistent_dates.global" in ids
    assert _fact(pack, "timing.inconsistent_dates.global").numerator == 2
