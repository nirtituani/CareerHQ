"""Turning a job posting into form fields.

Nothing here saves anything. The result is handed back to the interface, which
fills the Add Application form and waits for the person to confirm it — the same
shape as the CV import, and for the same reason: Principle II puts a human
between an extraction and the record it becomes. An endpoint that created the
application directly would be a model writing to the database unreviewed.

**The model is the second choice, not the first.** Where a page publishes
schema.org `JobPosting` data the employer has already written the fields, so
they are read exactly and for nothing. Only a page without it is worth a
completion. On the applicant tracking systems most postings actually live on,
the free path is the one that runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from careerhq.application.ports import StructuredCompletion, Usage
from careerhq.domain.schemas.job import JobPostingExtraction
from careerhq.infrastructure.jobs import (
    JobFetchError,
    fetch_posting,
    html_to_text,
    json_ld_job_posting,
    looks_unrendered,
)
from careerhq.infrastructure.jobs.comeet import (
    fetch_comeet_posting,
    is_comeet_url,
    metadata_from_position,
)

logger = logging.getLogger("careerhq.jobs")

TASK = "job_extraction"

#: Enough of a posting for the model to work with. Beyond this a page is
#: navigation, related jobs and cookie policy — sending it costs tokens and
#: dilutes the part that matters.
MAX_PROMPT_CHARS = 24_000

#: Below this a "successful" fetch returned a cookie wall or a JS shell rather
#: than a posting. Sending it to the model would spend a call to be told
#: nothing, so it is treated as the fetch failure it actually is.
MIN_USABLE_CHARS = 200


class JobMetadata(BaseModel):
    """The short fields the model is asked for — and **not** the description.

    Reproducing the description would mean thousands of output tokens, and
    output is the slow half of a completion: a real Greenhouse posting took
    **52 seconds** that way. The description is already in the text that was
    stripped from the page, so copying it through the model buys nothing and
    costs both the wait and the tokens.

    Every field here is a phrase, which keeps the completion small and quick.
    """

    company: str | None = Field(default=None, description="The hiring company's name")
    job_title: str | None = Field(default=None, description="The role title as advertised")
    location: str | None = Field(default=None, description="Where the role is based")
    salary_text: str | None = Field(default=None, description="Pay as written, verbatim")
    company_domain: str | None = Field(default=None, description="The employer's domain")

    #: The only long field the model returns, and deliberately a **list** —
    #: asking for prose would invite it to rewrite what it read, while a line
    #: per requirement is copied rather than composed.
    requirements: list[str] = Field(
        default_factory=list, description="What the posting asks of the candidate, one per line"
    )


_PROMPT = """Read this job posting and identify its details.

Rules:
- Copy what the posting says. Do not infer, improve, or fill gaps.
- `salary_text` is whatever the posting says about pay, word for word
  ("competitive", "90-110k", "DOE"). Never a number you worked out yourself.
- `requirements` is what the posting asks *of the candidate* — the
  requirements, qualifications, "what we look for", "must have" and
  "nice to have" lines. Copy each one as its own line, worded as written.
- Leave out of `requirements`: the company blurb, what the role involves
  day to day, benefits, equal-opportunity statements, and how to apply.
- If the posting states no requirements, return an empty list rather than
  inventing some from the responsibilities.

