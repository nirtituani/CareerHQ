"""T033 — FR-016: export is refused for a version that has not been approved.

**"Approved" is `READY`.** `data-model.md` calls the state `APPROVED`; the model has
called it `ready` since migration `0010`, and T005 kept the value rather than rewriting
the rows that are this project's only paid evaluation evidence. The contract's
precondition line still says `APPROVED` and means this.

**Two spec artefacts disagreed about re-export, and the guard follows the one that is
already in the schema.** `contracts/export.md` says the precondition is *"the version is
APPROVED"*, and FR-019 moves it to `EXPORTED` — so a literal reading makes a second
export impossible. But `ExportedDocument`'s docstring, merged at T005, says the opposite
and shaped the schema: *"Not unique on `resume_version_id`, deliberately. Re-exporting an
approved version is legitimate — a download that failed, a second copy."* A READY-only
guard would refuse the action that docstring exists to permit and make the missing unique
constraint pointless.

FR-016 asks whether a version **has been approved**, not what its status literal is now,
and an `EXPORTED` version has been. So: `READY` and `EXPORTED` may export.

**`SUBMITTED` may not, and that is the model's rule rather than a preference.** Export
sets the status to `EXPORTED` (FR-019), and `SUBMITTED` is terminal — *"No transition
leaves it"* — so exporting a submitted version would move it out of a state nothing may
leave. FR-022 requires that refusal to be explicit.

**The refusal must be distinguishable from a rendering failure.** "Your resume could not
be exported" reads identically whether the version was not approved or WeasyPrint fell
over, and only one of those is the user's to fix.
"""

from __future__ import annotations

import pathlib

import pytest

from careerhq.application.export import EXPORTABLE_STATUSES, ExportRefused, ensure_exportable
from careerhq.domain.models import VersionStatus

#: Every state that is not exportable, named individually rather than derived, so adding
#: a status to the enum cannot silently join either set.
_REFUSED = (
    VersionStatus.DRAFT,
    VersionStatus.TAILORING,
    VersionStatus.REVIEWING,
    VersionStatus.AWAITING_APPROVAL,
    VersionStatus.SUBMITTED,
)


@pytest.mark.parametrize("status", _REFUSED)
def test_export_is_refused_for_a_version_that_has_not_been_approved(
    status: VersionStatus,
) -> None:
    """FR-016, over the states that actually exist in the domain."""
    with pytest.raises(ExportRefused) as exc_info:
        ensure_exportable(status)

    assert status.value in str(exc_info.value), (
        "the refusal does not name the state it refused, so the caller cannot say why"
    )


def test_an_approved_version_is_exportable() -> None:
    """The positive case, without which the guard could refuse everything and pass."""
    ensure_exportable(VersionStatus.READY)


def test_an_already_exported_version_may_be_exported_again() -> None:
    """`ExportedDocument` has no unique constraint on the version precisely for this.

    A download that failed, or a second copy: FR-031's byte-determinism means the repeat
    produces identical bytes and an identical checksum, so the honest record is that the
    export happened twice. A `READY`-only guard would make that unreachable.
    """
    ensure_exportable(VersionStatus.EXPORTED)


def test_a_submitted_version_is_refused_and_says_so_distinctly() -> None:
    """`SUBMITTED` is terminal, and export would move the version out of it."""
    with pytest.raises(ExportRefused) as exc_info:
        ensure_exportable(VersionStatus.SUBMITTED)

    message = str(exc_info.value)
    assert "submitted" in message.lower()

    # **The sharp assertion, and the first version of this test did not have it.** It
    # checked only that the message mentioned "submitted", which the *generic* refusal
    # also does — it interpolates `status.value`. So the drill that deleted the
    # submitted-specific branch passed. The real defect in the generic wording is that it
    # tells a submitted version it "has not been approved", which is false: it was
    # approved, exported and sent. That is what must not be said.
    assert "has not been approved" not in message, (
        "a submitted version is told it was never approved; it was approved, exported "
        "and sent, and the reason it cannot be exported again is that it is terminal"
    )
    assert message != str(_refusal_for(VersionStatus.DRAFT))


def _refusal_for(status: VersionStatus) -> ExportRefused:
    with pytest.raises(ExportRefused) as exc_info:
        ensure_exportable(status)
    return exc_info.value


def test_every_status_is_classified_exactly_once() -> None:
    """**The gate that survives a new status.**

    A value added to `VersionStatus` later is otherwise silently refused by the guard's
    default branch, with nobody deciding whether it should have been. This forces the
    decision at the moment the enum changes.
    """
    classified = set(EXPORTABLE_STATUSES) | set(_REFUSED)

    assert set(VersionStatus) == classified, (
        f"unclassified statuses: {sorted(s.value for s in set(VersionStatus) - classified)}"
    )
    assert not set(EXPORTABLE_STATUSES) & set(_REFUSED), "a status is both exportable and refused"
    assert len(classified) == 7, f"expected the 7 known statuses, examined {len(classified)}"


def test_the_refusal_is_not_a_rendering_or_infrastructure_failure() -> None:
    """FR-022's "refused explicitly" is about being *distinguishable*, not just raising.

    Asserted structurally as well as by type: the precondition module imports no renderer,
    so a refusal cannot have rendered anything first and cannot be confused with a render
    error. That is FR-016's "refused **before** rendering" made checkable.
    """
    import careerhq.application.export as export_module

    assert issubclass(ExportRefused, Exception)
    assert not issubclass(ExportRefused, OSError), (
        "ExportRefused inherits from OSError and would be caught by handlers meant for "
        "storage and rendering failures"
    )

    source = pathlib.Path(export_module.__file__).read_text()
    for forbidden in ("weasyprint", "render_resume_pdf", "infrastructure.documents"):
        assert forbidden not in source, (
            f"the export precondition imports {forbidden!r}; a guard that can render is a "
            "guard that might render before refusing"
        )


@pytest.mark.parametrize("status", [*_REFUSED, VersionStatus.READY, VersionStatus.EXPORTED])
def test_the_guard_accepts_the_plain_string_a_loaded_row_actually_carries(
    status: VersionStatus,
) -> None:
    """**Found by T037's first real request, not by these tests.**

    `ResumeVersion.status` is a `String` column, so a row loaded in a session that did not
    create it comes back as `str`, not as the enum member — the shape every test above
    misses because it constructs the member directly. Membership and `==` survive it
    because `VersionStatus` is a `StrEnum`; `.value` does not, and the refusal message
    used it, so every refusal raised `AttributeError` instead through the route.

    Parametrised over the exportable states too: a coercion that fixed the message while
    breaking the positive path would be worse than the bug.
    """
    plain: str = str(status.value)
    assert type(plain) is str

    if status in EXPORTABLE_STATUSES:
        ensure_exportable(plain)  # must not raise
    else:
        with pytest.raises(ExportRefused) as exc_info:
            ensure_exportable(plain)
        assert plain in str(exc_info.value)
