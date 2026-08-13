"""Professional content — written only when an import is approved.

Every entity here carries `source`, because FR-004 requires user-verified facts
to stay distinguishable from unverified extraction *after* approval. Discarding
provenance at the approval boundary would make the profile a flat set of claims
with no record of which ones a human actually looked at.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.domain.models.provenance import Source
from careerhq.infrastructure.database import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _profile_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("professional_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _source() -> Mapped[Source]:
    return mapped_column(String(16), nullable=False, default=Source.EXTRACTED)


class ContactInformation(Base):
    __tablename__ = "contact_information"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(255))
    links: Mapped[str | None] = mapped_column(Text)
    source: Mapped[Source] = _source()


class ProfessionalTitle(Base):
    __tablename__ = "professional_titles"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[Source] = _source()


class SummaryBlock(Base):
    __tablename__ = "summary_blocks"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Source] = _source()


class WorkExperience(Base):
    __tablename__ = "work_experiences"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    #: Kept as the text the CV used. Parsing "March 2021 - Present" into a date
    #: means inventing precision and occasionally the wrong month.
    start_date: Mapped[str | None] = mapped_column(String(64))
    end_date: Mapped[str | None] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[Source] = _source()

    bullets: Mapped[list[ExperienceBullet]] = relationship(
        back_populates="experience",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExperienceBullet.ordinal",
    )


class ExperienceBullet(Base):
    """One achievement, as its own row.

    Separate from the role because slice 004 tailors, diffs and approves at
    bullet granularity — Principle II's item-level approval is not expressible
    over a text blob.
    """

    __tablename__ = "experience_bullets"

    id: Mapped[uuid.UUID] = _pk()
    experience_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("work_experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[Source] = _source()

    experience: Mapped[WorkExperience] = relationship(back_populates="bullets")


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[Source] = _source()


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1024))
    source: Mapped[Source] = _source()


class Education(Base):
    __tablename__ = "education"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    qualification: Mapped[str | None] = mapped_column(String(255))
    field_of_study: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[str | None] = mapped_column(String(64))
    end_date: Mapped[str | None] = mapped_column(String(64))
    grade: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[Source] = _source()


class Certification(Base):
    __tablename__ = "certifications"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(255))
    year: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[Source] = _source()


class Language(Base):
    __tablename__ = "languages"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[Source] = _source()


class ResumeProfile(Base):
    """A career-focused view over the profile — the "Master Resume".

    References profile facts rather than duplicating them (Principle I,
    docs/03 §4.3). Constraint **C4** — a partial unique index on `profile_id`
    where `is_master` — is what makes a double-clicked approve unable to produce
    two of them (SC-004). An application-level check could be raced by exactly
    the double-click it is meant to stop.
    """

    __tablename__ = "resume_profiles"
    __table_args__ = (
        Index(
            "uq_resume_profiles_one_master_per_profile",
            "profile_id",
            unique=True,
            postgresql_where=text("is_master"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_master: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MilitaryService(Base):
    """Military service — not employment.

    Separate from `WorkExperience` because conflating them makes the profile
    assert something untrue, and because a tailoring agent reasoning about
    career progression should not read a conscript posting as a job move.
    """

    __tablename__ = "military_service"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[str | None] = mapped_column(String(64))
    end_date: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[str | None] = mapped_column(Text)
    source: Mapped[Source] = _source()


class VolunteerExperience(Base):
    __tablename__ = "volunteer_experiences"

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = _profile_fk()
    organisation: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[str | None] = mapped_column(String(64))
    end_date: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[Source] = _source()
