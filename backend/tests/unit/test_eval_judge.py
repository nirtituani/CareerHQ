"""The judge, its blindness, and what makes its scores evidence (T027-T031)."""

from __future__ import annotations

import pytest

from careerhq.application.eval_judge import (
    JUDGE_TASK,
    RUBRIC_VERSION,
    agreement,
    build_prompt,
    load_rubric,
)
from careerhq.config import get_settings
from careerhq.domain.schemas.evaluation import JudgeVerdict


def test_the_judge_has_its_own_configured_model_rather_than_falling_back() -> None:
    """Omitting it would be right by accident and wrong by process."""
    settings = get_settings()
    assert settings.model_for_task(JUDGE_TASK) == "anthropic/claude-opus-5"
    assert hasattr(settings, f"llm_model_{JUDGE_TASK}"), (
        "the judge must have an explicit entry; model_for_task falls back silently"
    )


def test_the_rubric_loads_and_is_versioned() -> None:
    rubric = load_rubric(RUBRIC_VERSION)
    assert "Relevance to the posting" in rubric
    assert "Coverage of stated requirements" in rubric


def test_the_rubric_never_tells_the_model_how_to_distribute_its_answers() -> None:
    """ "Most real profiles are mostly `partial`…" made a model comply, in slice 004."""
    rubric = load_rubric().lower()
    for phrase in ("most résumés", "most resumes", "typically score", "usually score"):
        assert phrase not in rubric, f"the rubric anchors the distribution: {phrase!r}"
    assert "says nothing about how often each" in rubric


def test_the_prompt_carries_the_posting_the_resume_and_the_rubric() -> None:
    prompt = build_prompt(posting="POSTING-MARKER", resume="RESUME-MARKER", rubric="RUBRIC-MARKER")
    assert "POSTING-MARKER" in prompt
    assert "RESUME-MARKER" in prompt
    assert "RUBRIC-MARKER" in prompt


def test_the_prompt_tells_the_judge_it_does_not_know_which_arm_produced_this() -> None:
    prompt = build_prompt(posting="p", resume="r", rubric="x").lower()
    assert "not told which system" in prompt
    assert "must not speculate" in prompt


def test_the_schema_makes_every_rule_visible_in_the_json_schema() -> None:
    """A `model_validator(mode="after")` does not serialise; a description does."""
    schema = JudgeVerdict.model_json_schema()
    assert schema["properties"]["dimensions"]["minItems"] == 5
    assert "NOT" in schema["properties"]["overall"]["description"]
    dimension = schema["$defs"]["DimensionScore"]["properties"]
    assert dimension["score"]["maximum"] == 5
    assert "distribution" in dimension["score"]["description"]


def test_a_verdict_that_scores_fewer_than_five_dimensions_is_rejected() -> None:
    with pytest.raises(ValueError):
        JudgeVerdict(
            dimensions=[],
            overall=3,
            strongest="something specific",
            weakest="something else specific",
        )


# -- Agreement (FR-025) ------------------------------------------------------


def test_perfect_ordering_agreement_is_one() -> None:
    result = agreement({"a": 5, "b": 3, "c": 1}, {"a": 5, "b": 3, "c": 1})
    assert result["agreed"] == 1.0
    assert result["comparable_pairs"] == 3


def test_inverted_ordering_agreement_is_zero() -> None:
    result = agreement({"a": 5, "b": 3, "c": 1}, {"a": 1, "b": 3, "c": 5})
    assert result["agreed"] == 0.0


def test_a_judge_that_scores_everything_the_same_agrees_with_nobody() -> None:
    """Ties are excluded, or a constant judge would agree perfectly with anyone."""
    result = agreement({"a": 3, "b": 3, "c": 3}, {"a": 5, "b": 3, "c": 1})
    assert result["agreed"] is None
    assert result["comparable_pairs"] == 0
    assert "nothing to agree" in result["reason"]


def test_agreement_over_no_shared_items_is_not_measured() -> None:
    assert agreement({"a": 5}, {"b": 5})["agreed"] is None


def test_agreement_reports_its_sample_size() -> None:
    result = agreement({"a": 5, "b": 3}, {"a": 5, "b": 3})
    assert result["items"] == 2
    assert result["comparable_pairs"] == 1


# -- T029: the judge is audited like every other model call ------------------


def _verdict_payload() -> dict[str, object]:
    return {
        "dimensions": [
            {
                "dimension": name,
                "score": 3,
                "justification": "A specific sentence naming the thing that decided it.",
            }
            for name in (
                "relevance",
                "coverage",
                "specificity",
                "plausibility",
                "presentation",
            )
        ],
        "overall": 3,
        "strongest": "The settlement ledger bullet gives a concrete before and after.",
        "weakest": "Kubernetes is claimed as a skill but no bullet shows it in use.",
    }


@pytest.mark.asyncio
async def test_the_judge_returns_its_usage_rather_than_logging_it() -> None:
    """Principle V: usage is returned so the audit lands in the caller's transaction."""
    from decimal import Decimal

    from careerhq.application.eval_judge import judge_resume
    from tests.support.scripted_seam import ScriptedSeam

    seam = ScriptedSeam(script={JUDGE_TASK: [_verdict_payload()]}, cost_per_call=Decimal("0.07"))
    verdict, usage, rubric_version = await judge_resume(
        completion=seam, posting="a posting", resume="a resume"
    )

    assert verdict.overall == 3
    assert usage.cost == Decimal("0.07")
    assert usage.input_tokens > 0
    assert usage.model == f"scripted/{JUDGE_TASK}"
    assert rubric_version == RUBRIC_VERSION


@pytest.mark.asyncio
async def test_the_judge_calls_the_seam_by_task_name_never_by_model() -> None:
    from careerhq.application.eval_judge import judge_resume
    from tests.support.scripted_seam import ScriptedSeam

    seam = ScriptedSeam(script={JUDGE_TASK: [_verdict_payload()]})
    await judge_resume(completion=seam, posting="p", resume="r")

    assert seam.tasks_called == [JUDGE_TASK]
    assert seam.times_called(JUDGE_TASK) == 1


@pytest.mark.asyncio
async def test_the_judge_sees_the_posting_and_the_resume_and_not_the_profile() -> None:
    """Read out of the prompt the seam actually received, not out of the arguments.

    A double fed by someone who read the code proves the plumbing works when values
    are supplied. Reading it back out of the prompt is what proves a model *could*
    see it — and, here, that it could not see what it must not.
    """
    from careerhq.application.eval_judge import judge_resume
    from tests.support.scripted_seam import ScriptedSeam

    seam = ScriptedSeam(script={JUDGE_TASK: [_verdict_payload()]})
    await judge_resume(completion=seam, posting="POSTING-MARKER", resume="RESUME-MARKER")

    prompt = seam.calls[0].prompt
    assert "POSTING-MARKER" in prompt
    assert "RESUME-MARKER" in prompt
    assert "PROFILE-MARKER" not in prompt
    assert "tailoring plan" not in prompt.lower()


@pytest.mark.asyncio
async def test_a_judge_whose_output_fails_validation_raises_rather_than_scoring() -> None:
    """The case is unjudged and the run continues; a number is never invented."""
    from careerhq.application.eval_judge import judge_resume
    from tests.support.scripted_seam import ScriptedSeam

    seam = ScriptedSeam(script={JUDGE_TASK: [{"overall": 9, "dimensions": []}]})
    with pytest.raises(ValueError):
        await judge_resume(completion=seam, posting="p", resume="r")
