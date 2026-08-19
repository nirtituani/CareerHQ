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
    kind: Literal["must_have", "preferred"]
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

        if (self.verdict == "confirmed") != (self.shortfall is None):
            raise ValueError(
                "shortfall must be set on every verdict except 'confirmed', and only then"
            )
        return self


class MatchJudgement(BaseModel):
    """One scoring run's output, before it becomes a stored analysis."""

    direct: int = Field(ge=0, le=100, description="Same capability, same domain, comparable scale")
    transferable: int = Field(ge=0, le=100, description="Same capability in a different context")
    adjacent: int = Field(ge=0, le=100, description="Secondary responsibility or related tooling")
    impact: int = Field(ge=0, le=100, description="The kind of outcome this posting values")

    verdict: str = Field(description="One sentence a person can act on")

    requirements: list[JudgedRequirement] = Field(default_factory=list)


__all__ = ["JudgedRequirement", "MatchJudgement"]
