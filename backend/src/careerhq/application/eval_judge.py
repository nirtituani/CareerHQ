"""The judge: a model scoring a résumé against a versioned rubric.

**A task name on the existing seam, not a new provider path** (FR-040). It calls
`complete()` exactly as every other model use in this system does, so
`test_the_application_layer_imports_no_provider_sdk` covers it without amendment
and `UsageRecorder` audits it without special-casing.

**`llm_model_eval_judge` is set explicitly to Opus.** `model_for_task` falls back
to `llm_provider_model`, which is *also* Opus — so omitting the entry would be
right by accident and wrong by process, and the fallback is silent.

**What the judge is not shown is the load-bearing part** (FR-026):

| withheld | because |
|---|---|
| which arm produced this | a judge that can tell the arms apart is scoring the label |
| the master profile | it would become a second Reviewer, and its score would then
  correlate with the Reviewer's by construction — destroying the independence that
  makes judged coverage a control on Reviewer-reported coverage |
| the tailoring plan | it would score intent rather than result |
| the Reviewer's findings | it would echo them |
| any other candidate | this contract scores one output at a time |

**A validation failure means the case is unjudged, not that the run stops.** The
run continues and the report says how many cases lack a score — a missing number
is a fact, and inventing one to keep the table rectangular is not.
"""

from __future__ import annotations

import pathlib

from careerhq.application.ports import StructuredCompletion, Usage
from careerhq.domain.schemas.evaluation import JudgeVerdict

#: The task name the gateway resolves a model from. Never a model name here.
JUDGE_TASK = "eval_judge"

#: Which rubric produced a score. **A change is a new version, never an edit** —
#: otherwise every historical score is silently reinterpreted.
RUBRIC_VERSION = "v1"

_RUBRIC_PATH = pathlib.Path(__file__).resolve().parents[3] / "benchmark" / "rubric"


class JudgeUnavailableError(RuntimeError):
    """The judge produced nothing usable for this case.

    Raised so the caller can record the case as **unjudged** and continue. It is
    deliberately not a subclass of anything the runner treats as fatal.
    """


def load_rubric(version: str = RUBRIC_VERSION) -> str:
    path = _RUBRIC_PATH / f"{version}.md"
    if not path.is_file():
        raise JudgeUnavailableError(f"no rubric {version!r} at {path}")
    return path.read_text()


def build_prompt(*, posting: str, resume: str, rubric: str) -> str:
    """The judge's whole input. Everything it may see is assembled here.

    Assembled in one function so that "what the judge is shown" is answerable by
    reading one place, rather than by tracing what a caller happened to pass.
    """
    return (
        "You are evaluating one tailored résumé against one job posting, using the "
        "rubric below. Score only what is in front of you.\n\n"
        "You are not told which system, configuration or version produced this "
        "résumé, and you must not speculate about it or let a guess affect a score.\n\n"
        "=== RUBRIC ===\n"
        f"{rubric}\n\n"
        "=== JOB POSTING ===\n"
        f"{posting}\n\n"
        "=== RÉSUMÉ UNDER EVALUATION ===\n"
        f"{resume}\n\n"
        "Score every rubric dimension, with one specific sentence of justification "
        "each, then give your summary judgement."
    )


async def judge_resume(
    *,
    completion: StructuredCompletion,
    posting: str,
    resume: str,
    rubric_version: str = RUBRIC_VERSION,
) -> tuple[JudgeVerdict, Usage, str]:
    """Score one résumé. Returns the verdict, what it cost, and the rubric version.

    **Usage is returned rather than logged**, like every other call through the
    seam, so the audit record Principle V requires is written in the same
    transaction as the work — and so a judge call that failed is still accounted
    for, because it was still billed.
    """
    rubric = load_rubric(rubric_version)
    prompt = build_prompt(posting=posting, resume=resume, rubric=rubric)
    result = await completion.complete(task=JUDGE_TASK, schema=JudgeVerdict, prompt=prompt)
    return result.value, result.usage, rubric_version


def agreement(judge_scores: dict[str, float], human_scores: dict[str, float]) -> dict[str, object]:
    """How often the judge and a person order the same pair the same way.

    **Pairwise, because that is the question the slice actually asks.** "Did this
    change help?" is a relative judgement, it is the more stable human task, and it
    needs fewer judgements to reach a stable agreement figure than absolute rating
    does (research R6, D8).

    **Ties are excluded from the denominator rather than counted as agreement.**
    A judge that scored everything identically would otherwise agree perfectly with
    any human at all.

    Returns `agreed=None` when there is no comparable pair — never `0.0`, which
    would read as total disagreement where the truth is that there is nothing to
    compare.
    """
    shared = sorted(set(judge_scores) & set(human_scores))
    concordant = 0
    comparable = 0
    for i, left in enumerate(shared):
        for right in shared[i + 1 :]:
            jd = judge_scores[left] - judge_scores[right]
            hd = human_scores[left] - human_scores[right]
            if jd == 0 or hd == 0:
                continue
            comparable += 1
            if (jd > 0) == (hd > 0):
                concordant += 1

    return {
        "items": len(shared),
        "comparable_pairs": comparable,
        "concordant_pairs": concordant,
        "agreed": (concordant / comparable) if comparable else None,
        "reason": (
            ""
            if comparable
            else "no comparable pair — every pair tied on one side or the other, so "
            "there is nothing to agree or disagree about"
        ),
    }


__all__ = [
    "JUDGE_TASK",
    "RUBRIC_VERSION",
    "JudgeUnavailableError",
    "agreement",
    "build_prompt",
    "judge_resume",
    "load_rubric",
]
