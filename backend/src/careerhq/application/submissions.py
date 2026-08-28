"""What an application actually sent. **FR-024 and nothing else** (T040).

**This is the pointer, not the artefact.** FR-023 — that a submitted record does not move
when the profile does — is a property of `SubmittedResume` itself, and is held by the
record snapshotting bytes rather than referencing rows. This module answers the other
half of Constitution IV: *"Applications in `Applied` or later status MUST reference a
Submitted Resume."* A perfectly frozen record that no application can be traced back to
fails that requirement just as completely as a mutable one.

**One function, so there is one answer.** "What did this application send" must not be
answerable in two places, because the wrong second answer is always available and always
plausible: the latest version, the latest export, the master résumé. Each of those is a
real document, and each would name something the employer never received —
`docs/03` §12.2: *"Applications may not reference editable Resume Versions as submitted
documents."* Export does not imply submission; a person may export a PDF and never send
it.

**The scope of the invariant, stated honestly.** `docs/03` §5.2 gives the rule as a
universal — every application at `Applied` or later references a submission — and the
universal is **false against real data**. Applications are imported from a job tracker at
`Applied`, `Interview Round 2` and `Rejected`, and none of them has a document here
because none was ever tailored here. What this module guarantees is that the reference is
mandatory, cannot dangle, resolves to exactly one record, and is never answered with
something editable. What it does not do is invent a submission for a row that has none:
`None` is the truthful answer, and a fabricated one would defeat the requirement it
appeared to satisfy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.domain.models import NormalizedStatus, SubmittedResume

#: The analytics categories that could only have been reached by applying.
#:
#: `NormalizedStatus` is a category rather than a lifecycle position, so "`Applied` or
#: later" has to be derived from what a category *implies*. `REJECTED` and `GHOSTED`
#: qualify because an employer cannot reject or ignore someone who never wrote to them.
#:
#: **`WITHDRAWN` is excluded, and it is the judgement worth stating.** `docs/03` §10.2
#: draws `Wishlist → Withdrawn` directly: a withdrawn application may never have been
#: sent. **`OTHER` is excluded** because it is the bucket for a label this system does
#: not recognise — it asserts nothing, and an invariant asserted over an unknown is a
#: guess dressed as a rule.
APPLIED_OR_LATER = frozenset(
    {
        NormalizedStatus.APPLIED,
        NormalizedStatus.INTERVIEWING,
        NormalizedStatus.OFFER,
        NormalizedStatus.REJECTED,
        NormalizedStatus.GHOSTED,
    }
)


def has_applied(status: NormalizedStatus | str) -> bool:
    """Whether this category means the application was actually sent (FR-024).

    **Accepts a plain `str`, and the coercion is load-bearing.**
    `Application.normalized_status` is a `String` column, so a row loaded in a session
    that did not create it comes back as `str` rather than as the enum member — the
    defect this project has already shipped twice with `is` comparisons.
    """
    return NormalizedStatus(status) in APPLIED_OR_LATER


async def submission_for(
    session: AsyncSession, *, application_id: uuid.UUID
) -> SubmittedResume | None:
    """The résumé this application sent, or `None` if it sent none through CareerHQ.

    **`None` is an answer, not a failure.** An application that reached `Applied` outside
    this system has no document here, and the only honest thing to return is nothing. A
    fallback to the latest export would answer confidently and wrongly.

    One row at most: `submitted_resumes` is unique on `resume_version_id` and a second
    send is a new version (FR-025), so an application with several versions could in
    principle carry several submissions — the most recent is the one it sent last, and
    the ordering is explicit rather than left to the plan.
    """
    record: SubmittedResume | None = await session.scalar(
        select(SubmittedResume)
        .where(SubmittedResume.application_id == application_id)
        .order_by(SubmittedResume.submitted_at.desc(), SubmittedResume.id.desc())
        .limit(1)
    )
    return record


__all__ = ["APPLIED_OR_LATER", "has_applied", "submission_for"]
