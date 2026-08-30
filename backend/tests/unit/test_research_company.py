"""Layer 1 end to end, against scripted doubles — no network, no provider.

The pipeline `plan.md` §2 settled on, with the model call count it justified:

    deterministic queries -> search -> controlled fetch -> ONE model call
                          -> verbatim excerpt check (free)

**One model call, not two.** Layer 1's query planning is a template because the
queries depend only on company identity (`research_queries.py`); the synthesis is
irreducibly a model task. Layer 2's role-query planning keeps its model call, and
is not this module's business.

**Plain async, no graph.** OQ-D: a linear sequence with no conditional edge and
no retry is not what LangGraph is for.
"""

from __future__ import annotations

from typing import Any

from careerhq.application.ports import FetchedSource, SearchHit
from careerhq.application.research_company import TASK_SYNTHESISE_COMPANY, research_company
from tests.support.scripted_seam import ScriptedSeam
from tests.support.scripted_search import ScriptedSearch

PAGE_ABOUT = "Acme Payments builds payment infrastructure for European retailers."
PAGE_PRODUCTS = "Its product line covers card acquiring and settlement."


def _hit(url: str, title: str = "t") -> SearchHit:
    return SearchHit(url=url, title=title, snippet="snippet")


def _search() -> ScriptedSearch:
    """Every query the template generates must be scripted, or the double
    raises — which is how a change to query generation announces itself."""
    from careerhq.application.research_queries import general_queries

    queries = general_queries(company_name="Acme Payments", domain="acme.com")
    script: dict[str, list[SearchHit]] = {q: [] for q in queries}
    script[queries[0]] = [_hit("https://acme.com/about", "About")]
    script[queries[1]] = [_hit("https://acme.com/products", "Products")]
    return ScriptedSearch(script=script)


class _Fetcher:
    """A `SourceFetcher` double. Returns None for a page it cannot retrieve."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def fetch(self, *, url: str) -> FetchedSource | None:
        self.requested.append(url)
        text = self.pages.get(url)
        if text is None:
            return None
        return FetchedSource(url=url, title="t", text=text)


def _section(claims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if claims:
        return {"claims": claims}
    return {"claims": [], "empty_reason": "No public source covered this."}


def _answer(claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "what_the_company_does": _section(claims),
        "products_and_services": _section(),
        "market_and_customers": _section(),
        "practical_facts": _section(),
        "interview_preparation": _section(),
    }


def _fact(claim_id: str, excerpt: str, source_id: str) -> dict[str, Any]:
    return {
        "id": claim_id,
        "text": "They build payment infrastructure.",
        "tier": "fact",
        "evidence": [{"source_id": source_id, "excerpt": excerpt}],
    }


async def _run(seam: ScriptedSeam, fetcher: _Fetcher, search: ScriptedSearch | None = None) -> Any:
    return await research_company(
        company_name="Acme Payments",
        domain="acme.com",
        search=search or _search(),
        fetcher=fetcher,
        completion=seam,
    )


# --- the pipeline -----------------------------------------------------------


async def test_layer_one_runs_end_to_end_with_one_model_call() -> None:
    fetcher = _Fetcher({"https://acme.com/about": PAGE_ABOUT})
    seam = ScriptedSeam(
        script={TASK_SYNTHESISE_COMPANY: [_answer([_fact("c1", "payment infrastructure", "s1")])]}
    )

    result = await _run(seam, fetcher)

    assert seam.times_called(TASK_SYNTHESISE_COMPANY) == 1, "Layer 1 is exactly one model call"
    assert seam.call_count == 1, "no other task may be called — query planning is a template"
    assert len(result.research.what_the_company_does.claims) == 1
    assert result.usage.output_tokens > 0, "the audit record must survive the call"


async def test_only_pages_the_search_returned_are_fetched() -> None:
    """The trust boundary: URLs come from search, content comes from us."""
    fetcher = _Fetcher({"https://acme.com/about": PAGE_ABOUT})
    seam = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: [_answer([])]})

    await _run(seam, fetcher)

    assert fetcher.requested == ["https://acme.com/about", "https://acme.com/products"]


async def test_a_page_that_could_not_be_retrieved_is_recorded_not_dropped() -> None:
    """FR-009. A failed fetch is a fact about the run, and silence about it
    would misrepresent how much of the web was actually consulted."""
    fetcher = _Fetcher({"https://acme.com/about": PAGE_ABOUT})  # /products fails
    seam = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: [_answer([])]})

    result = await _run(seam, fetcher)

    assert result.failed_urls == ("https://acme.com/products",)
    assert [s.url for s in result.sources] == ["https://acme.com/about"]


async def test_an_unverifiable_claim_is_removed_before_it_reaches_the_caller() -> None:
    """FR-032 wired into the pipeline, not merely available beside it."""
    fetcher = _Fetcher({"https://acme.com/about": PAGE_ABOUT})
    seam = ScriptedSeam(
        script={TASK_SYNTHESISE_COMPANY: [_answer([_fact("c1", "dominates South America", "s1")])]}
    )

    result = await _run(seam, fetcher)

    assert result.research.what_the_company_does.claims == []
    assert len(result.citations.rejected) == 1
    assert result.citations.examined == 1


# --- what the prompt must and must not contain -----------------------------


async def test_the_prompt_carries_source_ids_the_model_can_cite() -> None:
    """Without ids nothing maps, and a 'successful' run cites nothing — the
    same failure slice 005 hit when master rows lacked `[id: ...]`."""
    fetcher = _Fetcher({"https://acme.com/about": PAGE_ABOUT})
    seam = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: [_answer([])]})

    result = await _run(seam, fetcher)
    prompt = seam.calls[0].prompt

    assert result.sources[0].source_id in prompt
    assert PAGE_ABOUT in prompt, "the fetched text is what the model reads"


async def test_the_prompt_frames_retrieved_content_as_untrusted() -> None:
    """FR-016. These pages are attacker-influenceable; instructions inside them
    carry no authority, and the prompt has to say so."""
    fetcher = _Fetcher({"https://acme.com/about": PAGE_ABOUT})
    seam = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: [_answer([])]})

    await _run(seam, fetcher)
    prompt = seam.calls[0].prompt.lower()

    assert "instructions" in prompt and "ignore" in prompt


async def test_the_prompt_never_mentions_a_role_or_a_job() -> None:
    """**FR-021 at the last place it could leak.** Layer 1 must read identically
    for two different jobs at the same employer."""
    fetcher = _Fetcher({"https://acme.com/about": PAGE_ABOUT})
    seam = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: [_answer([])]})

    await _run(seam, fetcher)
    prompt = seam.calls[0].prompt.lower()

    for forbidden in ("job title", "job description", "candidate", "applicant", "vacancy"):
        assert forbidden not in prompt, (
            f"the Layer 1 prompt mentioned {forbidden!r}; the general layer must not be "
            "shaped by the job the user is applying for"
        )
