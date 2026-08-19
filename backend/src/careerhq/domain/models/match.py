"""Match analysis — how well one profile fits one job (data-model.md).

Two tables, one row per run and one row per requirement, plus the constraint
that makes AI-008 true of the data rather than true of the code that usually
writes it.

**Append-only.** A re-run inserts; it never updates a finished analysis. Slice
004's calibration is measured over history, and Constitution IV governs. The
single legitimate update is `pending -> ready|failed`, which completes a row
rather than rewriting one.

**Two absences worth naming**, in the manner of `application.py`:

* **There is no `is_stale` column.** Staleness is a comparison between the
  profile's `updated_at` and the analysis's `created_at`, computed at read time.
  Stored, it would be a second source of truth that goes wrong the moment a
  profile is edited without every analysis being visited.
* **There is no `overall_score` returned by the model.** The model rates four
  dimensions and the application computes the total (`match_criteria.py`).
  Asking for the parts and the total invites them to disagree, and the total is
  the one a person acts on.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.infrastructure.database import Base


class MatchStatus(enum.StrEnum):
    """Where one run got to.

    `pending` is written in the same transaction as the application, before any
    provider call. That is what makes a background run visible rather than
    mysterious: the interface has something to show a spinner against, and a
    failure has somewhere to record itself instead of leaving a blank forever.
    """

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class MatchBand(enum.StrEnum):
    """What the person is shown, in place of a bare percentage.

    A score of 84 claims a precision this method does not have. A band does not,
    while still separating "worth the evening" from "probably not". The number
    is kept beside it for sorting and for the Match Score calibration docs/07
    §3.2 evaluates this capability on — there is nothing to calibrate if no
    number is retained (research.md R9/D2).
    """

    STRONG = "strong"
    MODERATE = "moderate"
    STRETCH = "stretch"
    LOW_PROBABILITY = "low_probability"


class RequirementKind(enum.StrEnum):
    """Whether the posting stated this as required or preferred."""

    MUST_HAVE = "must_have"
    PREFERRED = "preferred"


class RequirementVerdict(enum.StrEnum):
    """How the profile answers one requirement.

    Five rather than three, and the last two are the reason.

    `gap` and `unverified` are different claims. *The profile shows you fall
    short of this* is supportable; *the profile does not mention this, therefore
    you lack it* is not. An earlier draft had a single evidence-free `missing`
    verdict, which let a silent profile become a confident "you do not have
    this" — inventing a negative fact about the person. AI-008 forbids inventing
    experience the profile lacks; that is the same fabrication pointed the other
    way (research.md R9/D1).

    `transferable` is separated from `confirmed` for the same reason one step
    removed: presenting adjacent experience as direct experience is a claim the
    profile does not support either.
    """

    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    TRANSFERABLE = "transferable"
    GAP = "gap"
    UNVERIFIED = "unverified"


class Shortfall(enum.StrEnum):
    """Why a requirement is not met, which decides what to do about it.

    Rephrase what is already there, supply the proof, or acknowledge the gap. A
    list of unmet requirements that does not say which is a list of problems
    with no next step.
    """

    WORDING = "wording"
    EVIDENCE = "evidence"
    CAPABILITY = "capability"


class MatchAnalysis(Base):
    """One scoring run. Insert-only once finished.

    Model metadata is written in the same transaction as the result
    (Constitution V, FR-017), exactly as the CV import does — infrastructure
    returns usage, the application layer records it where the data lands.
    """

    __tablename__ = "match_analyses"

    __table_args__ = (
        # FR-007. At most one run in flight per application, enforced where it
        # cannot be raced. An application-level check loses to two clicks.
        Index(
            "uq_match_analysis_one_pending_per_application",
            "application_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[MatchStatus] = mapped_column(String(16), nullable=False)
    #: Set only when `failed`, and shown to the person. The driver's own text
    #: goes to the log, not here — slice 002's rule about unauthenticated
    #: disclosure applies to anything a browser renders.
    error: Mapped[str | None] = mapped_column(Text)

    #: Retained for sorting and calibration; never rendered as a bare
    #: percentage (FR-001a).
    overall_score: Mapped[int | None] = mapped_column(SmallInteger)
    band: Mapped[MatchBand | None] = mapped_column(String(16))
    verdict: Mapped[str | None] = mapped_column(Text)

    #: Which rubric produced this. NOT NULL from the first insert: nullable
    #: would make a forgotten value indistinguishable from a deliberate one, and
    #: a calibration measurement across scores from different unnamed criteria
    #: measures nothing (FR-018).
    criteria_version: Mapped[str] = mapped_column(String(64), nullable=False)

    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    #: Decimal, never float. A per-call cost accumulated over thousands of runs
    #: in binary floating point drifts, and this is an audit record.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    #: True only from the fixture adapter. Canned content mistaken for a real
    #: analysis would mean acting on a score nothing produced.
    is_fixture: Mapped[bool] = mapped_column(nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requirements: Mapped[list[MatchRequirement]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="MatchRequirement.ordinal",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<MatchAnalysis {self.id} {self.status} {self.overall_score}>"


class MatchRequirement(Base):
    """One requirement, and how the profile answers it.

    Rows rather than a JSON blob because slice 007's Career Advisor counts how
    often each skill is required and separates critical gaps from nice-to-haves
    (docs/07 §3.5). As rows that is a `GROUP BY`; as JSON it is unqueryable and
    would have to be re-extracted from analyses already paid for.
    """

    __tablename__ = "match_requirements"

    __table_args__ = (
        # AI-008, in the last place it can be enforced.
        #
        # Read it as an equivalence in both directions. Every verdict except
        # `unverified` must quote the profile — **including `gap`**, which has
        # to point at the text showing the shortfall. A model that cannot quote
        # anything does not get to say the person falls short; the honest answer
        # is `unverified`, which is the sole evidence-free verdict precisely
        # because it is the only one asserting nothing.
        #
        # The Pydantic validator rejects this earlier and more legibly. This is
        # what makes it true of the table whatever writes to it.
        CheckConstraint(
            "(verdict = 'unverified') = (evidence IS NULL)",
            name="ck_match_requirement_grounded",
        ),
        # A shortfall is meaningless on something the profile confirms.
        CheckConstraint(
            "(verdict = 'confirmed') = (shortfall IS NULL)",
            name="ck_match_requirement_shortfall",
        ),
        CheckConstraint(
            "importance >= 0 AND importance <= 100",
            name="ck_match_requirement_importance",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("match_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Presentation order, as the posting stated them.
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: Worded as the posting worded it. A paraphrase makes the coverage count
    #: incomparable between runs and slice 007's frequency counting meaningless.
    text_: Mapped[str] = mapped_column("text", Text, nullable=False)

    #: What the posting said. Preserved because it is the employer's own words.
    kind: Mapped[RequirementKind] = mapped_column(String(16), nullable=False)

    #: What the model judged it is worth, 0-100. This is what the band rule
    #: reads; `kind` is not. A posting's "must have" heading is routinely a
    #: wishlist, and if every stated requirement capped the band, every job
    #: would read `stretch` and the band would stop discriminating.
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")

    verdict: Mapped[RequirementVerdict] = mapped_column(String(16), nullable=False)
    shortfall: Mapped[Shortfall | None] = mapped_column(String(16))

    #: Quoted from the profile. The grounding mechanism, not a nicety: it is
    #: what lets a chip be clicked to see why, and what makes the constraint
    #: above enforceable.
    evidence: Mapped[str | None] = mapped_column(Text)

    analysis: Mapped[MatchAnalysis] = relationship(back_populates="requirements")

    def __repr__(self) -> str:
        return f"<MatchRequirement {self.ordinal} {self.verdict}>"


__all__ = [
    "MatchAnalysis",
    "MatchBand",
    "MatchRequirement",
    "MatchStatus",
    "RequirementKind",
    "RequirementVerdict",
    "Shortfall",
]
