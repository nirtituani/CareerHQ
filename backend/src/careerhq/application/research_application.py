"""Role-aware research for one application (slice 010).

Two pure functions, and their purity is the design:

* `context_for` assembles the research input from **the application and its
  company, and nothing else**. The role and posting come from the job
  (FR-002, retiring 008's FR-021); the posting question is answered by
  `scoreable_posting` — the same single answer Match and Tailor use — so
  research cannot grow a private opinion about what counts as a posting
  (FR-003). There is no parameter anything profile-shaped could arrive
  through, and the SC-007 sentinel test asserts the assembled inputs stay
  clean.

* `perform_research` makes the one provider call and owns the fallback
  decision (D8): `ResearchProviderUnavailable` falls back when a fallback was
  configured, because availability is a fact about the provider;
  `ResearchProviderRejected` never does, because bad output is a fact about
  this run — a retry against the same input would repeat it, and a silent
  fallback would hide a provider quality problem behind a pipeline with a
  known wrong-entity risk.

Sessions, snapshots and commits live in `research_persistence`; the route owns
the background task. Neither concern belongs here, which is what keeps this
testable with scripted doubles and no database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from careerhq.application.ports import (
    ResearchOutcome,
    ResearchProvider,
    ResearchProviderUnavailable,
)
from careerhq.application.scoreability import scoreable_posting


class _HasJob(Protocol):
    job_title: str
    job_description: str | None
    requirements: list[str] | None


class _HasIdentity(Protocol):
    name: str
    domain: str | None


@dataclass(frozen=True, slots=True)
class ResearchContext:
    """Everything a research provider may know. Nothing else exists to send."""

    company_name: str
    domain: str | None
    role_title: str | None
    posting_text: str | None


def context_for(application: _HasJob, company: _HasIdentity) -> ResearchContext:
    """The research input, assembled from the application alone.

    **No posting empties both role fields.** A role title without its posting
    would smuggle role context past the honest company-only degrade (D7) — the
    provider would research a title nobody could ground, which is the guessing
    FR-011 exists to prevent. Title and posting travel together or not at all.
    """
    posting = scoreable_posting(application)
    return ResearchContext(
        company_name=company.name,
        domain=company.domain,
        role_title=application.job_title if posting is not None else None,
        posting_text=posting,
    )


async def perform_research(
    context: ResearchContext,
    *,
    provider: ResearchProvider,
    fallback: ResearchProvider | None,
) -> ResearchOutcome:
    """One research run: the provider, then the configured fallback decision."""
    try:
        return await provider.research(
            company_name=context.company_name,
            domain=context.domain,
            role_title=context.role_title,
            posting_text=context.posting_text,
        )
    except ResearchProviderUnavailable:
        # Only unavailability falls back, and only when configured. Everything
        # else — rejection included — propagates to be recorded (FR-017).
        if fallback is None:
            raise
        return await fallback.research(
            company_name=context.company_name,
            domain=context.domain,
            role_title=context.role_title,
            posting_text=context.posting_text,
        )


__all__ = ["ResearchContext", "context_for", "perform_research"]
