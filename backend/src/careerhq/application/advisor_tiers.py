"""Read-time tier classification: Evidence -> Pattern -> Recommendation -> Action.

A career memory's **lifecycle** (active / tentative / superseded / retired) is
stored and answers "is this the agent's current understanding?". A memory's
**tier** is a different question — "how strong is the evidence behind it, and
is it actionable?" — and it is **derived at read time from the memory's own
frozen evidence**, never stored. This mirrors how match staleness and research
freshness are derived rather than persisted: a stored tier would go wrong the
moment the rules changed, and the rules are explicitly calibratable.

**Deterministic and grounded.** Every input is a number already frozen into
the memory's evidence by the grounding gate — the LLM is not consulted here and
cannot promote a weak pattern to a recommendation. The model's `priority` only
orders memories *within* a tier; the tier itself is arithmetic.

**These constants are a v1 policy with a version number, not a permanent
truth.** `ADVISOR_TIER_RULES_VERSION` is returned to the client so a change is
legible, and — because tiers are re-derived at read time — a change re-labels
history under the new rules. That is acceptable for *presentation*; it never
rewrites the frozen evidence underneath.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

#: Bump on any threshold change below.
ADVISOR_TIER_RULES_VERSION = "v1-tiers"

#: A skill claim needs at least this much coverage (analysed postings) before
#: it is more than an isolated observation. Two postings is not a market.
MIN_COVERAGE = 3
#: ...and the skill must recur — a single occurrence is an observation.
MIN_OCCURRENCES_FOR_PATTERN = 2
#: "Established" (strong enough to carry a recommendation or a strength).
MIN_OCCURRENCES_ESTABLISHED = 4
MIN_OCCURRENCES_ESTABLISHED_WITH_MAJORITY = 3
FREQUENCY_MAJORITY = 0.5
#: A recommendation is an established, recurring *gap*: the gap itself must have
#: recurred (absolute count) and dominate the postings that require the skill.
MIN_GAP_FOR_RECOMMENDATION = 3
GAP_RATE_ACTION = 0.5
#: A strength is an established skill that is consistently met.
GAP_RATE_STRENGTH = 0.2


class Tier(enum.StrEnum):
    """The presentation tier a memory falls into. Open in spirit but closed in
    code: these five plus the two non-skill buckets are the whole vocabulary."""

    OBSERVATION = "observation"
    EMERGING = "emerging"
    PATTERN = "pattern"
    RECOMMENDATION = "recommendation"
    STRENGTH = "strength"
    #: Non-skill memories: search-level facts (rejection rate, volume, timing).
    PORTFOLIO = "portfolio"
    #: The inconsistent-imported-dates data-quality fact and its kin.
    DATA_NOTE = "data_note"


#: Which UI section each tier belongs to. The section is what the first view
#: groups by; the tier is the finer label shown on the chip.
SECTION_OF: dict[Tier, str] = {
    Tier.RECOMMENDATION: "recommended",
    Tier.EMERGING: "emerging",
    Tier.PATTERN: "emerging",
    Tier.OBSERVATION: "emerging",
    Tier.STRENGTH: "strengths",
    Tier.PORTFOLIO: "portfolio",
    Tier.DATA_NOTE: "data_notes",
}


@dataclass(frozen=True, slots=True)
class TierEvidence:
    """The numbers a skill memory's tier is computed from, read out of the
    frozen evidence. `None` where the memory is not a skill pattern."""

    #: analysed postings (denominator), skill occurrences, gap/partial count.
    coverage: int | None = None
    occurrences: int | None = None
    gaps: int | None = None
    topic: str | None = None
    #: Whether the evidence carried a `tier2.*` fact at all.
    is_skill: bool = False
    #: Whether the memory looks like a data-quality note.
    is_data_note: bool = False


def _facts(evidence: Any) -> list[dict[str, Any]]:
    if not isinstance(evidence, dict):
        return []
    facts = evidence.get("facts")
    return [f for f in facts if isinstance(f, dict)] if isinstance(facts, list) else []


def read_tier_evidence(evidence: Any) -> TierEvidence:
    """Extract the tier inputs from a memory's frozen evidence. Backward
    compatible: a memory whose evidence carries no `tier2.*` fact (Tier-1, or
    anything pre-dating this) simply comes back non-skill and is bucketed as a
    portfolio insight or data note — never an error."""
    requirement: dict[str, Any] | None = None
    gap: dict[str, Any] | None = None
    data_note = False
    for fact in _facts(evidence):
        fact_id = str(fact.get("fact_id", ""))
        if fact_id.startswith("tier2.requirement."):
            requirement = fact
        elif fact_id.startswith("tier2.gap."):
            gap = fact
        elif fact_id.startswith("timing.inconsistent_dates"):
            data_note = True

    if requirement is not None:
        return TierEvidence(
            coverage=int(requirement.get("denominator", 0)),
            occurrences=int(requirement.get("numerator", 0)),
            gaps=int(gap.get("numerator", 0)) if gap is not None else 0,
            topic=requirement.get("scope_value"),
            is_skill=True,
        )
    return TierEvidence(is_data_note=data_note)


def classify(evidence: Any) -> Tier:
    """The v1 policy, applied to one memory's frozen evidence."""
    ev = read_tier_evidence(evidence)

    if not ev.is_skill:
        return Tier.DATA_NOTE if ev.is_data_note else Tier.PORTFOLIO

    coverage = ev.coverage or 0
    occurrences = ev.occurrences or 0
    gaps = ev.gaps or 0

    # Gate A — enough coverage and repetition to say anything at all.
    if coverage < MIN_COVERAGE or occurrences < MIN_OCCURRENCES_FOR_PATTERN:
        return Tier.OBSERVATION

    frequency = occurrences / coverage if coverage else 0.0
    established = occurrences >= MIN_OCCURRENCES_ESTABLISHED or (
        occurrences >= MIN_OCCURRENCES_ESTABLISHED_WITH_MAJORITY and frequency >= FREQUENCY_MAJORITY
    )
    if not established:
        return Tier.EMERGING

    # Gate C — overlay the gap dimension on an established pattern.
    gap_rate = gaps / occurrences if occurrences else 0.0
    if gaps >= MIN_GAP_FOR_RECOMMENDATION and gap_rate >= GAP_RATE_ACTION:
        return Tier.RECOMMENDATION
    if gap_rate <= GAP_RATE_STRENGTH:
        return Tier.STRENGTH
    return Tier.PATTERN


