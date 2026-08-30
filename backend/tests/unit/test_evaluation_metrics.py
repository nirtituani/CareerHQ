"""Metric definitions, and the four rules every one of them obeys (T022-T026).

1. **It returns `n` with the value.** A metric over zero cases is *not measured*,
   never `0` — `plan_adherence` already draws that distinction and a posting with
   no requirements is already "nothing to score against, not a zero".
2. **It reads only persisted records.** Nothing is derived from a value the system
   did not store.
3. **It is versioned.** Changing how a number is computed is a new version.
4. **It refuses rather than guesses** when the run it was handed cannot support the
   claim.
"""

from __future__ import annotations

import pytest

from careerhq.application.evaluation.metrics import (
    METRIC_VERSION,
    ClaimFacts,
    FindingRecord,
    GuidelineRecord,
    MetricValue,
    RequirementFacts,
    calibration,
    coverage,
    grounding,
    retrieval_quality,
)

# -- Rule 1: n travels with the value ----------------------------------------


def test_a_metric_over_nothing_is_not_measured_rather_than_zero() -> None:
    empty = MetricValue.not_measured(reason="no cases")
    assert empty.value is None
    assert empty.n == 0
    assert empty.measured is False
    assert "no cases" in empty.reason


def test_a_measured_metric_refuses_to_be_built_without_an_n() -> None:
    with pytest.raises(ValueError):
        MetricValue(value=0.5, n=0)


def test_a_zero_value_and_an_unmeasured_metric_are_different_objects() -> None:
    """The distinction this whole rule exists for."""
    genuine_zero = MetricValue(value=0.0, n=7)
    assert genuine_zero.measured is True
    assert genuine_zero.value == 0.0
    assert genuine_zero != MetricValue.not_measured(reason="nothing to score")


def test_every_metric_is_versioned() -> None:
    assert METRIC_VERSION


# -- Grounding accuracy (FR-014, FR-015, SC-006) -----------------------------


def test_grounding_counts_proposals_that_trace_to_a_profile_fact() -> None:
    result = grounding(
        claims=[
            ClaimFacts(
                item_id="i1",
                source_item_id="s1",
                proposed_text="rewritten",
                original_text="a",
                final_text="rewritten",
            ),
            ClaimFacts(
                item_id="i2",
                source_item_id="s2",
                proposed_text="rewritten",
                original_text="b",
                final_text="rewritten",
            ),
            ClaimFacts(
                item_id="i3",
                source_item_id=None,
                proposed_text="invented summary",
                original_text="c",
                final_text="invented summary",
            ),
        ],
        findings=[],
    )
    assert result["traceable"].n == 3
    assert result["traceable"].value == pytest.approx(2 / 3)


def test_grounding_reports_the_ungrounded_count_the_reviewer_caught() -> None:
    result = grounding(
        claims=[
            ClaimFacts(
                item_id="i1",
                source_item_id="s1",
                proposed_text=None,
                original_text="a",
                final_text="a",
            ),
        ],
        findings=[FindingRecord(item_id="i1", kind="ungrounded", quoted_text="led a team of 40")],
    )
    assert result["ungrounded_caught"] == 1


def test_no_ungrounded_claim_may_survive_into_a_persisted_proposal() -> None:
    """SC-006 — the Principle III release-blocker, as a number.

    `finalise()` discards an ungrounded proposal *before any row is written* and
    restores the owner's wording, so the correct value is always 0. This metric is
    what would notice if that stopped.
    """
    clean = grounding(
        claims=[
            ClaimFacts(
                item_id="i1",
                source_item_id="s1",
                proposed_text=None,
                original_text="a",
                final_text="a",
            )
        ],
        findings=[FindingRecord(item_id="i1", kind="ungrounded", quoted_text="led a team of 40")],
    )
    assert clean["persisted_ungrounded"] == 0

    leaked = grounding(
        claims=[
            ClaimFacts(
                item_id="i1",
                source_item_id="s1",
                proposed_text="Led a team of 40",
                original_text="a",
                final_text="Led a team of 40",
            )
        ],
        findings=[FindingRecord(item_id="i1", kind="ungrounded", quoted_text="Led a team of 40")],
    )
    assert leaked["persisted_ungrounded"] == 1, (
        "a fabricated claim reached an approve button; this is the release blocker"
    )


def test_grounding_over_no_claims_is_not_measured() -> None:
    assert grounding(claims=[], findings=[])["traceable"].measured is False


# -- Requirement coverage (FR-016) -------------------------------------------


