"""What the roles actually asked, and what to do about it (Advisor V2).

V1 stopped at the topic and two counts: *"Cloud Platforms — gap in 2 of 7"*.
The rows underneath were always there — every `tier2.*` fact freezes the
`record_ids` of the `match_requirements` rows it counted — but nothing resolved
them, so the interface could only restate the arithmetic in prose. This module
resolves that pointer chain and turns the row-level facts into an assessment
and one typed recommendation.

**Everything here is deterministic.** The inputs are rows the match analysis
already wrote (verbatim requirement text, verdict, shortfall, importance, and
the profile line it quoted); the outputs are a mix, a sentence, and a category.
No provider call is made, and none is needed: `shortfall` is the match
analysis's own judgement of *why* a requirement is unmet, which is exactly the
question "what should I do about it" turns on.

**Frozen evidence is a record of past justification, not a live view.** A row
whose application has since been deleted simply does not resolve; the count it
contributed to stays frozen, and the caller is told how many are missing rather
than being handed a smaller list that silently disagrees with the headline.

**Ownership comes from the session.** The resolver joins
`match_requirements → match_analyses → applications` and filters on
`applications.user_id`, so a record id belonging to another user resolves to
nothing at all rather than to someone else's requirement text.

**The taxonomy is versioned.** `ADVISOR_ACTION_RULES_VERSION` covers the
dominance thresholds and the category vocabulary; changing either is a new
version, never an edit, because the same discipline that governs the tier
thresholds governs these.
"""

from __future__ import annotations

import enum
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.advisor_tiers import Tier
from careerhq.domain.models import Application, MatchAnalysis, MatchRequirement

#: Bump on any change to the thresholds or the category vocabulary below.
ADVISOR_ACTION_RULES_VERSION = "v1-actions"

#: A shortfall (or a silence) must account for at least this share of the rows
#: that could carry one before it is called the cause. Below it the mix is
#: genuinely mixed, and saying so is more useful than picking a winner.
DOMINANCE_SHARE = 0.5

#: Verdicts that carry a shortfall. The database enforces the equivalence
#: (`ck_match_requirement_shortfall`): `confirmed` has nothing to explain and
#: `unverified` has nothing to explain it *with*.
_SHORTFALL_BEARING = frozenset({"partial", "transferable", "gap"})


class ActionCategory(enum.StrEnum):
    """What kind of next step the evidence supports.

    Five real actions and one honest refusal. The refusal is not a failure
    mode: a pattern that recurs without a dominant cause, or a claim whose
    rows no longer resolve, has no defensible next step, and inventing one
    would be the same overreach the grounding gate exists to prevent.
    """

    LEARN_BUILD = "learn_build"
    PROVE_IT = "prove_it"
    SURFACE_IT = "surface_it"
    ADD_IF_YOU_HAVE_IT = "add_if_you_have_it"
    KEEP_LEADING = "keep_leading"
    NO_ACTION_YET = "no_action_yet"


@dataclass(frozen=True, slots=True)
class SpecificRequirement:
    """One requirement row, as the posting worded it.

    `text` is verbatim — the match analysis stores the employer's own wording
    precisely so counts stay comparable between runs, and paraphrasing it here
    would break the same property one layer up.
    """

    requirement_id: uuid.UUID
    text: str
    verdict: str
    shortfall: str | None
    importance: int
    #: The profile line the analysis quoted as evidence, where it quoted one.
    profile_quote: str | None
    resolved: bool = True


@dataclass(frozen=True, slots=True)
class Specifics:
    """The resolved rows behind one memory, plus what could not be resolved."""

    items: list[SpecificRequirement] = field(default_factory=list)
    #: Rows the frozen evidence names that no longer exist or are not this
    #: user's. Reported rather than hidden: the headline counts are frozen, so
    #: a shorter list without an explanation would read as a contradiction.
    unresolved: int = 0

    @property
    def profile_quotes(self) -> list[str]:
        """Distinct quotes, in the order the rows present them."""
        seen: dict[str, None] = {}
        for item in self.items:
            if item.profile_quote:
                seen.setdefault(item.profile_quote.strip(), None)
        return list(seen)


