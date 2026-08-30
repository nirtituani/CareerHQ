"""What the company-research completions return (slice 008, Layer 1).

Specified by `specs/008-company-research/spec.md`. Named with schema nouns rather
than the ORM's, for the reason `MatchJudgement` and `TailoringPlan` are: the use
case will import both, and two `CompanyResearch`es would make every call site
ambiguous.

**Three tiers, three different evidence obligations.** A reader can only weigh
research if the output distinguishes what a source *said* from what we *read
into* it from what we *guessed beyond* it:

* `fact` — a source states it. Must quote that source.
* `interpretation` — a reading of stated facts. Must name the facts it rests on.
* `inference` — reasoned beyond any source. May cite nothing, but is labelled
  and is never rendered as a fact.

This is the shape slice 004 arrived at with its five verdicts, where `unverified`
is the only evidence-free one "because it is the only one that asserts nothing".
The tiers differ in what they assert, so they differ in what they owe.

**The obligations are written into `Field(description=...)`, not only into the
validator, and that is deliberate.** `model_validator(mode="after")` does **not**
serialise, and the serialised JSON Schema is the entire contract
`LiteLLMGateway` sends the model. Slice 005 spent two paid runs learning that a
rule living only in a validator is a rule the model is never shown. The
validator still exists — it is what makes the rule true rather than merely
requested — but the description is what makes it followable.

**Layer 1 is role-independent (FR-021), and this file is where that is
guaranteed.** There is no field through which a job title, description or
requirement could reach it, so a Layer 1 snapshot produced for one job is valid
for another at the same employer. That reuse is not a convention to remember; it
is a shape the schema cannot express otherwise.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

#: The three kinds of content, in descending order of what a source backs.
ClaimTier = Literal["fact", "interpretation", "inference"]


class Evidence(BaseModel):
    """One source, and the passage in it that carries the claim.

    The excerpt is not decoration. `spec.md` FR-032 requires every stored excerpt
    to be checked **verbatim** against the document CareerHQ retrieved — a
    deterministic string test, possible only because the application does its own
    fetching and therefore holds the document. It is what defeats citation
    laundering: an invented claim paired with a real URL cannot survive it.
    """

    source_id: str = Field(
        description="Identifier of the source, exactly as given to you in the sources list"
    )
    excerpt: str = Field(
        min_length=1,
        description=(
            "The passage from that source supporting this claim, copied WORD FOR WORD. "
            "It is checked against the retrieved page and the claim is rejected if it "
            "does not appear there verbatim. Do not paraphrase, summarise or reflow it."
        ),
    )


class Claim(BaseModel):
    """One statement in a research brief, with the evidence its tier requires."""

    id: str = Field(description="A short identifier unique within this brief, e.g. 'c1'")
    text: str = Field(min_length=1, description="The statement itself, in one sentence")
    tier: ClaimTier = Field(
        description=(
            "'fact' if a source states this and you can quote it; "
            "'interpretation' if you are reading something out of stated facts; "
            "'inference' if you are reasoning beyond what any source says."
        )
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description=(
            "Sources backing this claim. A 'fact' MUST have at least one entry. "
            "Leave empty for an 'inference'."
        ),
    )
    rests_on: list[str] = Field(
        default_factory=list,
        description=(
            "Ids of the facts in this brief that this claim is read out of. An "
            "'interpretation' MUST name at least one. Leave empty for a 'fact' or an "
            "'inference'."
        ),
    )

    @model_validator(mode="after")
    def _tier_obligations(self) -> Self:
        """FR-029, enforced. The descriptions above state the same rules so the
        model can follow them; this is what makes them true."""
        if self.tier == "fact" and not self.evidence:
            raise ValueError(
                "a 'fact' must carry at least one evidence entry quoting its source; "
                "use 'inference' for a claim no source states"
            )
        if self.tier == "interpretation" and not self.rests_on:
            raise ValueError(
                "an 'interpretation' must name the facts it rests on in rests_on; "
                "an interpretation resting on nothing is an inference"
            )
        return self


class ResearchSection(BaseModel):
    """One heading of the brief. Present even when it holds nothing.

    An empty section must say **why** it is empty. Silence and absence are
    different things, and conflating them is the mistake slice 004 removed when
    it made `unverified` an explicit verdict: a section that simply vanishes
    reads as "not applicable" when it may mean "we looked and found nothing".
    """

    claims: list[Claim] = Field(default_factory=list, description="The claims under this heading")
    empty_reason: str | None = Field(
        default=None,
        description=(
            "REQUIRED when claims is empty: why nothing was found — for example that no "
            "reliable public source covered it. Omit when there are claims."
        ),
    )

    @model_validator(mode="after")
    def _empty_sections_explain_themselves(self) -> Self:
        if not self.claims and not self.empty_reason:
            raise ValueError(
                "an empty section must set empty_reason; an unexplained empty section "
                "cannot be told apart from one that was never attempted"
            )
        return self


class CompanyResearch(BaseModel):
    """Layer 1 — the general company understanding.

    **Role-independent by construction.** Every field below is about the
    employer, and none can carry a job. That is what lets one snapshot serve
    every application to that company (FR-021) and what makes the reuse in
    `plan.md` §6 sound rather than merely convenient.

    The sections are **named fields rather than a list**, so a missing section is
    unrepresentable. `docs/01` FR-020's "may include" is unimplementable as
    written: a schema has to know what is required, and the answer here is all of
    them — empty where the research found nothing, and saying so.
    """

    what_the_company_does: ResearchSection = Field(
        description="What the company actually does. The primary output of this layer."
    )
    products_and_services: ResearchSection = Field(
        description="What it builds and sells, and to whom it sells it"
    )
    market_and_customers: ResearchSection = Field(
        description="Its market, its customers, and the business context it operates in"
    )
    practical_facts: ResearchSection = Field(
        description=(
            "SECONDARY: locations, working arrangements, size, benefits where publicly "
            "stated. Useful context, but never at the expense of the sections above."
        )
    )
    interview_preparation: ResearchSection = Field(
        description=(
            "What to know for a general or HR conversation about this company, and "
            "questions worth asking. Not technical — that is the role-specific layer."
        )
    )


class RoleQueryPlan(BaseModel):
    """The searches Layer 2 will run (pipeline step [4]).

    **A model call, and the one to challenge first** (OQ-I). Layer 1's queries
    are a template because they depend only on company identity; these depend on
    a role and its requirements, which is world knowledge a template cannot
    supply — and Brave's index is keyword-oriented, so the terms chosen decide
    what comes back. The deterministic alternative is not rejected, only
    unmeasured; measuring it needs a working search adapter.

    Bounded in the schema **and** re-checked by the caller, because a `max_items`
    a model overshoots is a validation error rather than a silent overrun — the
    opposite of the Layer 1 template's failure mode, which was to truncate
    quietly.
    """

    queries: list[str] = Field(
        min_length=1,
        max_length=8,
        description=(
            "Search queries for a KEYWORD engine, aimed at material showing how this "
            "company builds software, chosen for this role. Quote the company name."
        ),
    )


class RoleFinding(BaseModel):
    """One heading of a Layer 2 brief, and the claims under it.

    **The heading is chosen by the model, and that is the layer's entire
    structural difference from Layer 1** (FR-022). Layer 1's five sections are
    named fields because every company brief answers the same five questions.
    Layer 2's do not: what is worth knowing about a backend role at an
    infrastructure company is a different set of headings from a design role at
    the same employer, and fixing them would shape every brief like whichever
    role was imagined first.

    The emptiness rule is `ResearchSection`'s, unchanged and for the same
    reason — a heading with nothing under it reads as "not applicable" when it
    may mean "we looked and found nothing".
    """

    heading: str = Field(
        min_length=1,
        description=(
            "A short heading for this group of claims, chosen to fit THIS role at THIS "
            "company — for example 'Architecture and scale', 'Testing culture', "
            "'The team you would join'. Do not use a fixed set: pick the headings the "
            "evidence and the role actually justify."
        ),
    )
    claims: list[Claim] = Field(default_factory=list, description="The claims under this heading")
    empty_reason: str | None = Field(
        default=None,
        description=(
            "REQUIRED when claims is empty: what you looked for and did not find. "
            "Omit when there are claims."
        ),
    )

    @model_validator(mode="after")
    def _empty_findings_explain_themselves(self) -> Self:
        if not self.claims and not self.empty_reason:
            raise ValueError(
                "a finding with no claims must set empty_reason; an unexplained empty "
                "heading cannot be told apart from one that was never attempted"
            )
        return self


class RoleResearch(BaseModel):
    """Layer 2 — the role-specific perspective on one application.

    **Driven by the target role** — the job title, the description and the
    extracted requirements — and by nothing about the applicant. FR-022 is
    explicit that Layer 2 "does not read the user's own profile or history", so
    no field here can carry one. Whether *this person* fits *this job* is slice
    004's question, and answering it here would quietly duplicate it against
    worse evidence.

    **`findings` is a variable list** where Layer 1 has fixed fields. See
    `RoleFinding`.

    **Lineage lives on the stored row, not here.** FR-023 requires Layer 2 to
    record which Layer 1 snapshot it rests on and how old that was; that is
    `RoleResearchSnapshot.company_research_snapshot_id`, a fact about the run
    rather than something the model produces. Asking the model for it would
    invite it to invent one.
    """

    findings: list[RoleFinding] = Field(
        default_factory=list,
        description=(
            "The role-specific findings, under headings you choose. Group by what a "
            "candidate for THIS role needs to know."
        ),
    )
    no_findings_reason: str | None = Field(
        default=None,
        description=(
            "REQUIRED when findings is empty: why no role-specific finding could be "
            "supported. Producing nothing is a legitimate outcome when the sources do "
            "not cover this role's technical context — inventing plausible detail is not."
        ),
    )
    interview_preparation: ResearchSection = Field(
        description=(
            "FOR A TECHNICAL CONVERSATION with a team lead or hiring manager: the "
            "technical topics likely to come up for this role at this company, and "
            "questions worth asking. This is the role-level counterpart to the general "
            "interview notes in the company profile, and does not repeat them."
        )
    )

    @model_validator(mode="after")
    def _an_empty_brief_explains_itself(self) -> Self:
        """The list-level counterpart to `RoleFinding`'s rule.

        FR-024 forbids filling headings with plausible architecture, so finding
        nothing is a legitimate outcome — but an empty list with no reason
        cannot be told apart from a run that never happened.
        """
        if not self.findings and not self.no_findings_reason:
            raise ValueError(
                "a brief with no findings must set no_findings_reason; producing nothing "
                "is allowed, producing nothing silently is not"
            )
        return self


__all__ = [
    "Claim",
    "ClaimTier",
    "CompanyResearch",
    "Evidence",
    "ResearchSection",
    "RoleFinding",
    "RoleQueryPlan",
    "RoleResearch",
]
