"""What guidance a run actually used, read from its own snapshot (T037).

**This function is why slice 007 needs no `guideline_source` column**, so it carries
the weight the column would have. It was untested until a drill went looking for the
test that should have covered it and found nothing — the drill broke the function and
every existing test still passed.

**The distinction it must never blur**: a snapshot with no content hashes is what a
deliberately static run leaves behind *and* what a retrieval run that fell back
leaves behind. This function does not try to tell those apart, because that is not
the question a metric asks. It answers *what was used*, which the record states
exactly, and fallback detection is left to intent-versus-outcome in `eligibility`.
"""

from __future__ import annotations

from careerhq.application.evaluation.readers import STATIC_RUBRIC_SOURCE, guidance_used


def test_a_corpus_snapshot_is_recognised_by_its_citations() -> None:
    snapshot = [
        {"source": "integrity-no-fabrication v1 · rule 1 · 6f35", "content_hash": "6f35"},
        {"source": "universal-verbs v1 · rule 3 · aa11", "content_hash": "aa11"},
    ]
    assert guidance_used(snapshot) == "corpus"


def test_a_static_snapshot_is_recognised_by_the_rubrics_constant_source() -> None:
    """`StaticGuidelines` writes a fixed string; the corpus writes a citation."""
    snapshot = [
        {"source": "CareerHQ house rubric v1"},
        {"source": "CareerHQ house rubric v1 (AI-008)"},
    ]
    assert guidance_used(snapshot) == "static"
    assert snapshot[0]["source"].startswith(STATIC_RUBRIC_SOURCE)


def test_an_empty_or_absent_snapshot_is_none_not_a_guess() -> None:
    assert guidance_used([]) == "none"
    assert guidance_used(None) == "none"


def test_a_snapshot_carrying_both_is_reported_as_mixed_rather_than_resolved() -> None:
    """Nothing produces this today; inventing a winner would hide it if anything did."""
    snapshot = [
        {"source": "CareerHQ house rubric v1"},
        {"source": "universal-verbs v1 · rule 3 · aa11", "content_hash": "aa11"},
    ]
    assert guidance_used(snapshot) == "mixed"


def test_a_snapshot_matching_neither_shape_is_unrecognised_rather_than_assumed() -> None:
    assert guidance_used([{"source": "something nobody writes"}]) == "unrecognised"


def test_the_two_shapes_do_not_overlap_on_the_real_recorded_data() -> None:
    """The exact shapes measured across the ten real runs carrying a snapshot.

    Seven record the rubric constant, three record citations. If either side ever
    starts matching the other, this function silently changes its mind about six
    years of history.
    """
    real_static = {"source": "CareerHQ house rubric v1"}
    real_corpus = {
        "source": "integrity-no-fabrication v1 · rule 1 · 6f35f48fd2e9",
        "content_hash": "6f35f48fd2e9",
    }
    assert guidance_used([real_static]) == "static"
    assert guidance_used([real_corpus]) == "corpus"
    assert guidance_used([real_static]) != guidance_used([real_corpus])
