"""Applications — the jobs a user is pursuing (data-model.md §3).

Three entities and one pure function. The function matters as much as the
tables: `normalize_status` is the *only* way a normalized status is produced,
which is what makes FR-013's "derived, never supplied" enforceable rather than
aspirational.

Two absences are deliberate and load-bearing:

* **There is no `rejected` column.** Rejection is a value of `normalized_status`
  (FR-016, docs/03 §14). A boolean beside it is a second source of truth for the
  same fact, and the two drift the first time one is written without the other.
  `tests/integration/test_applications.py` asserts the absence against
  `information_schema`, because nothing breaks when it grows back.
* **There is no `submitted_resume_id`.** Submitted Resumes arrive in slice 004,
  and an application in a pre-submission status must be valid without one
  (FR-011).
"""

from __future__ import annotations

import enum
import re
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.infrastructure.database import Base


class NormalizedStatus(enum.StrEnum):
    """The analytics category the Career Advisor reasons over (FR-013).

    The user's own label is preserved verbatim beside this. The label is what
    they call it; this is what the system counts.
    """

    WISHLIST = "wishlist"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    GHOSTED = "ghosted"
    OTHER = "other"


#: Labels this system recognises, keyed by their folded form (data-model.md §3).
#: Sourced from JobTracker's own vocabulary so an import lands in the right
#: category without a mapping table maintained separately from this one.
_STATUS_VOCABULARY: dict[str, NormalizedStatus] = {
    "pre applied": NormalizedStatus.WISHLIST,
    "wishlist": NormalizedStatus.WISHLIST,
    "saved": NormalizedStatus.WISHLIST,
    "applied": NormalizedStatus.APPLIED,
    "online assessment": NormalizedStatus.INTERVIEWING,
    "phone screen": NormalizedStatus.INTERVIEWING,
    "interview round 1": NormalizedStatus.INTERVIEWING,
    "interview round 2": NormalizedStatus.INTERVIEWING,
    "interview round 3": NormalizedStatus.INTERVIEWING,
    "final interview": NormalizedStatus.INTERVIEWING,
    "offer received": NormalizedStatus.OFFER,
    "offer": NormalizedStatus.OFFER,
    "rejected": NormalizedStatus.REJECTED,
    "withdrawn": NormalizedStatus.WITHDRAWN,
    "ghosted": NormalizedStatus.GHOSTED,
}


def _fold(value: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    So `Pre-Applied`, `pre applied` and `Pre — Applied` are one key. Matching on
    the raw string would make the vocabulary depend on which dash someone typed.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", value.casefold())).strip()


def normalize_status(label: str) -> NormalizedStatus:
    """Derive the analytics category from the user's label (FR-013).

    An unrecognised label normalizes to `OTHER` and is **preserved verbatim** —
    it does not reject the row. That is the common case rather than the exotic
    one: JobTracker keeps custom statuses in `localStorage`, so they never reach
    an export at all (R8, Finding 3). FR-018's "cannot be mapped" is about rows
    missing something structural, like a company or a title.
    """
    return _STATUS_VOCABULARY.get(_fold(label), NormalizedStatus.OTHER)


def normalize_company_name(name: str) -> str:
    """The dedup key for C2.

    Folded the same way as a status label, so `Acme Corporation`, `  acme
    corporation.` and `ACME Corporation` resolve to one company. Casing and a
    trailing full stop are typing, not a different employer.
    """
    return _fold(name)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _user_fk() -> Mapped[uuid.UUID]:
    """FR-019, constraint C5. Owned rows are unrepresentable without an owner."""
    return mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Company(Base):
    """An employer, as one user records them.

    Per user, not global (C2's scope). Two users naming the same employer own
    separate rows: these carry the user's own notes and contacts, so sharing
    them across accounts would leak one person's research into another's.
    """

    __tablename__ = "companies"
    __table_args__ = (
        # C2 — FR-014. A UNIQUE constraint rather than a read-then-write check,
        # which is also what makes import dedup correct under concurrent retry.
        UniqueConstraint("user_id", "normalized_name", name="uq_companies_user_normalized_name"),
    )

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()

    #: As the user entered it — this is what the interface shows.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The dedup key. Derived by `normalize_company_name`, never typed.
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)

    domain: Mapped[str | None] = mapped_column(String(255))
    careers_url: Mapped[str | None] = mapped_column(String(1024))
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Company {self.id} {self.name!r}>"


