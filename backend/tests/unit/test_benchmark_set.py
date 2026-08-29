"""The benchmark set: fixed, versioned, reproducible, and not artificially easy.

**FR-001 to FR-005d, and T016.** The set is the fixed input that makes two runs
comparable. Two properties matter more than any other and each has a test here:

* **It is reproducible from version-controlled files** — never from rows somebody
  seeded by hand, which is what FR-005 exists to rule out.
* **It is hard enough to measure anything.** A synthetic posting is cleaner than a
  real one, and both retrieval quality and requirement coverage would be flattered
  by that with nothing in the harness noticing (research R8).
"""

from __future__ import annotations

import pathlib

import pytest

from careerhq.application.evaluation.benchmark_set import (
    BenchmarkSetError,
    difficulty_report,
    load_benchmark_set,
)

ROOT = pathlib.Path(__file__).resolve().parents[2] / "benchmark"


def test_the_committed_set_loads() -> None:
    benchmark = load_benchmark_set("v1", root=ROOT)
    assert benchmark.version == "v1"
    assert len(benchmark.cases) >= 12, f"D3 approved 12 cases; the set holds {len(benchmark.cases)}"


def test_the_case_count_is_read_from_the_set_not_hard_coded() -> None:
    """A runner that assumes 12 would project the wrong cost for any other set."""
    benchmark = load_benchmark_set("v1", root=ROOT)
    assert benchmark.case_count == len(benchmark.cases)


def test_every_case_names_a_profile_state_that_exists() -> None:
    benchmark = load_benchmark_set("v1", root=ROOT)
    for case in benchmark.cases:
        assert case.profile_state in benchmark.profiles, (
            f"{case.case_id} pairs with an unknown profile state {case.profile_state!r}"
        )


def test_case_ids_are_unique() -> None:
    benchmark = load_benchmark_set("v1", root=ROOT)
    ids = [c.case_id for c in benchmark.cases]
    assert len(ids) == len(set(ids))


def test_loading_an_unknown_version_refuses_rather_than_returning_nothing() -> None:
    """An empty set is the shape of a benchmark that measures nothing."""
    with pytest.raises(BenchmarkSetError):
        load_benchmark_set("v-does-not-exist", root=ROOT)


# -- FR-005b: the set must not be artificially easy ---------------------------


def test_the_set_spans_at_least_three_disciplines() -> None:
    report = difficulty_report(load_benchmark_set("v1", root=ROOT))
    assert report["disciplines"] >= 3, (
        f"FR-003 requires three; the set spans {report['disciplines']}"
    )


def test_the_set_varies_seniority() -> None:
    report = difficulty_report(load_benchmark_set("v1", root=ROOT))
    assert report["seniorities"] >= 2


def test_the_set_varies_the_profile_and_does_not_reuse_one() -> None:
    """Reusing one profile makes coverage a property of that profile."""
    report = difficulty_report(load_benchmark_set("v1", root=ROOT))
    assert report["profile_states"] >= 3, (
        f"one profile reused across every case measures the profile, not the agent; "
        f"found {report['profile_states']}"
    )


def test_at_least_one_case_has_a_must_have_the_profile_does_not_cover() -> None:
    """A benchmark the agent cannot fail measures nothing.

    It is also the only place AI-008 can be tested: the temptation to fabricate
    exists exactly where there is a gap.
    """
    report = difficulty_report(load_benchmark_set("v1", root=ROOT))
    assert report["cases_with_expected_gaps"] >= 1


def test_the_set_contains_postings_that_are_genuinely_unlike_each_other() -> None:
    """Twelve backend roles would never exercise retrieval.

    T013 (006) measured 13 rules for a backend posting and 12 for a nursing one
    with **1 in common**; a set that cannot produce that spread cannot tell a
    retrieval regression from noise.

    **The assertion is on the minimum, not the maximum, and the first draft had it
    backwards.** Requiring every pair to be dissimilar would forbid two backend
    roles at different seniorities — which is exactly the pair that exercises
    seniority guidance and which any real benchmark should contain. The property
    that matters is that *genuinely different* postings exist in the set, and that
    is a floor on the least similar pair plus a spread wide enough to distinguish
    the two situations.
    """
    report = difficulty_report(load_benchmark_set("v1", root=ROOT))
    assert report["min_pairwise_vocabulary_overlap"] < 0.15, (
        "no two postings in the set are genuinely unlike each other; retrieval has "
        f"nothing to get wrong (least similar pair {report['min_pairwise_vocabulary_overlap']}, "
        f"{report['least_similar_pair']})"
    )
    spread = report["max_pairwise_vocabulary_overlap"] - report["min_pairwise_vocabulary_overlap"]
    assert spread > 0.15, (
        f"every pair is about equally similar ({spread=}); the set has one register, "
        "so a guidance difference between cases cannot be attributed to the posting"
    )


def test_every_case_carries_a_posting_with_real_content() -> None:
    benchmark = load_benchmark_set("v1", root=ROOT)
    for case in benchmark.cases:
        assert len(case.posting_text) >= 400, (
            f"{case.case_id}'s posting is {len(case.posting_text)} characters; a stub "
            "posting produces a stub analysis and flatters every downstream metric"
        )
        assert case.requirements, f"{case.case_id} states no requirements to score against"


def test_no_committed_case_carries_a_real_email_address_or_phone_number() -> None:
    """FR-039. This repository is public and has had two near-misses."""
    benchmark = load_benchmark_set("v1", root=ROOT)
    blob = "\n".join(
        [c.posting_text for c in benchmark.cases] + [repr(p) for p in benchmark.profiles.values()]
    )
    import re

    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", blob))
    assert all(e.endswith("example.com") for e in emails), (
        f"non-example.com address in a committed benchmark file: {emails}"
    )
    assert not re.search(r"\+972[\d\- ]{7,}", blob), "an Israeli phone number is committed"
