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
    #: Which market this CV is being written for. **Added at T027, and it is the
    #: second half of FR-038.** Precedence is scoped *"for Israeli-market CVs"*,
    #: so retrieval that cannot tell which market it is serving cannot apply it —
    #: a gap that survives any amount of topic metadata, and that R13 surfaced
    #: alongside the topic one.
    #:
    #: Domain vocabulary, not retrieval's: it says something about the document
    #: being written, which is exactly what this query is for. `"global"` is the
    #: default so an unchanged caller keeps its existing behaviour.
    #:
    #: **The default stays `global`, and V1's actual answer is stated at the call
    #: site** — `tailor_resume.V1_TARGET_MARKET`, decided as OQ-006-B on
    #: 2026-08-28. Expressing a product decision by moving a default here would
    #: make every future caller Israeli by omission, which is the invisible
    #: inference that decision exists to avoid, relocated one layer down.
    market: str = "global"
    #: Unused as of slice 006 (decision D2): guidance is retrieved once for the
    #: whole run, so there is no per-section query to carry. Kept because it
    #: costs nothing and is exactly what a future per-node implementation would
    #: need — but it is dead today, and pretending otherwise would be worse.
    section: str | None = None


class GuidelineSource(Protocol):
    """One question in, guidance out.

    **Called once, in the use case, before the graph is invoked** — the result
    is placed in `TailoringState.guidelines` and shared by every node that
    consumes it (today Plan and Draft). Slice 006 decision D2.

    An earlier version of this docstring said the opposite: that Plan and Draft
    would each call it, because Draft's query depends on what Plan decided. The
    implementation never did that, and slice 006 resolved the conflict in favour
    of the implementation rather than the prose. The reasoning, so it is not
    re-litigated:

    * The rendered guidance block is **507 tokens, 5.3% of the ~9,630-token
      Draft prompt**, and retrieval replaces it with at most **1,500 tokens**
      under the FR-014 ceiling — ~15.6% of that prompt. Plan-aware retrieval's
      real job is fitting a context budget, and at this scale no such budget
      binds. (An earlier version of this bullet said "~1,690 tokens at 40
      retrieved chunks", computed at 42 tokens/rule; corpus rules measure ~76,
      so 40 chunks cannot fit under the ceiling at all. The ceiling is the
      honest bound and it makes this argument stronger, not weaker.)
    * Resume-writing guidance is largely **job-independent**. "Never invent a
      number", "no tables or columns" hold for every posting. The plan decides
      which *profile items* to emphasise; it does not imply different *writing
      advice*. So the plan adds little to a query that already carries the job
      requirements the plan was derived from.
    * Per-node retrieval would have changed the Draft node's body and this
      graph's wiring for a benefit nobody has measured — churn in a workflow
      that had just stabilised.

    What is still true, and still forbids the other shape: retrieval is **not a
    graph node**, and making it one would be a workflow change caused by nothing
    but RAG arriving.

    **When to revisit.** Only if slice 007's retrieval-quality metric shows the
    single shared query missing guidance a per-node query would have found. That
    is a measurement, not a preference — and until it exists, the shared call
    stands.
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
