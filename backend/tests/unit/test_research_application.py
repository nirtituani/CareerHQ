"""The research use case: context assembly and the fallback decision (T014).

The provider double is scripted and **raises when called twice** — a double
that repeats its last answer would make a retry loop look convergent (testing
rule 8). Context assembly is asserted from what the double captured, and the
inputs come from the application alone: the one thing that must never appear
is anything profile-shaped, and there is no parameter it could arrive through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from careerhq.application.ports import (
    ResearchOutcome,
    ResearchProviderRejected,
    ResearchProviderUnavailable,
)
from careerhq.application.research_application import context_for, perform_research
from careerhq.domain.schemas.research import ApplicationResearch


def _outcome(produced_by: str = "provider:tavily-research") -> ResearchOutcome:
    research = ApplicationResearch.model_validate(
        {
            "company_identification": {
                "official_name": "Pango",
                "website": "https://pango.co.il",
                "how_identified": "posting location and domain",
            },
            "company_overview": "o",
            "products_and_services": "p",
            "business_and_market": "b",
            "relevant_to_your_role": "r",
            "what_to_know_before_the_interview": ["k"],
            "questions_worth_asking": ["q"],
        }
    )
    return ResearchOutcome(
        research=research,
        sources=(),
        produced_by=produced_by,
        prompt_version="app-v1",
        cost_estimate=Decimal("0.1"),
    )


class ScriptedProvider:
    """Answers (or raises) once. A second call is a test failure, loudly."""

    def __init__(self, result: ResearchOutcome | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, str | None]] = []

    async def research(
        self,
        *,
        company_name: str,
        domain: str | None,
        role_title: str | None,
        posting_text: str | None,
    ) -> ResearchOutcome:
        if self.calls:
            raise AssertionError("provider called twice — the script has one answer")
        self.calls.append(
            {
                "company_name": company_name,
                "domain": domain,
                "role_title": role_title,
                "posting_text": posting_text,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeApplication:
    job_title: str = "Senior Back End Developer - Parking Team"
    job_description: str | None = "Join our Parking Domain at Pango."
    #: An empty list, not None: `requirements IS NULL` marks a pre-004 legacy
    #: row and is refused outright by `scoreable_posting`.
    requirements: list[str] | None = field(default_factory=list)


@dataclass
class FakeCompany:
    name: str = "Pango"
    domain: str | None = "pango.co.il"


def test_context_comes_from_the_application_and_company_only() -> None:
    context = context_for(FakeApplication(), FakeCompany())
    assert context.company_name == "Pango"
    assert context.domain == "pango.co.il"
    assert context.role_title == "Senior Back End Developer - Parking Team"
    assert context.posting_text == "Join our Parking Domain at Pango."


def test_no_posting_means_no_role_context_at_all() -> None:
    """D7: `scoreable_posting` answering nothing empties BOTH role fields — a
    role title without a posting would smuggle role context past the honest
    company-only degrade."""
    application = FakeApplication(job_description=None, requirements=[])
    context = context_for(application, FakeCompany())
    assert context.posting_text is None
    assert context.role_title is None

    legacy = FakeApplication(requirements=None)
    assert context_for(legacy, FakeCompany()).posting_text is None


def test_requirements_compose_into_the_posting_when_no_description() -> None:
    """The context uses the same single scoreability answer as Match and
    Tailor — requirements compose one per line when the description is empty."""
    application = FakeApplication(job_description=None, requirements=["Python", "AWS experience"])
    context = context_for(application, FakeCompany())
    assert context.posting_text == "- Python\n- AWS experience"


async def test_the_provider_is_called_once_with_the_context() -> None:
    provider = ScriptedProvider(_outcome())
    context = context_for(FakeApplication(), FakeCompany())
    outcome = await perform_research(context, provider=provider, fallback=None)

    assert outcome.produced_by == "provider:tavily-research"
    (call,) = provider.calls
    assert call["company_name"] == "Pango"
    assert call["posting_text"] == "Join our Parking Domain at Pango."


async def test_unavailable_with_a_fallback_runs_the_fallback() -> None:
    provider = ScriptedProvider(ResearchProviderUnavailable("down"))
    fallback = ScriptedProvider(_outcome(produced_by="builtin"))
    context = context_for(FakeApplication(), FakeCompany())

    outcome = await perform_research(context, provider=provider, fallback=fallback)
    assert outcome.produced_by == "builtin"
    assert len(fallback.calls) == 1


async def test_unavailable_without_a_fallback_reraises() -> None:
    provider = ScriptedProvider(ResearchProviderUnavailable("down"))
    context = context_for(FakeApplication(), FakeCompany())
    with pytest.raises(ResearchProviderUnavailable):
        await perform_research(context, provider=provider, fallback=None)


async def test_rejected_output_never_falls_back() -> None:
    """Bad output is a fact about this run, not about availability — a retry
    against the same input would repeat it, and a silent fallback would hide a
    provider quality problem behind a worse pipeline (contract invariant 4)."""
    provider = ScriptedProvider(ResearchProviderRejected("schema violation"))
    fallback = ScriptedProvider(_outcome(produced_by="builtin"))
    context = context_for(FakeApplication(), FakeCompany())

    with pytest.raises(ResearchProviderRejected):
        await perform_research(context, provider=provider, fallback=fallback)
    assert fallback.calls == []
