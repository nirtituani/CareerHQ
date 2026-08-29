"""Mark an exported version as submitted (T038, FR-020/FR-021).

**Submission promotes an export; it never produces one.** The bytes an employer received
already exist, so the whole operation is a verification followed by a snapshot:

    ensure_submittable  →  load the stored bytes  →  SHA-256  →  compare  →
    SubmittedResume  →  status = SUBMITTED

**The recorded checksum is not evidence about the bytes**, and this is the substance of
the task rather than an implementation detail. `ExportedDocument.checksum_sha256` says
what the export *believed* it stored; FR-021 asks for "a stable checksum of the exact
document sent", and Constitution IV rests on being able to produce that document later.
Copying the row forward would verify nothing — it would succeed identically against an
object that had since been replaced, truncated, or lost — so the bytes are read back and
hashed, and the comparison is a precondition of writing anything.

**A mismatch refuses and repairs nothing.** Not by re-rendering: the version's items are
independent of the stored PDF only by lifecycle, and a re-render is a *different*
document wearing the same record. Not by rewriting the export's checksum either, which
would launder an unexplained discrepancy into a row that looks verified forever. Both the
object and the row are left exactly as they were, for a person to look at.

**The use case flushes; the caller commits** — the boundary `run_tailoring` and
`export_version` already set, so a route can span several use cases in one transaction.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.export import latest_export
from careerhq.domain.models import ResumeVersion, SubmittedResume, VersionStatus
from careerhq.infrastructure import storage


class SubmissionRefused(RuntimeError):
    """This version may not be submitted, and the message says why.

    A *state* refusal, and the person can act on it: export first, or create a new
    version. FR-022 requires the refusal to be explicit rather than silent — a no-op on
    an immutability guarantee is indistinguishable from success.
    """


class ExportChecksumMismatch(RuntimeError):
    """The stored document is not the document the export recorded.

    **Deliberately not a `SubmissionRefused`.** They are different failures with
    different owners: a state refusal is resolved by the person doing the obvious next
    thing, while this one cannot be resolved by clicking again — the artefact does not
    match its record, and that is an operator's question. If this inherited, a handler
    written for refusals would report corruption as "export it first", and an
    implementation that dropped the integrity check altogether could still satisfy a
    test that only demanded "a refusal".
    """


#: The one state a submission may start from.
#:
#: **`READY` is absent, and that is the distinction worth stating.** The version is
#: approved, which is the green light everywhere else in the system — but there is no
#: stored document, so there is nothing to verify and nothing to freeze. Submission is a
#: claim about a *document* that was sent, not about a version that was approved.
#:
#: `SUBMITTED` is absent because it is terminal: what was sent is a historical fact, and
#: a second send is a new version (FR-025), which the unique constraint on
#: `submitted_resumes.resume_version_id` also enforces where two clicks cannot race it.
SUBMITTABLE_STATUSES = frozenset({VersionStatus.EXPORTED})


def ensure_submittable(status: VersionStatus | str) -> None:
    """Raise `SubmissionRefused` unless this version may be submitted.

    **Accepts a plain `str`, and the coercion is load-bearing.** `ResumeVersion.status`
    is a `String` column, so a row loaded in a session that did not create it comes back
    as `str` rather than as the enum member. Membership and `==` survive that because
    `VersionStatus` is a `StrEnum`; **`.value` does not**, and the messages below use it.
    That exact defect shipped in `ensure_exportable` and was found by the first real
    request rather than by its tests, which passed enum members only.
    """
    status = VersionStatus(status)

    if status in SUBMITTABLE_STATUSES:
        return

    if status == VersionStatus.SUBMITTED:
        raise SubmissionRefused(
            "This version has already been submitted. What was sent to an employer is a "
            "historical record; to send something different, revise it as a new version."
        )

    raise SubmissionRefused(
        f"This version is {status.value} and has not been exported. Export the approved "
        "resume as a PDF before marking it submitted."
    )


#: PostgreSQL's SQLSTATE for a unique violation. A standard code rather than a driver
#: exception class, so nothing here imports the database driver into the application layer.
_UNIQUE_VIOLATION = "23505"


def _is_duplicate_submission(error: IntegrityError) -> bool:
    """Whether this is *the* race — a second submission of one version — or something else.

    **Narrow on purpose.** Catching every `IntegrityError` here would turn any future
    constraint failure on this insert into "already submitted", which is a wrong answer
    delivered confidently.

    **Two conditions, and both are exact.** The SQLSTATE must be a unique violation, and
    PostgreSQL's diagnostic `table_name` must be *this table* — compared for equality,
    never as a substring, and never against `constraint_name`. A substring test would
    match a constraint merely *named* after this table, and reading `constraint_name`
    would tie the branch to a name PostgreSQL generates from a column-level `unique=True`
    and that is written down nowhere this code could keep in step with. `table_name` is
    the thing PostgreSQL reports about the row it refused.

    **It stays wrong for the right reason if a second unique constraint is ever added
    here**: this predicate would classify that violation as the duplicate-submission race
    too. There is exactly one unique constraint on the table today — `resume_version_id`,
    the one FR-025 rests on — and adding another is the moment to give this a column test
    as well.
    """
    original = error.orig
    if getattr(original, "sqlstate", None) != _UNIQUE_VIOLATION:
        return False
    diagnostic = getattr(original, "diag", None)
    return getattr(diagnostic, "table_name", None) == SubmittedResume.__tablename__


async def submit_version(session: AsyncSession, *, version_id: uuid.UUID) -> SubmittedResume:
    """Verify the stored export and record that it was sent.

    Raises `SubmissionRefused` when the version may not be submitted,
    `ExportChecksumMismatch` when the stored bytes no longer hash to the recorded
    checksum, and `LookupError` when the version does not exist — never `None`, which
    would make every caller guess.
    """
    version = await session.scalar(select(ResumeVersion).where(ResumeVersion.id == version_id))
    if version is None:
        raise LookupError(f"resume version {version_id} does not exist")

    # First, and before the object-storage round trip: a version that may not be
    # submitted costs nothing and leaves no trace.
    ensure_submittable(version.status)

    export = await latest_export(session, version.id)
    if export is None:
        # `export_version` writes the row and moves the status together, so this state
        # is unreachable by any code path here. Pinned anyway: an inconsistency that
        # surfaces as a `TypeError` inside a hash call tells the person nothing.
        raise SubmissionRefused(
            "This version is marked exported but no exported document is recorded for "
            "it. Export it again before marking it submitted."
        )

    # **The verification.** Read what is actually there, hash that, compare.
    data = await storage.get_object(export.document_storage_key)
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != export.checksum_sha256:
        raise ExportChecksumMismatch(
            "The stored document no longer matches the checksum recorded when it was "
            "exported, so it cannot be recorded as the document that was sent. Export "
            "this version again and check the result before submitting it."
        )

    # The **measured** values, not the row's. They are equal — the comparison above just
    # said so — but writing what was verified keeps the snapshot a statement about bytes
    # somebody read rather than a copy of a row that might not have been checked.
    record = SubmittedResume(
        resume_version_id=version.id,
        application_id=version.application_id,
        document_storage_key=export.document_storage_key,
        checksum_sha256=checksum,
        byte_size=len(data),
    )
    # **The guard above is a read, and two clicks land in the gap after it.** Both
    # requests see `EXPORTED`, both verify the bytes, and both arrive here. Only the
    # unique constraint on `resume_version_id` can settle that, which is why it exists
    # and why it is not an application-level check — but losing it must still *read* as
    # a refusal. An `IntegrityError` escaping here reaches the route unhandled and
    # answers **500**, telling the person the system broke when it correctly declined.
    #
    # The message is deliberately the one `ensure_submittable` gives a sequential second
    # attempt: by the time anyone reads it, that is exactly what happened.
    #
    # **The savepoint is what keeps this a refusal rather than a wound.** A failed flush
    # aborts the whole PostgreSQL transaction, so without it the caller's session is
    # unusable afterwards — and this project's contract is that *the caller* owns the
    # transaction and may span several use cases in one. Every other refusal here costs
    # nothing; this one would have cost the caller everything it had written.
    #
    # ***The insert and the status change are inside the block, and that is the whole of
    # why it works.*** Wrapping only the `flush()` does **not** help: writes registered
    # before the savepoint belong to the outer transaction, and its failure poisons that
    # transaction no matter where the flush was issued. Measured, not reasoned — the form
    # with `session.add` left outside leaves the session in exactly the failed state this
    # exists to prevent. `test_a_refusal_leaves_the_session_usable_whichever_branch_raised_it`
    # is what fails if anyone moves them back out.
    #
    # **Rolling the session back here was rejected**, and also measured: it makes the
    # session usable by destroying the caller's earlier uncommitted writes — a use case
    # silently discarding its caller's work, which is worse than the state it fixes.
    try:
        async with session.begin_nested():
            session.add(record)
            version.status = VersionStatus.SUBMITTED
            await session.flush()
    except IntegrityError as clash:
        if not _is_duplicate_submission(clash):
            raise
        raise SubmissionRefused(
            "This version has already been submitted. What was sent to an employer is a "
            "historical record; to send something different, revise it as a new version."
        ) from clash

    return record


__all__ = [
    "SUBMITTABLE_STATUSES",
    "ExportChecksumMismatch",
    "SubmissionRefused",
    "ensure_submittable",
    "submit_version",
]
