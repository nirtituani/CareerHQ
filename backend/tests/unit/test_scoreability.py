"""Whether a job has posting content the analysis will actually read.

**The defect this exists to close.** `create_pending_analysis` tested
`application.requirements`; `run_analysis` sent `application.job_description`.
The guard checked one field and the prompt read another, so a job with
requirements and no description passed the gate, was sent an empty posting, and
came back `0/100 · low_probability` with the model's own verdict reading "No job
posting content was provided". It cost $0.007266 and rendered as a judgement
about the person rather than about missing data.

The user had supplied the content. They pasted it into the requirements box, and
nothing sent it. So the fix is not a stricter gate — a stricter gate would still
refuse that job, and still be wrong.

One function decides, and both Match and Tailor ask it.
"""

from __future__ import annotations

from typing import Any

from careerhq.application.scoreability import scoreable_posting


class _App:
    """Only the two fields that decide this."""

    def __init__(self, description: Any = None, requirements: Any = None) -> None:
        self.job_description = description
        self.requirements = requirements


def test_a_description_is_the_posting() -> None:
    assert scoreable_posting(_App("Build payment services at scale.", [])) == (
        "Build payment services at scale."
    )


def test_the_description_wins_when_both_are_present() -> None:
    """Preserved deliberately. The description is the whole posting; the
    requirements are a list extracted *from* it, so preferring the list would
    hand the model less than it had."""
    posting = scoreable_posting(_App("The whole posting.", ["5+ years backend"]))

    assert posting == "The whole posting."
    assert "5+ years" not in posting


def test_requirements_stand_in_when_there_is_no_description() -> None:
    """The Voyantis case. The content exists; nothing was reading it."""
    posting = scoreable_posting(
        _App(None, ["3+ years building production cloud systems", "Strong Python"])
    )

    assert posting is not None
    assert "3+ years building production cloud systems" in posting
    assert "Strong Python" in posting


def test_the_composed_posting_invents_nothing() -> None:
    """It may reformat what is stored. It may not add to it.

    Every line of the result must trace to a stored requirement — no invented
    heading, no summary sentence, no 'the role requires'.
    """
    stored = ["3+ years building production cloud systems", "Strong Python"]
    posting = scoreable_posting(_App(None, stored))
    assert posting is not None

    for line in posting.splitlines():
        stripped = line.lstrip("-• ").strip()
        assert stripped in stored, f"composed a line that is not stored: {line!r}"


def test_nothing_usable_is_nothing() -> None:
    assert scoreable_posting(_App(None, [])) is None
    assert scoreable_posting(_App("", [])) is None
    assert scoreable_posting(_App("   \n  ", [])) is None
    assert scoreable_posting(_App(None, ["", "   "])) is None


def test_whitespace_in_a_description_falls_through_to_the_requirements() -> None:
    """A description of spaces is not a description. Returning it would send an
    empty posting — the original bug, wearing a non-null value."""
    posting = scoreable_posting(_App("   ", ["Strong Python"]))

    assert posting is not None
    assert "Strong Python" in posting


def test_blank_requirement_lines_are_dropped_not_rendered() -> None:
    posting = scoreable_posting(_App(None, ["Strong Python", "", "  ", "AWS"]))

    assert posting is not None
    assert [line for line in posting.splitlines() if not line.strip()] == []


def test_a_legacy_row_stays_unscoreable_even_though_it_has_a_description() -> None:
    """`requirements is None` marks a row written before slice 004, whose
    `job_description` holds a joined requirements list rather than a posting
    (research R1). Scoring it compares the profile against that list while the
    prompt claims to be reading a whole posting, and the resulting number looks
    entirely normal. That refusal predates this change and survives it.
    """
    assert scoreable_posting(_App("5+ years backend\nKubernetes\nPython", None)) is None