#: Generic, deterministic action scaffolds by tier — grounded in the memory's
#: own counts, no LLM and no shortfall/importance enrichment (that is v2). The
#: "why this matters" line the UI shows is the model's existing, grounded
#: `priority_reason`; this only supplies the neutral next-step framing.
_ACTION_TEMPLATES: dict[Tier, str] = {
    Tier.RECOMMENDATION: (
        "This is a recurring gap in the roles you target. Prioritise closing it — "
        "and make sure your profile shows any experience you already have here."
    ),
    Tier.STRENGTH: (
        "A consistent strength across your target roles. Keep it prominent in your "
        "profile and lead with it."
    ),
}


def action_for(tier: Tier, evidence: Any) -> str | None:
    """The next-step scaffold for a tier, or `None` where an action is not yet
    warranted (observation / emerging / pattern) — 'insufficient evidence' is a
    valid state, not an error."""
    del evidence  # v1 templates are tier-generic; v2 keys on shortfall mix.
    return _ACTION_TEMPLATES.get(tier)


def topic_for(tier: Tier, evidence: Any, *, kind: str, scope_value: str | None) -> str:
    """The chip's headline. A skill memory names its skill; otherwise fall back
    to the cleaned kind so a Tier-1 memory still reads sensibly."""
    ev = read_tier_evidence(evidence)
    if ev.is_skill and ev.topic:
        return str(ev.topic)
    if scope_value:
        return scope_value
    return kind.replace("_", " ")
