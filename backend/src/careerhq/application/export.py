"""Export preconditions. **FR-016 and nothing else** (T033).

The export *use case* — render, persist to object storage, write `ExportedDocument`, move
the status — is **T036**, and is deliberately not here. This module holds the one rule
that has to be true before any of that starts, so the rule can be stated, tested and
drilled on its own rather than discovered inside a function that has already spent an
object-storage round trip.

**It imports no renderer, and a test asserts that.** A guard that *can* render is a guard
that might render before refusing, and FR-016's refusal is meant to happen first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.domain.models import ExportedDocument, VersionStatus


class ExportRefused(RuntimeError):
    """The version may not be exported, and the message says which state refused it.

    **A distinct type, not a generic error.** "Your resume could not be exported" reads
    identically whether the version was never approved or whether WeasyPrint fell over,
    and only one of those is the user's to resolve. Deliberately **not** an `OSError`
    subclass, so a handler written for storage and rendering failures cannot swallow it.
    """


#: The states from which an export may proceed.
#:
#: **`READY` is the state the specs call `APPROVED`** — the value has been `ready` since
#: migration `0010`, and T005 kept it rather than rewriting the paid evaluation rows.
#:
#: **`EXPORTED` is here on purpose, and it resolves a conflict between two artefacts.**
#: `contracts/export.md` gives the precondition as *"the version is APPROVED"*, and
#: FR-019 moves the version to `EXPORTED` — so read literally, a version could be
#: exported exactly once, ever. But `ExportedDocument` carries **no unique constraint on
#: `resume_version_id`**, and its docstring says why: *"Re-exporting an approved version
#: is legitimate — a download that failed, a second copy."* That is already in the
#: schema. FR-016 asks whether a version **has been approved**, not what its status
#: literal is at this instant, and an exported version has been. A `READY`-only guard
#: would refuse the action the missing constraint exists to allow.
#:
#: **`SUBMITTED` is absent, and that is the model's rule rather than a preference.**
#: Export sets the status to `EXPORTED`; `SUBMITTED` is terminal — *"No transition leaves
#: it"* — so exporting a submitted version would move it out of a state nothing may
#: leave. FR-022 requires that refusal to be explicit rather than silent.
EXPORTABLE_STATUSES = frozenset({VersionStatus.READY, VersionStatus.EXPORTED})


def ensure_exportable(status: VersionStatus | str) -> None:
    """Raise `ExportRefused` unless this version may be exported (FR-016).

    Takes the status rather than the version: the rule is about one field, and a function
    that accepted the whole row would invite reading others and grow into the use case
    that belongs in T036.

    **Accepts a plain `str`, and the coercion is load-bearing.** `ResumeVersion.status` is
    a `String` column, so a row loaded in a session that did not create it comes back as
    `str` rather than as the enum member — the failure this project has already shipped
    twice with `is` comparisons. Membership and `==` both survive that, because
    `VersionStatus` is a `StrEnum`; **`.value` does not**, and the refusal message below
    used it. T033's tests passed enum members only and could not see it; the route found
    it on the first real request (T037).
    """
    status = VersionStatus(status)

    if status in EXPORTABLE_STATUSES:
        return

    if status == VersionStatus.SUBMITTED:
        raise ExportRefused(
            f"This version was already submitted ({status.value}) and cannot be exported "
            "again. A submitted resume is a historical record; revise it by creating a "
            "new version."
        )

    raise ExportRefused(
        f"This version is {status.value} and has not been approved. Approve the tailored "
        "resume before exporting it."
    )


async def latest_export(session: AsyncSession, version_id: uuid.UUID) -> ExportedDocument | None:
    """The export a person would get if they pressed download. `None` if there is none.

    **Here rather than at either call site, because two call sites is the whole
    problem.** The download route serves an export and the submit use case freezes one,
    and if those two ever disagreed about *which* export, a person would download one
    document and send a record of another — silently, since both would be real exports
    of the same version with, under FR-031, identical bytes. Sharing the query makes
    "you submit what you can download" true by construction instead of by two
    coincidentally matching `ORDER BY` clauses.

    **`id` makes the order stable, and it does not order by insertion.** `exported_at`
    defaults to `now()`, which PostgreSQL evaluates once per *transaction*, so two
    exports written in one transaction carry the same timestamp; the `id` tiebreak then
    makes the answer deterministic rather than plan-dependent, but the id is a random
    v4 and the row it picks is not the later one. That is acceptable only because no
    path exports twice in one transaction — each export is its own request — and because
    FR-031 makes the two objects byte-identical anyway. It is stated rather than assumed:
    a future caller that batched exports would need a real ordering column.

    In `export.py` rather than in `export_resume.py` so that the submit use case can ask
    the question without importing a module that can render: T033 asserts this file
    imports no renderer, which is what makes T038's "submission never re-renders" an
    import-graph property rather than a promise.
    """
    record: ExportedDocument | None = await session.scalar(
        select(ExportedDocument)
        .where(ExportedDocument.resume_version_id == version_id)
        .order_by(ExportedDocument.exported_at.desc(), ExportedDocument.id.desc())
        .limit(1)
    )
    return record


__all__ = ["EXPORTABLE_STATUSES", "ExportRefused", "ensure_exportable", "latest_export"]