Posting:
---
{text}
---"""

#: How the fields were obtained. Shown to the user, because "the employer
#: published this" and "a model read the page" deserve different trust, and
#: because a field they must check is different from one they need not.
Provenance = Literal["structured_data", "model", "manual"]


@dataclass(frozen=True, slots=True)
class JobExtraction:
    """Extracted fields, how they were obtained, and what it cost."""

    posting: JobPostingExtraction
    provenance: Provenance
    #: None on the structured-data path — there was no completion to bill.
    usage: Usage | None = None


async def extract_job_from_text(text: str, *, completion: StructuredCompletion) -> JobExtraction:
    """Extract from posting text the user pasted, or that we stripped.

    The model supplies the short fields; the **description is the text itself**,
    which is both faster and more faithful — nothing is paraphrased away, and
    the person can edit it in the form before saving.
    """
    body = text.strip()[:MAX_PROMPT_CHARS]

    result = await completion.complete(
        task=TASK,
        schema=JobMetadata,
        prompt=_PROMPT.format(text=body),
    )

    fields = result.value.model_dump()
    requirements = fields.pop("requirements", [])

    # **Requirements only** — the user's decision, recorded here because it has
    # a consequence worth seeing at the point of impact: slice 004 tailors
    # against whatever is stored, so responsibilities ("led a team of six") are
    # no longer available to match a CV bullet against, and the original posting
    # may have expired by the time anyone wants it back.
    #
    # Falls back to the full text when the model found no requirements, because
    # an application with an empty description cannot be tailored against at all
    # — worse than one carrying more than it needs.
    posting = JobPostingExtraction(
        **fields,
        job_description="\n".join(requirements) if requirements else body,
    )

    logger.info(
        "job extracted from text",
        extra={
            "model": result.usage.model,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cost": str(result.usage.cost),
        },
    )
    return JobExtraction(posting=posting, provenance="model", usage=result.usage)


async def extract_job_from_url(url: str, *, completion: StructuredCompletion) -> JobExtraction:
    """Fetch a posting and extract it. Raises `JobFetchError` if unreachable.

    The caller turns that exception into an offer to paste the text instead,
    which is the path most large job boards force: they refuse automated
    requests outright, and no amount of retrying changes that.
    """
    html = await fetch_posting(url)
    vendor_metadata: dict[str, str] = {}

    if is_comeet_url(url):
        # Comeet draws its pages in the browser, so the fetched shell holds no
        # posting at all. Its own API supplies the metadata and points at the
        # employer's rendered page for the body.
        position, body_url = await fetch_comeet_posting(url, html)
        vendor_metadata = metadata_from_position(position)
        if body_url:
            html = await fetch_posting(body_url)

    text = html_to_text(html)

    if looks_unrendered(text):
        # The page shipped its template. There is nothing here to read, and
        # sending it would bill a completion to extract `{{position.name}}`.
        raise JobFetchError(
            "This page builds its content in the browser, so there is nothing "
            "to read from the address alone. Paste the posting text instead."
        )

    if len(text) < MIN_USABLE_CHARS:
        raise JobFetchError(
            "That page did not contain a readable posting — it may need a "
            "sign-in or JavaScript. Paste the posting text instead."
        )

    extraction = await extract_job_from_text(text, completion=completion)

    if vendor_metadata:
        # The vendor stated these outright, so they beat a model reading a page
        # that also carries the employer's site navigation.
        #
        # This is the **floor**, not the last word: the employer's own JSON-LD
        # is applied after it below and wins, because a company describing
        # itself on its own careers page beats the applicant tracking system's
        # record of it. On a real posting that was the difference between
        # "DriveNets" and the ATS's all-caps "DRIVENETS".
        extraction = JobExtraction(
            posting=extraction.posting.model_copy(update=vendor_metadata),
            provenance="structured_data",
            usage=extraction.usage,
        )

    # Structured data is **metadata only**, and is overlaid rather than
    # returned on its own.
    #
    # Returning early on it looked like a free win and was a bug twice over. On
    # a real posting the page's `JobPosting` block carried 1,591 characters of
    # company blurb while the page itself held 9,447 including the actual
    # requirements — so the "exact" path returned *less* than reading the page —
    # and it skipped the requirements narrowing entirely, handing back a
    # description beginning "Company Overview:".
    #
    # Where the employer did state a field, though, that still beats a model
    # inferring it, so those fields win.
    structured = json_ld_job_posting(html)
    if structured is None:
        return extraction

    metadata = {
        field: value
        for field, value in structured.model_dump().items()
        # The body is never taken from here — that is the whole lesson above.
        if field != "job_description" and value
    }
    logger.info("structured metadata overlaid", extra={"url": url, "fields": sorted(metadata)})

    return JobExtraction(
        posting=extraction.posting.model_copy(update=metadata),
        provenance="structured_data" if metadata else extraction.provenance,
        usage=extraction.usage,
    )


__all__ = [
    "MAX_PROMPT_CHARS",
    "MIN_USABLE_CHARS",
    "TASK",
    "JobExtraction",
    "Provenance",
    "extract_job_from_text",
    "extract_job_from_url",
]
