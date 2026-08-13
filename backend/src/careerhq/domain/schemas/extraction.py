"""What the model must return when reading a CV.

This schema *is* the extraction contract: the seam validates against it, and
output that does not satisfy it is extraction failure rather than partial data
(FR-025, obligation O2). Three decisions in here are load-bearing.

**Bullets are separate items, never a blob of text.** Slice 004 tailors,
reviews and approves at bullet granularity — item-level human approval is
Principle II's mechanism — and a role whose achievements arrive as one string
cannot support that. Splitting them later is guesswork; asking for them split is
free.

**Dates stay as the text the CV used.** CVs write "March 2021 - Present",
"03/2021", "Spring 2021" and "2021-03" interchangeably. Parsing that into a
`date` here would mean inventing precision and occasionally inventing the wrong
month — the same trap as JobTracker's day-first strings (research R8). The user
corrects them in review, where the original is visible next to the value.

**Confidence is per item and self-reported.** It informs the reviewer and orders
the work; it never decides anything (FR-029). Principle II admits no threshold.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class _Extracted(BaseModel):
    """Base for every extracted item: how sure the model was.

    Kept as one shared field rather than repeated, so a new item type cannot be
    added without it — an item with no confidence would be silently treated as
    certain by any interface that sorts on it.
    """

    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class ExtractedContact(_Extracted):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class ExtractedTitle(_Extracted):
    title: str


class ExtractedSummary(_Extracted):
    text: str


class ExtractedBullet(_Extracted):
    """One achievement or responsibility, as written."""

    text: str


class ExtractedRole(_Extracted):
    company: str
    title: str | None = None
    location: str | None = None
    #: As written on the CV. See the module docstring.
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    bullets: list[ExtractedBullet] = Field(default_factory=list)


class ExtractedSkill(_Extracted):
    name: str
    category: str | None = None


class ExtractedProject(_Extracted):
    name: str
    description: str | None = None
    url: str | None = None


class ExtractedEducation(_Extracted):
    institution: str
    qualification: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    grade: str | None = None


class ExtractedCertification(_Extracted):
    name: str
    issuer: str | None = None
    year: str | None = None


class ExtractedLanguage(_Extracted):
    name: str
    proficiency: str | None = None


class ResumeExtraction(BaseModel):
    """Everything recovered from one CV.

    Every collection defaults to empty. A CV with no certifications is ordinary,
    and requiring the model to produce a key it has nothing for invites it to
    invent one — which Principle III forbids outright. An extraction where
    *everything* is empty is the caller's signal to report failure (FR-008), and
    `is_empty` exists so that decision is made in one place rather than
    re-derived by each caller.
    """

    contact: ExtractedContact = Field(default_factory=ExtractedContact)
    titles: list[ExtractedTitle] = Field(default_factory=list)
    summary: ExtractedSummary | None = None
    work_experience: list[ExtractedRole] = Field(default_factory=list)
    skills: list[ExtractedSkill] = Field(default_factory=list)
    projects: list[ExtractedProject] = Field(default_factory=list)
    education: list[ExtractedEducation] = Field(default_factory=list)
    certifications: list[ExtractedCertification] = Field(default_factory=list)
    languages: list[ExtractedLanguage] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Whether nothing usable was recovered.

        Contact details alone do not count: an email address scraped from a
        header is not a career history, and presenting that as a successful
        import would be the empty-review-form failure FR-008 exists to prevent.
        """
        return not any(
            (
                self.titles,
                self.summary,
                self.work_experience,
                self.skills,
                self.projects,
                self.education,
                self.certifications,
                self.languages,
            )
        )

    @property
    def item_count(self) -> int:
        """Reviewable items, for progress display and for the empty check."""
        bullets = sum(len(role.bullets) for role in self.work_experience)
        return (
            len(self.titles)
            + (1 if self.summary else 0)
            + len(self.work_experience)
            + bullets
            + len(self.skills)
            + len(self.projects)
            + len(self.education)
            + len(self.certifications)
            + len(self.languages)
        )


__all__ = [
    "ExtractedBullet",
    "ExtractedCertification",
    "ExtractedContact",
    "ExtractedEducation",
    "ExtractedLanguage",
    "ExtractedProject",
    "ExtractedRole",
    "ExtractedSkill",
    "ExtractedSummary",
    "ExtractedTitle",
    "ResumeExtraction",
]
