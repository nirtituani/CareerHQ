"""What the harness refuses to report on, and what it refuses to compare.

**These refusals are the reason any number in this package can be believed.** A
measurement that cannot refuse a mocked arm, an empty corpus or a fallback is a
number with no claim attached; a comparison that averages over a corpus edit is a
lie with a number in front of it.

**Every refusal names what it found.** The house rule elsewhere in this project is
that an error's *detail* goes to the operator and its *type* to the browser —
nothing here is browser-facing, so the detail is the whole point. A refusal saying
only "ineligible" sends the reader to look up something the refusal already knew.

**Every reason is reported, never only the first.** A run wrong in three ways
should not take three runs to discover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class IneligibleRunError(RuntimeError):
    """This run cannot support an agent-quality claim."""


class IncomparableError(RuntimeError):
    """These two results differ in more than the thing under test."""


@dataclass(frozen=True, slots=True)
class RunProvenance:
    """How a run was produced — everything that decides whether it counts.

    Read from the run's own columns (`is_fixture`, `model_config_used`, `status`)
    plus what the guideline source recorded about itself. Nothing here is inferred.
    """

    run_id: str
    used_fixture: bool
    #: **What guidance the run actually used**, read unambiguously from its own
    #: snapshot: `"corpus"` when the guidelines carry citations, `"static"` when
    #: they carry the house rubric's constant source, `"none"` when nothing was
    #: recorded.
    #:
    #: **This replaced "what was configured", and the change is the whole
    #: resolution of the persistence question.** The record does not say which
    #: source a run was *told* to use, and an earlier draft treated that as a gap
    #: needing a schema column. It is not a gap, because it is not the question a
    #: metric asks: a run whose guidance came from the static rubric cannot support
    #: a retrieval claim **whatever it was configured with**. What was *used* is
    #: what the number describes, and `guidelines_used` records that exactly —
    #: measured across all ten real runs that carry a snapshot.
    guidance_used: str
    #: What the caller *intended*, where a caller knows. The benchmark runner always
    #: does and writes it into the result artifact; `None` for a historical run
    #: nobody can ask.
    #:
    #: **Intent plus outcome is what detects a fallback, with no column**: a run
    #: intended `corpus` whose snapshot says `static` fell back, and the two records
    #: disagreeing is the evidence.
    guidance_intended: str | None
    model_config_used: dict[str, str]
    profile_is_benchmark: bool
    status: str


def assert_reportable(
    provenance: RunProvenance,
    *,
    shipping_mix: dict[str, str],
    require_benchmark_profile: bool = True,
    require_corpus_guidance: bool = False,
) -> None:
    """Refuse to report agent-quality metrics for a run that cannot support them.

    `require_benchmark_profile=False` is for reading metrics off **historical user
    runs** — a diagnostic over runs that already happened, not a benchmark claim.
    The FR-013 rule it relaxes is about a benchmark *run*, which creates rows and
    spends money against a profile; reading a number off a run that finished months
    ago is a different act, and conflating the two would either forbid the
    diagnostic or license the dangerous thing. The caller says which it is doing.

    `require_corpus_guidance=True` is for a claim *about retrieval*. It is off by
    default because most metrics — grounding, coverage, adherence — are claims about
    the agent and are just as true of a run advised by the static rubric, which is
    the documented FR-009 fallback and the SC-008 baseline arm, not a defect.
    """
    problems: list[str] = []

    if provenance.status != "succeeded":
        problems.append(
            f"status is {provenance.status!r}, not 'succeeded' — filter on status, never on "
            "the presence of guidelines_used, because a failed run can carry guidance it "
            "never used"
        )

    if provenance.used_fixture:
        problems.append(
            "at least one call came from the fixture gateway; canned content is plumbing "
            "evidence, never agent-quality evidence"
        )

    if provenance.guidance_intended and provenance.guidance_used != provenance.guidance_intended:
        problems.append(
            f"intended {provenance.guidance_intended!r} guidance but the snapshot records "
            f"{provenance.guidance_used!r}; it fell back, so it measures the fallback rather "
            "than the thing it was pointed at"
        )

    if provenance.guidance_used == "none":
        problems.append(
            "the run recorded no guidance, so nothing can be said about what advised it"
        )

    if require_corpus_guidance and provenance.guidance_used != "corpus":
        problems.append(
            f"this run used {provenance.guidance_used!r} guidance; a claim about retrieval "
            "needs a run that actually retrieved"
        )

    for task, model in sorted(shipping_mix.items()):
        actual = provenance.model_config_used.get(task)
        if actual != model:
            problems.append(
                f"{task} ran on {actual!r}, not the shipping {model!r}; evaluating a "
                "configuration that is never deployed describes a system nobody uses"
            )

    if require_benchmark_profile and not provenance.profile_is_benchmark:
        problems.append(
            "the run targeted a profile that is not the synthetic benchmark profile; "
            "a test seeded against the real profile has already merged a fictional CV "
            "into it once"
        )

    if problems:
        joined = "\n  - ".join(problems)
        raise IneligibleRunError(
            f"run {provenance.run_id} cannot support an agent-quality metric:\n  - {joined}"
        )


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Everything that must match before two results may be compared.

    **The load-bearing part of a regression report.** A clean delta across a corpus
    edit, a pricing change or a metric-version change is a lie with a number
    attached — and slice 006 already had to write a clause into SC-008 (006)
    against the pricing version of exactly this.
    """

    benchmark_set: str
    metric_version: str
    finalisation_rules_version: str
    guideline_source: str
    corpus_identity: str
    embedding_model: str
    pricing_basis: str
    model_config: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "benchmark_set": self.benchmark_set,
            "metric_version": self.metric_version,
            "finalisation_rules_version": self.finalisation_rules_version,
            "guideline_source": self.guideline_source,
            "corpus_identity": self.corpus_identity,
            "embedding_model": self.embedding_model,
            "pricing_basis": self.pricing_basis,
            "model_config": dict(self.model_config),
        }


def differences(left: Fingerprint, right: Fingerprint) -> dict[str, tuple[Any, Any]]:
    """Every dimension on which two fingerprints disagree."""
    a, b = left.as_dict(), right.as_dict()
    return {key: (a[key], b[key]) for key in a if a[key] != b[key]}


def assert_comparable(left: Fingerprint, right: Fingerprint, *, under_test: set[str]) -> None:
    """Refuse a comparison that differs in more than the thing being tested.

    `under_test` is what the experiment deliberately changed — `{"guideline_source"}`
    for an SC-008 pair, `set()` for a repeat of an unchanged system. Everything else
    differing is a confound, and it is **named** rather than averaged over.
    """
    unexpected = {k: v for k, v in differences(left, right).items() if k not in under_test}
    if unexpected:
        detail = "\n  - ".join(
            f"{key}: {a!r} vs {b!r}" for key, (a, b) in sorted(unexpected.items())
        )
        raise IncomparableError(
            "these results differ in more than the dimension under test "
            f"({sorted(under_test) or 'nothing'}):\n  - {detail}"
        )


__all__ = [
    "Fingerprint",
    "IncomparableError",
    "IneligibleRunError",
    "RunProvenance",
    "assert_comparable",
    "assert_reportable",
    "differences",
]
