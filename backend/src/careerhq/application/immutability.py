"""When a tailored version stops being editable. **FR-022 and nothing else** (T039).

**Two states are locked, and which two is the substance of the rule.** `docs/03` §10.1:
*"`Ready` means user-approved. It remains editable; approval is not a one-way door **until
export**"*, and *"`Submitted` is terminal and **locked**. The Version cannot be edited
again."* The door closes when a document leaves the system — at export, because a PDF now
exists whose checksum was recorded against content that must not move under it, and at
submission, because Constitution IV requires an application to reproduce exactly what was
sent.

**`READY` is not locked, and that is a requirement rather than an oversight.** FR-029
states it outright: *"An approved version MUST remain editable."* A lock defined as
"approved means final" would read as the stricter, safer interpretation of the same
requirement, pass every immutability test, and quietly remove the ability to fix a typo
before exporting.

**The rule is about content, not about the row.** A locked version's status still moves
forward — `EXPORTED → SUBMITTED` is the one edge out of it, and re-export is legitimate
(T036 left `ExportedDocument` without a unique constraint on purpose). A guard that
refused every write to the row would make the lifecycle impossible, which is a worse
failure than the one this prevents: a version stranded at `EXPORTED` forever.

**Here rather than in `tailor_resume.py`** so the rule can be stated, tested and drilled
on its own, and so the routes translate one exception rather than re-deciding a status
set each — the shape `export.py` already established for FR-016.
"""

from __future__ import annotations

from careerhq.domain.models import VersionStatus


class VersionLocked(RuntimeError):
    """This version may not be modified, and the message says why.

    **A distinct type, and each thing it is not is load-bearing.** Not an `OSError`, so a
    handler written for storage and rendering failures cannot swallow it. Not a
    `ValueError`, which `decide_item` already raises for empty edit text and which the
    API answers with 422 — a *malformed* request, which this is not. And not a subclass
    of `ExportRefused` or `SubmissionRefused`: "you may not edit this" is a different
    answer from "this cannot be exported", and a caller that collapsed them would tell a
    person to do something that is not available.

    FR-022 requires the refusal to be **explicit**. A silent no-op on an immutability
    guarantee is indistinguishable from success, and Constitution IV makes that a release
    blocker.
    """


#: The states in which a version's content is frozen.
#:
#: Enumerated rather than expressed as "at or past export", because an ordering over an
#: enum is a second, implicit lifecycle definition — and this one has a branch in it
#: (`READY → DRAFT`, further editing) that no ordering describes.
LOCKED_STATUSES = frozenset({VersionStatus.EXPORTED, VersionStatus.SUBMITTED})


def ensure_version_mutable(status: VersionStatus | str) -> None:
    """Raise `VersionLocked` unless this version's content may still change (FR-022).

    Takes the status rather than the version, for the reason `ensure_exportable` takes
    it: the rule is about one field, and a function handed the whole row would invite
    reading others and grow into the use case that should be calling it.

    **Accepts a plain `str`, and the coercion is load-bearing.** `ResumeVersion.status`
    is a `String` column, so a row loaded in a session that did not create it comes back
    as `str`. Membership and `==` survive that because `VersionStatus` is a `StrEnum`;
    **`.value` does not**, and the messages below use it. That exact defect shipped in
    `ensure_exportable` and was found by the first real request rather than by its tests.
    """
    status = VersionStatus(status)

    if status not in LOCKED_STATUSES:
        return

    if status == VersionStatus.SUBMITTED:
        raise VersionLocked(
            "This version has been submitted and can no longer be changed. What was sent "
            "to an employer is a permanent record; tailor this job again to work on a new "
            "version."
        )

    raise VersionLocked(
        f"This version is {status.value} and can no longer be changed — a PDF of it "
        "already exists, and editing it would make that document disagree with its "
        "record. Tailor this job again to work on a new version."
    )


__all__ = ["LOCKED_STATUSES", "VersionLocked", "ensure_version_mutable"]
