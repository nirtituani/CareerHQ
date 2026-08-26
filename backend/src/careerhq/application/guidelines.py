"""Where resume-writing guidance comes from.

**This port is the 005/006 boundary, and it exists so that boundary is
structural rather than an intention someone remembers.**

Slice 006 upgrades this agent's knowledge source: guidance stops being a static
rubric and starts being retrieval over a guideline library. It is *not* a
redesign, and there is no "Tailoring Agent v2" — the workflow, the nodes, their
responsibilities, the state and the finalisation rules all stay exactly as slice
005 built them. The only change is which implementation of `GuidelineSource` is
wired in.

Nothing in the graph refers to where guidance came from, so nothing in the graph
changes when the answer does. That is the whole design, and it is the same move
`ports.py` made for the provider seam, for the reason its docstring gives:
*defined with one caller rather than discovered with five*.

**What this signature deliberately does not have**: `top_k`, similarity scores,
embedding parameters. Those are retrieval's vocabulary. Putting them here in
advance would be designing 006 inside 005 — the opposite error, and equally
costly, because the static implementation would have to pretend to answer
questions it has no notion of. The port asks a question; how an implementation
answers it is its own business.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Guideline:
    """One piece of resume-writing advice, and where it came from.

    **`source` is populated from this first implementation**, even though it is
    a constant and looks redundant. `docs/08` requires retrieval to preserve
    citations, so slice 006 needs the field — and adding it then would change
    what the prompt builders consume, which is precisely the compounding
    node-input change the 005/006 boundary exists to prevent. A static rubric
    has a provenance too, so recording it is accurate rather than speculative.

    It is also what makes slice 007's *retrieval quality* metric measurable at
    all: "were the guidelines this run used relevant?" cannot be answered from a
    run that did not keep them.
    """

    text: str
    source: str


@dataclass(frozen=True, slots=True)
class GuidelineQuery:
    """What the caller is writing, so an implementation can be relevant.

    Deliberately expressed in the *domain's* terms — a role, a set of
    requirements, a section — rather than in retrieval's terms. A static rubric
    can ignore all of it; a retrieval implementation can embed it. Neither has
    to know what the other does.
    """

    role_title: str
    requirements: Sequence[str] = ()
    section: str | None = None


class GuidelineSource(Protocol):
    """One question in, guidance out.

    Called by the Plan and Draft nodes rather than ahead of the graph, because
    Draft's query depends on what Plan decided. `docs/08` §3.2.3 draws
    "Retrieve resume guidelines" as a step between Analyze and Draft; it is
    **not** a graph node, and making it one in slice 006 would be a workflow
    change caused by nothing but RAG arriving.
    """

    async def guidelines_for(self, *, context: GuidelineQuery) -> Sequence[Guideline]: ...


#: The rubric, until slice 006 replaces the source.
#:
#: Short and explicit on purpose. It must **not** grow into a long document, and
#: it must **not** vary by job — both are 006's job, and building either here
#: would make this port's shape wrong.
#:
#: Every rule is one the profile can actually satisfy without inventing
#: anything. That is the constraint that makes a rubric safe to hand a model
#: which is also being asked to sell someone: "quantify your impact" invites a
#: fabricated number unless it is bounded by "only where the profile supplies
#: one", so it is.
_RUBRIC: tuple[Guideline, ...] = (
    Guideline(
        text=(
            "Lead each role with the work most relevant to this posting. A reader spends "
            "seconds per role and reads top-down."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "Open bullets with a concrete verb describing what the person did — built, led, "
            "migrated, reduced — not with 'responsible for' or 'worked on'."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "Quantify outcomes ONLY where the profile already supplies the number. Never "
            "estimate, round up, or introduce a figure the profile does not contain."
        ),
        source="CareerHQ house rubric v1 (AI-008)",
    ),
    Guideline(
        text=(
            "Mirror the posting's vocabulary where the profile genuinely supports it — if the "
            "profile says 'Postgres' and the posting says 'PostgreSQL', prefer the posting's "
            "word. Do not mirror a term the profile cannot back."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "State scale where the profile records it: team size, traffic, data volume, budget. "
            "Scale is what distinguishes similar-sounding experience."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "Drop items that serve no requirement in this posting rather than compressing them. "
            "A shorter resume that answers the posting beats a complete one that does not."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "Keep each bullet to one idea and one line where possible. Two ideas in a bullet "
            "means the reader remembers neither."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "The summary states what the person is and what they have done, in the terms this "
            "posting uses. It is not a statement of ambition or of what they are looking for."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "Order skills by relevance to the posting, not alphabetically or by comfort. Do not "
            "add a skill the profile does not list."
        ),
        source="CareerHQ house rubric v1 (AI-008)",
    ),
    Guideline(
        text=(
            "Prefer the person's own phrasing for anything they corrected by hand. They chose "
            "those words deliberately."
        ),
        source="CareerHQ house rubric v1",
    ),
    Guideline(
        text=(
            "Where the profile shows adjacent rather than direct experience, describe it "
            "accurately as what it was. Presenting adjacent work as direct is the same "
            "fabrication as inventing it."
        ),
        source="CareerHQ house rubric v1 (AI-008)",
    ),
    Guideline(
        text=(
            "Keep formatting plain: no tables, columns, graphics or icons. Applicant tracking "
            "systems parse them badly or not at all."
        ),
        source="CareerHQ house rubric v1 (ATS)",
    ),
)


class StaticGuidelines:
    """The slice-005 implementation: the same rubric, every time.

    Ignores the query entirely, and says so rather than pretending otherwise. A
    static rubric that filtered by section would be a worse version of the
    retrieval this port exists to accept later, and would make the seam look
    like it does something it does not.
    """

    async def guidelines_for(self, *, context: GuidelineQuery) -> Sequence[Guideline]:
        return _RUBRIC


__all__ = [
    "Guideline",
    "GuidelineQuery",
    "GuidelineSource",
    "StaticGuidelines",
]
