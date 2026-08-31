"""The Career Advisor's named, versioned constants.

Every value here is a **first guess with a version number** — the only kind of
placeholder that does not rot silently (`finalisation_rules.py` established the
discipline, and `CONFIDENCE_THRESHOLD` is its precedent). None of them should
be read as evidence-based yet: they are named and versioned precisely so that
changing one, once slice 007-style measurement exists for the advisor, is an
honest act rather than a silent reinterpretation.

**Changing any constant below is a new `ADVISOR_RULES_VERSION`.** The version
is stamped on every `AdvisorRun` row, because a comparison across runs governed
by different unnamed rules measures nothing — the same argument
`match_criteria.py` and `FINALISATION_RULES_VERSION` already make.

Everything here is deterministic application code with no session, no provider
and no I/O.
"""

from __future__ import annotations

from datetime import timedelta

#: Bump on any change below. Never edit a released version's constants.
ADVISOR_RULES_VERSION = "v1-advisor"

#: The small-sample honesty floor (spec FR-010, clarification Q2). A claim
#: whose cited evidence includes any denominator below this persists as
#: `tentative` — the honest downgrade — rather than as a full-confidence
#: active memory. Five is the smallest denominator at which "recurring" is a
#: defensible word; it is a calibratable placeholder, not a statistical truth.
SMALL_SAMPLE_FLOOR = 5

#: The hard cap on active + tentative memories per user (spec FR-016a,
#: clarification Q3). Forgetting is part of memory management: at the cap, a
#: create must be accompanied by a retire. Evaluated with dispositions applied
#: first, so a same-run create-plus-retire at the cap is valid and ends at the
#: cap (analyze remediation G4).
ACTIVE_MEMORY_CAP = 25

#: After this, a `pending` advisor run is treated as abandoned rather than
#: slow, and stops blocking a new request (the stuck-run lesson, three times
#: paid for in match analysis). Generous because a run is at most two
#: completions — an over-eager deadline would let two real runs race.
RUN_ABANDONED_AFTER = timedelta(minutes=10)

#: Phrases that assert causation. Observed co-occurrence must be worded as
#: such (spec FR-010): at current sample sizes a causal claim is exactly the
#: kind of confident overreach the grounding gate exists to refuse. Crude on
#: purpose — the prompt carries the same rule, and this list is the backstop,
#: not the teacher. Matched case-insensitively inside a proposed claim.
CAUSAL_PHRASES: tuple[str, ...] = (
    "because",
    "causes",
    "caused",
    "leads to",
    "led to",
    "due to",
    "results in",
    "resulted in",
)

__all__ = [
    "ACTIVE_MEMORY_CAP",
    "ADVISOR_RULES_VERSION",
    "CAUSAL_PHRASES",
    "RUN_ABANDONED_AFTER",
    "SMALL_SAMPLE_FLOOR",
]
