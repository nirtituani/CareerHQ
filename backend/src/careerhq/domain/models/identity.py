"""Domain models.

Business rules that must always hold are expressed as database constraints
rather than as application checks. A check in Python can be raced, forgotten by
the next endpoint, or bypassed by a migration script; a UNIQUE constraint
cannot.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.infrastructure.database import Base


class User(Base):
    """A person who signs in to CareerHQ. Owns all of their data."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # Identity is the Google subject, not the email. A Google account can change
    # its email address; keying on email would split one person into two
    # accounts and orphan their history.
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    profile: Mapped[ProfessionalProfile] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"


class ProfessionalProfile(Base):
    """The user's single container of professional knowledge.

    Empty in this slice; later slices populate it. Constitution Principle I —
    exactly one per user — is enforced by the UNIQUE constraint on ``user_id``,
    which is also what makes concurrent first sign-in safe.
    """

    __tablename__ = "professional_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="profile")

    def __repr__(self) -> str:
        return f"<ProfessionalProfile {self.id} user={self.user_id}>"