def test_must_have_coverage_is_reported_separately_from_overall() -> None:
    """A resume addressing every nice-to-have and no must-have is not 50% good."""
    requirements = [
        RequirementFacts(text="Kubernetes", must_have=True),
        RequirementFacts(text="Go", must_have=True),
        RequirementFacts(text="Public speaking", must_have=False),
        RequirementFacts(text="Open source", must_have=False),
    ]
    result = coverage(
        requirements=requirements,
        uncovered=[
            FindingRecord(item_id=None, kind="uncovered", detail="Kubernetes is never addressed"),
            FindingRecord(item_id=None, kind="uncovered", detail="Go does not appear"),
        ],
    )
    assert result["overall"].value == pytest.approx(0.5)
    assert result["must_have"].value == pytest.approx(0.0)
    assert result["must_have"].n == 2


def test_coverage_reports_findings_it_could_not_match_to_a_requirement() -> None:
    """The crudeness has to be visible, or the number reads as exact.

    An `uncovered` finding carries free text and no requirement reference — the
    schema forbids it an item, deliberately — so matching is textual and fallible.
    """
    result = coverage(
        requirements=[RequirementFacts(text="Kubernetes", must_have=True)],
        uncovered=[
            FindingRecord(item_id=None, kind="uncovered", detail="no evidence of leadership")
        ],
    )
    assert result["unmatched_findings"] == 1
    assert result["overall"].value == pytest.approx(1.0)


def test_coverage_of_a_posting_with_no_requirements_is_not_measured() -> None:
    """ "Nothing to score against, not a zero" — the FR-006 rule, reused."""
    result = coverage(requirements=[], uncovered=[])
    assert result["overall"].measured is False
    assert result["must_have"].measured is False


def test_a_posting_with_no_must_haves_reports_must_have_as_not_measured() -> None:
    result = coverage(
        requirements=[RequirementFacts(text="Nice to have", must_have=False)], uncovered=[]
    )
    assert result["overall"].measured is True
    assert result["must_have"].measured is False


# -- Retrieval quality (FR-017) ----------------------------------------------


def test_pinned_integrity_rules_are_reported_apart_from_selected_ones() -> None:
    """Pinned rules are relevant by construction. Counting them flatters the metric."""
    result = retrieval_quality(
        guidelines=[
            GuidelineRecord(document_slug="integrity-no-fabrication", source_type="integrity"),
            GuidelineRecord(document_slug="integrity-owner-authority", source_type="integrity"),
            GuidelineRecord(document_slug="role-technical-depth", source_type="role"),
            GuidelineRecord(document_slug="universal-verbs", source_type="universal"),
        ],
        relevant_slugs={"role-technical-depth"},
    )
    assert result["pinned"] == 2
    assert result["selected"] == 2
    assert result["pinned_proportion"].value == pytest.approx(0.5)
    assert result["selected_relevance"].value == pytest.approx(0.5)
    assert result["selected_relevance"].n == 2


def test_relevance_is_not_computed_over_the_pinned_set() -> None:
    """The whole point: a run returning only integrity rules has no relevance figure."""
    result = retrieval_quality(
        guidelines=[
            GuidelineRecord(document_slug="integrity-no-fabrication", source_type="integrity")
        ],
        relevant_slugs=set(),
    )
    assert result["selected_relevance"].measured is False


def test_retrieval_quality_without_a_relevance_judgement_reports_structure_only() -> None:
    result = retrieval_quality(
        guidelines=[GuidelineRecord(document_slug="role-technical-depth", source_type="role")],
        relevant_slugs=None,
    )
    assert result["pinned_proportion"].measured is True
    assert result["selected_relevance"].measured is False
    assert "no relevance judgement" in result["selected_relevance"].reason


# -- Match-score calibration (FR-018) ----------------------------------------


def test_calibration_reports_its_sample_size_rather_than_implying_one() -> None:
    result = calibration([(80, 4.0), (60, 3.0), (40, 2.0), (20, 1.0)])
    assert result["correlation"].n == 4
    assert result["correlation"].value is not None
    assert result["correlation"].value > 0.9


def test_calibration_refuses_a_sample_too_small_to_mean_anything() -> None:
    assert calibration([(80, 4.0), (60, 3.0)])["correlation"].measured is False


def test_calibration_of_a_constant_score_is_not_measured() -> None:
    """No variance, no correlation — and a spurious 0.0 would read as "uncorrelated"."""
    assert (
        calibration([(50, 1.0), (50, 2.0), (50, 3.0), (50, 4.0)])["correlation"].measured is False
    )
