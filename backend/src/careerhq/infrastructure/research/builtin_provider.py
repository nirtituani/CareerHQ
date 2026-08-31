"""The retained 008 pipeline, behind the slice 010 `ResearchProvider` port.

**A degraded mode, and honest about it.** `research_company()` is called
exactly as 008 shipped it — queries from a template, Tavily search, our own
guarded fetching, one synthesis, the verbatim citation check — and its known
wrong-entity risk on collided names travels with it (spec assumption). What
this wrapper adds is only the outcome shape: the tiered `CompanyResearch`
under `prompt_version="v2-dense"`, exact seam usage (`cost_basis="recorded"`),
and sources that carry their **verified** excerpts — the one thing this path
does better than the provider (FR-010).

**The role context is accepted and deliberately unused.** The 008 pipeline is
role-independent by construction (its schema has no field a job could arrive
through), and threading a role into it would be a redesign of the fallback,
not a fallback. The port's signature is honoured; the extra context is simply
more than this producer can spend.
"""

from __future__ import annotations

from decimal import Decimal

from careerhq.application.ports import (
    ProviderSource,
    ResearchOutcome,
    ResearchProviderUnavailable,
)
from careerhq.application.research_company import COMPANY_PROMPT_VERSION, research_company
from careerhq.domain.models import FetchStatus
from careerhq.infrastructure.ai.litellm_gateway import LiteLLMGateway
from careerhq.infrastructure.research.tavily_search import SearchUnavailable, TavilySearch
from careerhq.infrastructure.research.web_fetcher import WebSourceFetcher

PRODUCED_BY = "builtin"


class BuiltinResearch:
    """`ResearchProvider` over the unchanged 008 pipeline."""

    produced_by = PRODUCED_BY
    #: Unknowable: an interrupted builtin run may have billed search credits
    #: and part of a synthesis, but no documented single figure describes it.
    attempt_cost_estimate: Decimal | None = None

    def __init__(
        self,
        search: TavilySearch | None = None,
        fetcher: WebSourceFetcher | None = None,
        completion: LiteLLMGateway | None = None,
    ) -> None:
        self._search = search or TavilySearch()
        self._fetcher = fetcher or WebSourceFetcher()
        self._completion = completion or LiteLLMGateway()

    async def research(
        self,
        *,
        company_name: str,
        domain: str | None,
        role_title: str | None,
        posting_text: str | None,
    ) -> ResearchOutcome:
        del role_title, posting_text  # role-independent by construction — see module docstring
        try:
            result = await research_company(
                company_name=company_name,
                domain=domain,
                search=self._search,
                fetcher=self._fetcher,
                completion=self._completion,
            )
        except SearchUnavailable as exc:
            raise ResearchProviderUnavailable(str(exc)) from exc

        excerpts: dict[str, str] = {}
        for section_name in type(result.research).model_fields:
            for claim in getattr(result.research, section_name).claims:
                for evidence in claim.evidence:
                    excerpts.setdefault(evidence.source_id, evidence.excerpt)

        sources = [
            ProviderSource(
                source_id=source.source_id,
                url=source.url,
                title=source.title,
                #: The surviving verified excerpt, where a claim cites this
                #: source — verification this path can honestly claim because
                #: it fetched the page itself and checked the passage verbatim.
                excerpt=excerpts.get(source.source_id),
                fetch_status=FetchStatus.RETRIEVED,
            )
            for source in result.sources
        ]
        sources.extend(
            ProviderSource(
                source_id=f"f{index + 1}",
                url=url,
                title=None,
                excerpt=None,
                fetch_status=FetchStatus.FAILED,
            )
            for index, url in enumerate(result.failed_urls)
        )

        return ResearchOutcome(
            research=result.research,
            sources=tuple(sources),
            produced_by=PRODUCED_BY,
            prompt_version=COMPANY_PROMPT_VERSION,
            usage=result.usage,
        )


__all__ = ["PRODUCED_BY", "BuiltinResearch"]
