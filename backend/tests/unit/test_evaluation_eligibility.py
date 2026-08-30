"""What the harness refuses to report on, and why (T009-T011, T013, T033).

**A measurement that cannot refuse a mocked arm, an empty corpus or a fallback is
a number with no claim attached.** Every test here is about a refusal, and every
refusal must *name what it found* — a message saying only "ineligible" sends the
reader to look up something the refusal already knew.
"""

from __future__ import annotations

import pytest

from careerhq.application.evaluation.eligibility import (
    Fingerprint,
    IncomparableError,
    IneligibleRunError,
    RunProvenance,
    assert_comparable,
    assert_reportable,
)

SHIPPING = {
    "tailor_plan": "anthropic/claude-sonnet-5",
    "tailor_draft": "anthropic/claude-sonnet-5",
    "tailor_review": "anthropic/claude-opus-5",
}


def _clean(**overrides: object) -> RunProvenance:
    base: dict[str, object] = {
        "run_id": "r1",
        "used_fixture": False,
        "guidance_used": "corpus",
        "guidance_intended": None,
        "model_config_used": dict(SHIPPING),
        "profile_is_benchmark": True,
        "status": "succeeded",
    }
    base.update(overrides)
    return RunProvenance(**base)  # type: ignore[arg-type]


def test_a_clean_run_is_reportable() -> None:
    assert_reportable(_clean(), shipping_mix=SHIPPING)


def test_a_fixture_run_is_refused_and_the_refusal_names_the_fixture_gateway() -> None:
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(_clean(used_fixture=True), shipping_mix=SHIPPING)
    assert "fixture" in str(excinfo.value).lower()


def test_a_run_that_fell_back_to_the_static_rubric_is_refused_by_name() -> None:
    """Intent plus outcome, with **no schema column**.

    The runner knows what it pointed a run at and records it in the result artifact;
    the snapshot records what the run actually used. The two disagreeing *is* the
    fallback, and both halves already exist.
    """
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(
            _clean(guidance_intended="corpus", guidance_used="static"), shipping_mix=SHIPPING
        )
    message = str(excinfo.value)
    assert "fell back" in message.lower()
    assert "'static'" in message and "'corpus'" in message


def test_a_deliberately_static_run_is_not_mistaken_for_a_fallback() -> None:
    """The SC-008 baseline arm is static on purpose and must not be refused for it.

    An earlier draft inferred "retrieval that fell back" from the absence of content
    hashes, which would have refused every legitimate static arm — including the
    baseline the whole cost measurement rests on — for a fault it did not have.
    """
    assert_reportable(
        _clean(guidance_intended="static", guidance_used="static"), shipping_mix=SHIPPING
    )


def test_a_claim_about_retrieval_needs_a_run_that_actually_retrieved() -> None:
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(
            _clean(guidance_used="static"),
            shipping_mix=SHIPPING,
            require_corpus_guidance=True,
        )
    assert "actually retrieved" in str(excinfo.value)


def test_a_run_that_recorded_no_guidance_is_refused() -> None:
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(_clean(guidance_used="none"), shipping_mix=SHIPPING)
    assert "no guidance" in str(excinfo.value)


def test_a_run_on_a_different_model_mix_is_refused_and_the_task_is_named() -> None:
    off_mix = dict(SHIPPING) | {"tailor_review": "anthropic/claude-sonnet-5"}
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(_clean(model_config_used=off_mix), shipping_mix=SHIPPING)
    message = str(excinfo.value)
    assert "tailor_review" in message
    assert "claude-sonnet-5" in message


def test_a_run_against_a_non_benchmark_profile_is_refused() -> None:
    """FR-013. A test seeded against the real profile has already merged a CV into it."""
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(_clean(profile_is_benchmark=False), shipping_mix=SHIPPING)
    assert "profile" in str(excinfo.value).lower()


def test_a_failed_run_is_refused_on_status_not_on_missing_guidance() -> None:
    """Slice 006 wrote this rule down: filter on `status`, never on `guidelines_used`.

    A failed run can carry guidance it never used.
    """
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(_clean(status="failed"), shipping_mix=SHIPPING)
    assert "status" in str(excinfo.value).lower()


def test_every_reason_is_reported_not_only_the_first() -> None:
    """A run wrong in three ways should not need three runs to discover it."""
    with pytest.raises(IneligibleRunError) as excinfo:
        assert_reportable(
            _clean(
                used_fixture=True,
                guidance_intended="corpus",
                guidance_used="static",
                profile_is_benchmark=False,
            ),
            shipping_mix=SHIPPING,
        )
    message = str(excinfo.value).lower()
    assert "fixture" in message and "fell back" in message and "profile" in message


# -- FR-031: comparability ----------------------------------------------------


def _fingerprint(**overrides: object) -> Fingerprint:
    base: dict[str, object] = {
        "benchmark_set": "v1",
        "metric_version": "1.0.0",
        "finalisation_rules_version": "v1",
        "guideline_source": "retrieval",
        "corpus_identity": "18/79/abc",
        "embedding_model": "all-MiniLM-L6-v2",
        "pricing_basis": "litellm-2026-08-29",
        "model_config": dict(SHIPPING),
    }
    base.update(overrides)
    return Fingerprint(**base)  # type: ignore[arg-type]


def test_identical_fingerprints_compare() -> None:
    assert_comparable(_fingerprint(), _fingerprint(), under_test=set())


def test_a_corpus_edit_makes_two_runs_incomparable() -> None:
    with pytest.raises(IncomparableError) as excinfo:
        assert_comparable(
            _fingerprint(), _fingerprint(corpus_identity="18/80/def"), under_test=set()
        )
    assert "corpus_identity" in str(excinfo.value)


def test_a_pricing_change_makes_two_runs_incomparable() -> None:
    """A percentage with a baseline on one side of a price change reports the price change."""
    with pytest.raises(IncomparableError) as excinfo:
        assert_comparable(
            _fingerprint(), _fingerprint(pricing_basis="litellm-2026-09-01"), under_test=set()
        )
    assert "pricing_basis" in str(excinfo.value)


def test_a_benchmark_set_version_change_makes_two_runs_incomparable() -> None:
    with pytest.raises(IncomparableError) as excinfo:
        assert_comparable(_fingerprint(), _fingerprint(benchmark_set="v2"), under_test=set())
    assert "benchmark_set" in str(excinfo.value)


def test_the_dimension_under_test_is_allowed_to_differ() -> None:
    """That is what an experiment is."""
    assert_comparable(
        _fingerprint(),
        _fingerprint(guideline_source="static"),
        under_test={"guideline_source"},
    )


def test_every_differing_dimension_is_named_not_only_the_first() -> None:
    with pytest.raises(IncomparableError) as excinfo:
        assert_comparable(
            _fingerprint(),
            _fingerprint(benchmark_set="v2", corpus_identity="x", metric_version="2.0.0"),
            under_test=set(),
        )
    message = str(excinfo.value)
    for dimension in ("benchmark_set", "corpus_identity", "metric_version"):
        assert dimension in message


def test_a_metric_version_change_makes_two_runs_incomparable() -> None:
    """Changing how a number is computed silently reinterprets every earlier result."""
    with pytest.raises(IncomparableError):
        assert_comparable(_fingerprint(), _fingerprint(metric_version="2.0.0"), under_test=set())