@dataclass(frozen=True, slots=True)
class VerdictMix:
    """How the rows behind one memory are distributed."""

    total: int
    by_verdict: Mapping[str, int]
    by_shortfall: Mapping[str, int]

    @property
    def shortfall_rows(self) -> int:
        return sum(self.by_shortfall.values())

    @property
    def dominant_shortfall(self) -> str | None:
        """The single cause behind at least `DOMINANCE_SHARE` of the rows that
        could name one, or `None` when the mix has no clear winner."""
        if not self.shortfall_rows:
            return None
        cause, count = max(self.by_shortfall.items(), key=lambda kv: (kv[1], kv[0]))
        ties = [c for c, n in self.by_shortfall.items() if n == count]
        if len(ties) > 1 or count / self.shortfall_rows < DOMINANCE_SHARE:
            return None
        return cause

    @property
    def silent(self) -> bool:
        """The profile says nothing either way about most of these asks."""
        if not self.total:
            return False
        return self.by_verdict.get("unverified", 0) / self.total >= DOMINANCE_SHARE


@dataclass(frozen=True, slots=True)
class Recommendation:
    category: ActionCategory
    text: str


# -- resolution --------------------------------------------------------------


def requirement_ids(evidence: Any) -> list[uuid.UUID]:
    """The requirement rows one memory's frozen evidence points at.

    Prefers the `tier2.requirement.*` fact, whose `record_ids` are every member
    row; falls back to the gap fact's subset when a memory cited only that.
    Anything that is not a parseable UUID is skipped rather than raising —
    frozen evidence is data written in the past, and a reader must survive it.
    """
    requirement: list[str] = []
    gap: list[str] = []
    facts = evidence.get("facts") if isinstance(evidence, dict) else None
    for fact in facts if isinstance(facts, list) else []:
        if not isinstance(fact, dict):
            continue
        fact_id = str(fact.get("fact_id", ""))
        raw = fact.get("record_ids")
        ids = [str(value) for value in raw] if isinstance(raw, list) else []
        if fact_id.startswith("tier2.requirement."):
            requirement = ids
        elif fact_id.startswith("tier2.gap."):
            gap = ids

    parsed: list[uuid.UUID] = []
    for value in requirement or gap:
        try:
            parsed.append(uuid.UUID(value))
        except (ValueError, AttributeError, TypeError):
            continue
    return parsed


async def resolve_specifics(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    evidence_by_memory: Mapping[uuid.UUID, Any],
) -> dict[uuid.UUID, Specifics]:
    """Resolve every memory's requirement rows in **one** query.

    Batched deliberately: the advisor page renders the whole active set, and a
    per-memory query would put the page's cost on the number of memories —
    the N+1 shape this project has paid for elsewhere. One `IN` over the union
    of ids, then a local regroup.
    """
    wanted: dict[uuid.UUID, list[uuid.UUID]] = {
        memory_id: requirement_ids(evidence) for memory_id, evidence in evidence_by_memory.items()
    }
    every_id = {row_id for ids in wanted.values() for row_id in ids}
    if not every_id:
        return {memory_id: Specifics() for memory_id in wanted}

    rows = (
        await session.execute(
            select(
                MatchRequirement.id,
                MatchRequirement.text_,
                MatchRequirement.verdict,
                MatchRequirement.shortfall,
                MatchRequirement.importance,
                MatchRequirement.evidence,
            )
            .join(MatchAnalysis, MatchAnalysis.id == MatchRequirement.analysis_id)
            .join(Application, Application.id == MatchAnalysis.application_id)
            .where(
                MatchRequirement.id.in_(every_id),
                # Ownership comes from the session, never from the row the
                # frozen evidence names.
                Application.user_id == user_id,
            )
        )
    ).all()

    by_id = {
        row.id: SpecificRequirement(
            requirement_id=row.id,
            text=row.text_,
            verdict=str(row.verdict),
            shortfall=str(row.shortfall) if row.shortfall else None,
            importance=row.importance,
            profile_quote=row.evidence,
        )
        for row in rows
    }

    resolved: dict[uuid.UUID, Specifics] = {}
    for memory_id, ids in wanted.items():
        found = [by_id[row_id] for row_id in ids if row_id in by_id]
        # Most important ask first; text is the tie-break so the order is a
        # function of the data rather than of row arrival.
        found.sort(key=lambda item: (-item.importance, item.text))
        resolved[memory_id] = Specifics(items=found, unresolved=len(ids) - len(found))
    return resolved


def mix_of(specifics: Specifics | None) -> VerdictMix:
    """Count the rows by verdict and by shortfall."""
    items = specifics.items if specifics else []
    return VerdictMix(
        total=len(items),
        by_verdict=Counter(item.verdict for item in items),
        by_shortfall=Counter(
            item.shortfall
            for item in items
            if item.shortfall and item.verdict in _SHORTFALL_BEARING
        ),
    )


# -- assessment and recommendation -------------------------------------------

