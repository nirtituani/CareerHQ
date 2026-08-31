"""The builtin fallback adapter: the unchanged 008 pipeline behind the new
port (T026).

The doubles are the same kind the 008 pipeline's own tests use — a scripted
seam that must be *read from the prompt*, a search double returning pointers
only, a fetcher returning the page — so this proves the wrapper's mapping, not
a re-test of `research_company` itself.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from careerhq.application.ports import (
    Completion,
    FetchedSource,
    ResearchProviderUnavailable,
    SearchHit,
    Usage,
)
from careerhq.infrastructure.research.builtin_provider import BuiltinResearch
from careerhq.infrastructure.research.tavily_search import SearchUnavailable

PAGE = "Pango operates mobile parking payments across Israel."


class _Search:
    async def search(self, *, query: str, limit: int) -> list[SearchHit]:
        return [SearchHit(url="https://pango.co.il/about", title="About", snippet="s")]


class _FailingSearch:
    async def search(self, *, query: str, limit: int) -> list[SearchHit]:
        raise SearchUnavailable("Web search is not configured.")


class _Fetcher:
    def __init__(self, *, works: bool = True) -> None:
        self.works = works

    async def fetch(self, *, url: str) -> FetchedSource | None:
        if not self.works:
            return None
        return FetchedSource(url=url, title="About", text=PAGE, source_id="")


class _Seam:
    """Answers the synthesis task with one cited fact quoted from the page."""

    async def complete(self, *, task: str, schema: Any, prompt: str) -> Completion[Any]:
        assert "mobile parking payments" in prompt, "the seam must be fed the fetched page"
        empty = {"claims": [], "empty_reason": "No public source covered this."}
        value = schema.model_validate(
            {
                "what_the_company_does": {
                    "claims": [
                        {
                            "id": "c1",
                            "text": "Pango operates mobile parking payments.",
                            "tier": "fact",
                            "evidence": [{"source_id": "s1", "excerpt": "mobile parking payments"}],
                        }
                    ]
                },
                "products_and_services": empty,
                "market_and_customers": empty,
                "practical_facts": empty,
                "interview_preparation": empty,
            }
        )
        return Completion(
            value=value,
            usage=Usage(model="gemini/x", input_tokens=100, output_tokens=40, cost=Decimal("0.01")),
        )


async def test_the_wrapper_returns_a_tiered_recorded_outcome_with_verified_excerpts() -> None:
    adapter = BuiltinResearch(search=_Search(), fetcher=_Fetcher(), completion=_Seam())  # type: ignore[arg-type]
    outcome = await adapter.research(
        company_name="Pango",
        domain=None,
        role_title="ignored by design",
        posting_text="ignored by design",
    )

    assert outcome.prompt_version == "v2-dense"
    assert outcome.produced_by == "builtin"
    assert outcome.usage is not None and outcome.usage.cost == Decimal("0.01")
    assert outcome.cost_estimate is None
    # The one thing this path does better: the surviving verified excerpt.
    cited = next(s for s in outcome.sources if s.source_id == "s1")
    assert cited.excerpt == "mobile parking payments"


async def test_a_page_that_could_not_be_read_is_still_a_source_row() -> None:
    adapter = BuiltinResearch(
        search=_Search(), fetcher=_Fetcher(works=False), completion=_SeamEmpty()
    )  # type: ignore[arg-type]
    outcome = await adapter.research(
        company_name="Pango", domain=None, role_title=None, posting_text=None
    )
    failed = [s for s in outcome.sources if s.fetch_status == "failed"]
    assert [s.source_id for s in failed] == ["f1"]


class _SeamEmpty:
    async def complete(self, *, task: str, schema: Any, prompt: str) -> Completion[Any]:
        empty = {"claims": [], "empty_reason": "No pages could be retrieved."}
        value = schema.model_validate(dict.fromkeys(schema.model_fields, empty))
        return Completion(
            value=value,
            usage=Usage(model="gemini/x", input_tokens=10, output_tokens=5, cost=Decimal("0.001")),
        )


async def test_search_unavailability_maps_to_the_port_vocabulary() -> None:
    adapter = BuiltinResearch(search=_FailingSearch(), fetcher=_Fetcher(), completion=_Seam())  # type: ignore[arg-type]
    with pytest.raises(ResearchProviderUnavailable):
        await adapter.research(
            company_name="Pango", domain=None, role_title=None, posting_text=None
        )
