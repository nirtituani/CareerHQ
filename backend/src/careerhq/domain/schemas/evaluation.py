"""What the judge returns — validated before use (Constitution VI).

**Every rule this schema enforces is visible in the JSON Schema.** A
`model_validator(mode="after")` does **not** serialise, and the schema is the whole
contract the gateway sends; a conditional requirement has to live in
`Field(description=...)`, which does. This project shipped the other way round
once, and the model could not comply with a rule it was never shown.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DimensionScore(BaseModel):
    """One rubric dimension, scored, with the reason it was scored that way."""

    dimension: str = Field(
        description=(
            "One of: relevance, coverage, specificity, plausibility, presentation. "
            "Use exactly these names."
        )
    )
    score: int = Field(
        ge=1,
        le=5,
        description=(
            "1 to 5, as the rubric defines each level. 3 is the honest middle, not a "
            "failure. Do not aim for any particular distribution across dimensions or "
            "across résumés."
        ),
    )
    justification: str = Field(
        min_length=20,
        description=(
            "ONE sentence naming the specific thing in this résumé that decided the "
            "score. 'Good coverage' is not a justification; 'Kubernetes is listed as a "
            "skill but no bullet shows it in use, and the posting calls it essential' "
            "is. Quote or point at the actual text."
        ),
    )


class JudgeVerdict(BaseModel):
    """A rubric score for one tailored résumé.

    **`overall` is not an average and must not be computed as one.** It is the
    judge's summary judgement, kept beside the parts rather than derived from them,
    for the reason `MatchAnalysis` keeps its four dimensions beside its total: a
    bare total implies a measurement nobody can audit, and an average would let a
    strong presentation score offset a fabrication risk.
    """

    dimensions: list[DimensionScore] = Field(
        min_length=5,
        max_length=5,
        description=(
            "Exactly five entries, one per rubric dimension: relevance, coverage, "
            "specificity, plausibility, presentation."
        ),
    )
    overall: int = Field(
        ge=1,
        le=5,
        description=(
            "Your summary judgement of this résumé against this posting. This is NOT "
            "an average of the dimensions — a strong presentation must not offset a "
            "plausibility concern."
        ),
    )
    strongest: str = Field(
        min_length=10, description="The single most effective thing this résumé does."
    )
    weakest: str = Field(
        min_length=10,
        description=(
            "The single thing most worth fixing. If the résumé makes a claim you would "
            "want to verify before believing, name that here."
        ),
    )


__all__ = ["DimensionScore", "JudgeVerdict"]