class Application(Base):
    """One job the user is pursuing."""

    __tablename__ = "applications"
    __table_args__ = (
        # C3 — FR-017. Partial, because manual entries have no import identity
        # and NULLs would otherwise never conflict *or* be constrained. Re-running
        # an import conflicts here and the database refuses; an application-level
        # check must read-then-write and can be raced.
        Index(
            "uq_applications_import_identity",
            "user_id",
            "import_source",
            "import_source_id",
            unique=True,
            postgresql_where=text("import_source IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))

    #: The text slice 004 tailors against — the reason User Story 2 exists.
    #: NULL for every imported application: JobTracker has no description field,
    #: only URLs (R8, Finding 2).
    job_description: Mapped[str | None] = mapped_column(Text)
    job_url: Mapped[str | None] = mapped_column(String(2048))
    job_description_url: Mapped[str | None] = mapped_column(String(2048))

    #: What the posting asks of the candidate, beside the posting rather than in
    #: place of it (slice 004, research.md R1).
    #:
    #: **NULL and `{}` are different facts and must stay so.** `{}` means the
    #: posting was read and stated no requirements. NULL means no posting was
    #: ever captured — true of every row written before slice 004, whose
    #: `job_description` holds a joined requirements list rather than an advert.
    #: Those rows are never scored: the prompt would claim to read a whole
    #: posting while receiving a requirements list, and the resulting number
    #: would look entirely normal. This column is the only thing telling them
    #: apart, which is why it is not backfilled with an empty array.
    requirements: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    #: The analysis to display. One join for the table rather than one query per
    #: row, with history preserved behind it.
    #:
    #: **Advances only when an analysis reaches `ready`** (FR-015). On a re-run
    #: it keeps pointing at the previous good row until the new one succeeds, so
    #: the score does not blank out mid-run and a failed re-run leaves the last
    #: good score standing rather than destroying it.
    #: `use_alter` because this closes a cycle — an application points at its
    #: current analysis and every analysis points back at its application — so
    #: the constraint is added after both tables exist. It must be **named**:
    #: an unnamed altered constraint cannot be dropped, which breaks
    #: `drop_all` and therefore every test that needs a clean schema.
    current_match_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "match_analyses.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_applications_current_match_analysis_id",
        ),
    )

    #: The user's own words, preserved verbatim.
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Derived from `status` by `normalize_status`. Never accepted from a request.
    normalized_status: Mapped[NormalizedStatus] = mapped_column(String(16), nullable=False)

    date_added: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    date_applied: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[str | None] = mapped_column(String(128))

    #: **Free text**, not min/max/currency. The source stores "90-110k",
    #: "competitive" and "" interchangeably (R8); parsing that into numbers
    #: would invent precision the data does not have.
    salary_text: Mapped[str | None] = mapped_column(String(255))

    #: Preserved from JobTracker so slice 004's MatchAnalysis builds on real
    #: ratings rather than discarding them on import. 0 means unset.
    imported_match_rating: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)

    #: Provenance for idempotency (C3). NULL for manual entries.
    import_source: Mapped[str | None] = mapped_column(String(64))
    import_source_id: Mapped[str | None] = mapped_column(String(255))

    #: History survives archiving — this hides a row, it does not erase one.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    company: Mapped[Company] = relationship(lazy="selectin")
    status_history: Mapped[list[ApplicationStatusHistory]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationStatusHistory.changed_at",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Application {self.id} {self.job_title!r} {self.status}>"


class ApplicationStatusHistory(Base):
    """Every status move, in order. Insert-only (Constitution IV, FR-012, C6).

    The timeline is the record and the application's current status is a
    projection of it. Nothing in the codebase may UPDATE or DELETE here — there
    is no endpoint, no use case, and a test in
    `tests/integration/test_applications.py` scans the source tree for one,
    because an append-only table stays append-only only while nothing can write
    to it another way.

    A trigger remains available if this ever needs enforcing against direct SQL
    as well; the constraint today is that no code path exists.
    """

    __tablename__ = "application_status_history"

    id: Mapped[uuid.UUID] = _pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: NULL on the row written at creation — there was no previous status.
    from_status: Mapped[str | None] = mapped_column(String(64))
    to_status: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_to_status: Mapped[NormalizedStatus] = mapped_column(String(16), nullable=False)

    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)

    application: Mapped[Application] = relationship(back_populates="status_history")

    def __repr__(self) -> str:
        return f"<ApplicationStatusHistory {self.from_status} -> {self.to_status}>"


__all__ = [
    "Application",
    "ApplicationStatusHistory",
    "Company",
    "NormalizedStatus",
    "normalize_company_name",
    "normalize_status",
]
