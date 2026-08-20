"""What one match completion returns.

Specified by `specs/004-match-analysis/contracts/match-analysis.md`. Named
`MatchJudgement` rather than `MatchAnalysis` because the ORM row is already
called that and `analyze_match.py` imports both — the same reason the CV
extraction schemas carry an `Extracted` prefix. The design's own phrase for this
is "one structured judgement", which is what the model produces; the analysis is
what gets stored.

**The model does not return a score.** It rates four dimensions and
`match_criteria.overall_score` combines them. A model asked for both the parts
and the total will sometimes return a total that does not follow from its parts,
and the total is the one a person acts on.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

#: Which verdicts assert something about the person and therefore need the
#: profile text that supports it. `gap` is here deliberately: *you fall short of
#: this* is as much a claim as *you have this*.
_GROUNDED = frozenset({"confirmed", "partial", "transferable", "gap"})


class JudgedRequirement(BaseModel):
    """One requirement, and how the profile answers it."""

    #: Worded as the posting worded it. A paraphrase makes the coverage count
    #: incomparable between runs and slice 007's frequency counting meaningless.
    text: str = Field(description="The requirement, worded as the posting worded it")
    #: What the posting **said**. Preserved verbatim, and deliberately not what
    #: the band rule reasons over — see `importance`.
    kind: Literal["must_have", "preferred"]

    #: What the model **judged** this requirement is worth to this recruiter for
    #: this role, 0-100.
    #:
    #: Separate from `kind` because a posting's "must have" heading is routinely
    #: a wishlist, and because the recruiter's real priorities show in how the
    #: posting is written — what comes first, what is repeated, what the role is
    #: actually about — rather than in which heading a line sits under. The same
    #: split as `status` and `normalized_status`.
    importance: int = Field(
        ge=0, le=100, description="How much this requirement matters for this role"
    )

    verdict: Literal["confirmed", "partial", "transferable", "gap", "unverified"]
    #: Why it is not met, which decides what to do about it: rephrase what is
    #: already there, supply the proof, or acknowledge the gap.
    shortfall: Literal["wording", "evidence", "capability"] | None = None
    #: Quoted from the profile — supporting text for a positive verdict, the
    #: text showing the shortfall for a `gap`.
    evidence: str | None = None

    @model_validator(mode="after")
    def _grounded(self) -> Self:
        """AI-008, structurally.

        Every verdict except `unverified` must quote the profile. A model that
        cannot quote anything does not get to say the person falls short — the
        honest verdict is then `unverified`, the sole evidence-free one because
        it is the only one asserting nothing.

        Whitespace does not count. The database CHECK can only test `IS NULL`,
        so an empty string satisfies it; this is the layer that closes that,
        which is why both layers exist rather than one.
        """
        has_evidence = bool(self.evidence and self.evidence.strip())

        if self.verdict in _GROUNDED and not has_evidence:
            raise ValueError(
                f"a {self.verdict!r} verdict must quote evidence from the profile; "
                "if nothing can be quoted the honest verdict is 'unverified'"
            )
        if self.verdict == "unverified" and has_evidence:
            raise ValueError("an 'unverified' verdict must not carry evidence — it asserts nothing")

        # A shortfall is only meaningful where the model has actually read
        # something. `confirmed` has nothing to explain; `unverified` has
        # nothing to explain it *with*.
        #
        # Requiring one on `unverified` was the original rule and it was wrong —
        # a real completion failed on exactly it. The profile says nothing, so
        # choosing between `wording`, `evidence` and `capability` means guessing
        # why it is silent: no skill, different words, or simply not written
        # down. Nothing in the profile answers that, and demanding an answer
        # reintroduces the invented absence this taxonomy exists to prevent.
        needs_shortfall = self.verdict in {"partial", "transferable", "gap"}
        if needs_shortfall and self.shortfall is None:
            raise ValueError(f"a {self.verdict!r} verdict must say what kind of shortfall it is")
        if not needs_shortfall and self.shortfall is not None:
            raise ValueError(
                f"a {self.verdict!r} verdict carries no shortfall — there is nothing to classify"
            )
        return self


class MatchJudgement(BaseModel):
    """One scoring run's output, before it becomes a stored analysis."""

    # **No dimension ratings.** v2 asked for four, computed the score from them,
    # and let the per-requirement verdicts feed nothing but the band cap — two
    # independent judgements about the same thing that nothing reconciled. A
    # real job came back with every requirement addressed and a score of 48.
    #
    # v3 earns the score from the requirements instead, so the total explains
    # the list rather than arguing with it (research.md R11).

    verdict: str = Field(description="One sentence a person can act on")

    requirements: list[JudgedRequirement] = Field(default_factory=list)


__all__ = ["JudgedRequirement", "MatchJudgement"]
