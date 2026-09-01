"""What happens to a draft once the Reviewer has finished with it.

This module is where Principles II and III are **reconciled rather than traded
off**. Principle III makes an unsupported claim a release blocker, so the system
enforces it and the owner is never consulted. Principle II says the owner
decides, so everything that is a matter of degree reaches them.

The rule that separates the two is the whole content of this file:

* `ungrounded` — the proposal is **discarded before persistence**. It never
  reaches a row, so it can never reach an approve button.
* `overstated` — persisted, shown, flagged against its item. The profile
  supports it; only the wording is in question, and that is judgement.
* `uncovered` — persisted, shown against the draft. Nothing to discard: it is
  an omission, not a claim.

**Changing any constant here is a new `FINALISATION_RULES_VERSION`.** Editing
one in place silently reinterprets every historical run, and slice 007 evaluates
this capability by comparing runs over time — a comparison across runs finalised
under different unnamed rules measures nothing. This is the same discipline
`match_criteria.py` follows, and for the same reason.

Everything here is deterministic application code with no session, no provider
and no I/O, which is what makes it testable without either.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from careerhq.domain.schemas.tailoring import DraftedItem, ReviewFinding

#: Bump on any change below. Never edit a released version's constants.
#:
#: `v1-severity` fed `finalise` the findings of **every** review pass, so a
#: pass-0 fabrication the Reviser fixed and the final review cleared was still
#: discarded — the owner saw "withdrawn" where a legitimate corrected proposal
#: existed. `v2-final-pass-severity` judges the discard on the final pass's
#: findings only (the caller filters; see `run_tailoring`), the same rule
#: `active_findings` applies to the revision gate. The split itself — what is
#: discarded versus shown — is unchanged.
#:
#: `v3-final-pass-t65` carries v2 forward and calibrates `CONFIDENCE_THRESHOLD`
#: from 70 to 65 (experiment E1, 2026-09-01) — see the threshold's own comment.
FINALISATION_RULES_VERSION = "v3-final-pass-t65"

#: Findings that mean *the profile does not support this claim at all*. The
#: proposal they concern is dropped and the owner's own wording stands.
_DISCARDING = frozenset({"ungrounded"})

#: Below this, the Reviewer has not cleared the draft and another revision is
#: attempted if the budget allows.
#:
#: **Calibrated to 65 by experiment E1 (2026-09-01)**, replacing the original
#: uncalibrated 70. Measured on true causal pairs (the same draft, shipped
#: versus revised): revisions triggered at 65-69 only de-overstated one or two
#: lines the owner sees flagged either way (FR-019), with no judged quality
#: difference — while low-60s revisions fixed 2-3 overstatements per run. 65
#: skips the former and keeps the latter. The evidence is directional, not
#: statistical: two causal pairs plus five historical pass-to-pass deltas.
#: An `ungrounded` finding still fails the draft at any confidence — the
#: threshold has never been part of the grounding guarantee.
CONFIDENCE_THRESHOLD = 65

#: How many revisions may be attempted before the draft is finalised as it
#: stands. Not extendable at run time (FR-013).
MAX_REVISIONS = 2


@dataclass(frozen=True, slots=True)
class Finalised:
    """The outcome of applying these rules to one reviewed draft."""

    #: The items as they will be persisted — discarded proposals already
    #: reverted to the owner's original wording.
    items: tuple[DraftedItem, ...]
    #: Every finding, including those whose proposal was discarded. The record
    #: of what the Reviewer caught is the evidence the guardrail ran, and slice
    #: 007 measures against it.
    findings: tuple[ReviewFinding, ...]
    #: Which item ids had a proposal removed. Reported so the caller can log or
    #: display *that* it happened without re-deriving the rule.
    discarded_item_ids: frozenset[str]


def clears_review(confidence: int, findings: Iterable[ReviewFinding]) -> bool:
    """Whether the draft is good enough to stop revising.

    An `ungrounded` finding fails the draft **regardless of confidence**. A
    model that both fabricates and reports high confidence is exactly the case
    the threshold cannot be trusted to catch, and it is the case Principle III
    is a release blocker about.
    """
    if any(f.kind in _DISCARDING for f in findings):
        return False
    return confidence >= CONFIDENCE_THRESHOLD


def should_revise(*, confidence: int, findings: Iterable[ReviewFinding], attempt: int) -> bool:
    """Whether to send the draft back. The conditional edge reads this."""
    return attempt < MAX_REVISIONS and not clears_review(confidence, findings)


def task_for_revision(attempt: int) -> str:
    """Which task name performs revision number `attempt`.

    The escalation from Sonnet to Opus is **a different task name**, not a
    branch on a model. `ports.py` resolves the model from the name, so
    `docs/08` §3.2.3 stays configuration rather than workflow code.

    The second attempt escalates because a Sonnet revision that has already
    failed to clear an Opus reviewer once is unlikely to clear it on a retry
    with the same model — the loop would burn attempts without converging.
    """
    return "tailor_revise" if attempt == 0 else "tailor_revise_escalated"


def finalise(
    items: Sequence[DraftedItem],
    findings: Sequence[ReviewFinding],
) -> Finalised:
    """Apply the severity split. **Called by the use case, never by a node.**

    A graph node that did this would be deciding a business outcome that
    survives the run, which contract O2 forbids — and the discarded proposal
    would exist in state where something downstream could still read it.
    """
    discarded = {
        str(f.source_item_id)
        for f in findings
        if f.kind in _DISCARDING and f.source_item_id is not None
    }

    kept: list[DraftedItem] = []
    for item in items:
        if item.source_item_id is not None and str(item.source_item_id) in discarded:
            # The owner's original wording stands. `text=None` means "unchanged"
            # everywhere else in this slice, so reverting is expressed the same
            # way the model expresses proposing nothing — one representation of
            # "no change", not two.
            kept.append(item.model_copy(update={"text": None, "reason": None}))
        else:
            kept.append(item)

    return Finalised(
        items=tuple(kept),
        findings=tuple(findings),
        discarded_item_ids=frozenset(discarded),
    )