#: Deliberately free of numbers. The counts are stated once, in the headline;
#: an assessment that repeated them would be the V1 duplication returning in a
#: new place.
_ASSESSMENT: dict[str, str] = {
    "capability": "You partly meet these asks — the shortfalls are depth of hands-on capability.",
    "evidence": "Your profile points this way, but the asks want concrete proof.",
    "wording": "You appear to have this; the asks are not matched by how your profile words it.",
    "silent": "Your profile says nothing either way about these asks.",
    "mixed": "The shortfalls are mixed — no single cause dominates.",
    "met": "Consistently met across the roles that ask for it.",
    "unavailable": "The requirements behind this claim are no longer available to read.",
}

_ACTION_TEXT: dict[ActionCategory, str] = {
    ActionCategory.LEARN_BUILD: (
        "Build hands-on depth here — this is a capability gap, not a wording one."
    ),
    ActionCategory.PROVE_IT: (
        "Add concrete proof — a project, a metric, an artefact the asks can point at."
    ),
    ActionCategory.SURFACE_IT: ("You have this; make it visible and explicit in your profile."),
    ActionCategory.ADD_IF_YOU_HAVE_IT: (
        "Your profile is silent here — add this experience if you have it, then re-run."
    ),
    ActionCategory.KEEP_LEADING: ("A consistent strength — keep leading with it."),
    ActionCategory.NO_ACTION_YET: ("Not enough to point at one next step yet — tracking it."),
}

#: Tiers whose evidence base is strong enough to carry a specific action at
#: all. Observation and emerging are watched, not acted on — the V1 threshold
#: decision, honoured here rather than re-litigated.
_ACTIONABLE_TIERS = frozenset({Tier.RECOMMENDATION, Tier.PATTERN})


def assess(tier: Tier, mix: VerdictMix) -> str | None:
    """One number-free sentence naming what the rows show, or `None` where the
    memory is not a skill claim at all."""
    if tier in (Tier.PORTFOLIO, Tier.DATA_NOTE):
        return None
    if not mix.total:
        return _ASSESSMENT["unavailable"]
    if tier == Tier.STRENGTH:
        return _ASSESSMENT["met"]
    if mix.silent:
        return _ASSESSMENT["silent"]
    cause = mix.dominant_shortfall
    return _ASSESSMENT[cause] if cause in _ASSESSMENT else _ASSESSMENT["mixed"]


def recommend(tier: Tier, mix: VerdictMix) -> Recommendation | None:
    """The one next step the evidence supports, or `None` for a memory that is
    not a skill claim.

    Topic-level by design: naming a specific technology would require a tag
    grounded in the row text, which this slice deliberately does not attempt.
    """
    if tier in (Tier.PORTFOLIO, Tier.DATA_NOTE):
        return None
    # **`not mix.total` is checked before the tier, in the same order `assess`
    # checks it.** The two disagreed: `assess` returned "the requirements are no
    # longer available to read" while this returned "a consistent strength — keep
    # leading with it", for the same memory in the same payload. A recommendation
    # is only as good as the rows under it, whatever the tier says.
    if not mix.total:
        return Recommendation(
            ActionCategory.NO_ACTION_YET, _ACTION_TEXT[ActionCategory.NO_ACTION_YET]
        )
    if tier == Tier.STRENGTH:
        return Recommendation(
            ActionCategory.KEEP_LEADING, _ACTION_TEXT[ActionCategory.KEEP_LEADING]
        )
    if tier not in _ACTIONABLE_TIERS:
        return Recommendation(
            ActionCategory.NO_ACTION_YET, _ACTION_TEXT[ActionCategory.NO_ACTION_YET]
        )
    if mix.silent:
        return Recommendation(
            ActionCategory.ADD_IF_YOU_HAVE_IT, _ACTION_TEXT[ActionCategory.ADD_IF_YOU_HAVE_IT]
        )
    by_cause = {
        "capability": ActionCategory.LEARN_BUILD,
        "evidence": ActionCategory.PROVE_IT,
        "wording": ActionCategory.SURFACE_IT,
    }
    category = by_cause.get(mix.dominant_shortfall or "", ActionCategory.NO_ACTION_YET)
    return Recommendation(category, _ACTION_TEXT[category])


def specific_labels(specifics: Specifics, *, limit: int = 3) -> list[str]:
    """Short labels for the compact card, taken **verbatim** from the rows.

    Shortened, never paraphrased and never generalised into a technology name:
    the row text is the only thing the evidence supports, so a label that said
    "AWS" where the row said "cloud platforms" would be inventing specificity.
    """
    labels: list[str] = []
    for item in specifics.items[:limit]:
        text = " ".join(item.text.split())
        labels.append(text if len(text) <= 48 else text[:47].rstrip(" ,;:-") + "…")
    return labels
