"""Staging: content that is not yet profile data.

The entire point of these two tables is that they are **not** the profile.
Extraction writes here; approval copies accepted items into the profile in one
transaction. An import that is abandoned leaves the profile untouched (FR-007),
which is only true because the staged rows live somewhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.domain.models.provenance import ImportStatus, ItemDecision, Source
from careerhq.infrastructure.database import Base


class ImportedResume(Base):
    """One uploaded CV and its extraction attempt."""

    __tablename__ = "imported_resumes"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Object-storage key for the retained original (FR-006). Deliberately read
    #: by one module only — asserted by a test, because "the uploaded file is
    #: never a source of truth" is a claim about what does *not* read it.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[ImportStatus] = mapped_column(
        String(16), nullable=False, default=ImportStatus.PENDING
    )
    #: Set when extraction failed or produced nothing usable (FR-008).
    extraction_error: Mapped[str | None] = mapped_column(Text)

    # -- Principle V's audit record (FR-026) --------------------------------
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    #: Numeric, not float. Accumulated over thousands of extractions, binary
    #: floating point drifts — and this is an audit record, not a display value.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))

    #: True when produced by fixture mode, so canned content can never be
    #: mistaken for a real extraction (research R3).
    is_fixture: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[ExtractionItem]] = relationship(
        back_populates="imported_resume",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExtractionItem.ordinal",
    )

    def __repr__(self) -> str:
        return f"<ImportedResume {self.id} {self.status}>"


class ExtractionItem(Base):
    """One extracted fact, with its provenance and the reviewer's decision."""

    __tablename__ = "extraction_items"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_extraction_confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    imported_resume_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("imported_resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Which profile entity this becomes — `work_experience`, `bullet`, `skill`…
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The structured value, already validated against the extraction schema
    #: before it was stored (FR-025).
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    confidence: Mapped[float] = mapped_column(nullable=False, server_default=text("0.5"))
    source: Mapped[Source] = mapped_column(String(16), nullable=False, default=Source.EXTRACTED)
    decision: Mapped[ItemDecision] = mapped_column(
        String(16), nullable=False, default=ItemDecision.PENDING
    )

    #: Preserves CV order, so review reads like the source document.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Set for bullets, pointing at the role item they belong to.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("extraction_items.id", ondelete="CASCADE")
    )

    imported_resume: Mapped[ImportedResume] = relationship(back_populates="items")

    #: Self-referential: a bullet points at the role it belongs to. Set as an
    #: object during staging so SQLAlchemy resolves the foreign key on flush,
    #: which avoids a second round trip just to learn the parent's id.
    parent: Mapped[ExtractionItem | None] = relationship(remote_side=[id])

    def __repr__(self) -> str:
        return f"<ExtractionItem {self.kind} {self.decision}>"
