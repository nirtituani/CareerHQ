"""What a job posting yields, however it was read.

One schema for both paths — schema.org `JobPosting` data parsed from the page,
and a model reading the text — so the caller cannot tell them apart by shape and
the form is populated the same way either way. Which path produced it travels
separately, as provenance, because the user is told.

Every field is optional. A posting that names no salary is ordinary, and a
schema that demanded one would turn a good extraction into a failure. What
cannot be extracted is left empty for the person to fill, which is the same rule
the CV extraction follows.

**There is no `date_applied` here, and there cannot be.** A posting carries its
own publication date; it has no idea when *you* applied. Taking one for the
other would file a wrong date silently, and a wrong date is worse than an absent
one for anything reasoning over a timeline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobPostingExtraction(BaseModel):
    """The fields the Add Application form can be filled from."""

    company: str | None = Field(default=None, description="The hiring company's name")
    job_title: str | None = Field(default=None, description="The role title as advertised")
    location: str | None = Field(default=None, description="Where the role is based")

    #: Free text, never parsed into numbers. Postings say "90-110k",
    #: "competitive" and "DOE" interchangeably, and turning that into a range
    #: would invent precision the posting does not have.
    salary_text: str | None = Field(default=None, description="Salary as written, verbatim")

    #: The reason any of this exists — the text slice 004 tailors against.
    job_description: str | None = Field(
        default=None, description="The full posting text, as plain text"
    )

    #: For the logo column, when the posting names the employer's own site.
    company_domain: str | None = Field(default=None, description="The employer's domain")


__all__ = ["JobPostingExtraction"]
