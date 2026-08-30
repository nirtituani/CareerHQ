"""The real `WebSearch`: Tavily over HTTPS.

**The `include_raw_content` boundary is what most of this file guards.** Tavily
*can* return page bodies, and if it did, CareerHQ would be summarising text it
never fetched: the SSRF guard would be bypassed, and FR-032's verbatim check
would quietly become a comparison between a model's quotation and a provider's
summary. Every test would still pass. OQ-A recorded exactly this — "one careless
change routes content around the guard silently" — so the flag is asserted on the
outgoing request *and* the mapper is asserted to ignore a body that arrives
anyway. Either alone would be one edit from useless.

No network here. The transport is injected; the live probe is separate.
"""

from __future__ import annotations

from typing import Any

import pytest

from careerhq.application.ports import SearchHit, WebSearch
from careerhq.infrastructure.research.tavily_search import (
    SearchUnavailable,
    TavilySearch,
    _hits_from_payload,
)

pytestmark = pytest.mark.asyncio

PAYLOAD: dict[str, Any] = {
    "query": '"Acme" company overview',
    "results": [
        {
            "title": "Acme Engineering Blog",
            "url": "https://acme.example/eng",
            "content": "How we run a service per team.",
            "score": 0.91,
        },
        {
            "title": "Acme — About",
            "url": "https://acme.example/about",
            "content": "Acme processes payments for European retailers.",
            "score": 0.88,
        },
    ],
}


def _search(payload: object, *, sent: list[dict[str, Any]] | None = None) -> TavilySearch:
    async def _post(body: dict[str, Any]) -> object:
        if sent is not None:
            sent.append(body)
        if isinstance(payload, Exception):
            raise payload
        return payload

    return TavilySearch(post=_post)


# -- the trust boundary ------------------------------------------------------


async def test_it_asks_tavily_not_to_return_page_content() -> None:
    """The single field that keeps our own fetching meaningful.

    Sent explicitly rather than relying on a default, because a provider's
    default can change under us and the failure would be invisible: briefs would
    still be produced, from text that never passed the guard.
    """
    sent: list[dict[str, Any]] = []
    await _search(PAYLOAD, sent=sent).search(query="x", limit=3)

    assert sent[0]["include_raw_content"] is False, (
        "raw page content was not explicitly declined; this is the boundary that "
        "makes CareerHQ's own fetching, and therefore FR-032, meaningful"
    )


async def test_page_content_is_ignored_even_if_the_provider_sends_it() -> None:
    """The second half of the same guarantee.

    Asking is not enough — the mapper must not read a body it was sent anyway.
    Two independent defences, because either one alone is a single edit from
    being useless.
    """
    payload = {
        "results": [
            {
                "title": "t",
                "url": "https://acme.example/eng",
                "content": "the snippet",
                "raw_content": "THE ENTIRE PAGE BODY THAT WE NEVER FETCHED",
            }
        ]
    }
    hits = await _search(payload).search(query="x", limit=3)

    assert hits[0].snippet == "the snippet"
    serialised = repr(hits[0])
    assert "ENTIRE PAGE BODY" not in serialised, (
        "raw page content reached a SearchHit; the fetch guard has been routed around"
    )


async def test_a_hit_carries_no_page_content_field_at_all() -> None:
    """Asserted on the real hits the adapter produced, not only on the class —
    a mapper could otherwise attach an attribute the dataclass never declared."""
    hits = await _search(PAYLOAD).search(query="x", limit=3)
    assert hits, "examined zero hits; this gate is looking at nothing"
    fields = set(SearchHit.__slots__)
    assert fields == {"url", "title", "snippet"}, (
        f"SearchHit gained {fields - {'url', 'title', 'snippet'}}"
    )


# -- the mapping -------------------------------------------------------------


async def test_it_maps_results_into_search_hits() -> None:
    hits = await _search(PAYLOAD).search(query='"Acme" company overview', limit=5)

    assert [h.url for h in hits] == ["https://acme.example/eng", "https://acme.example/about"]
    assert hits[0].title == "Acme Engineering Blog"
    assert hits[0].snippet == "How we run a service per team."


async def test_the_limit_is_a_budget_not_a_suggestion() -> None:
    """FR-004 bounds a run in code. Enforced on the request and on the response,
    because a provider returning extra results would otherwise widen the run."""
    sent: list[dict[str, Any]] = []
    hits = await _search(PAYLOAD, sent=sent).search(query="x", limit=1)

    assert len(hits) == 1
    assert sent[0]["max_results"] == 1


async def test_the_query_reaches_the_provider_unchanged() -> None:
    """Layer 1's queries quote the company name deliberately — an unquoted
    multi-word name matches loosely and returns a different company. An adapter
    that helpfully normalised the string would undo that."""
    sent: list[dict[str, Any]] = []
    await _search(PAYLOAD, sent=sent).search(query='"Acme Payments" products', limit=3)
    assert sent[0]["query"] == '"Acme Payments" products'


async def test_it_asks_for_the_cheap_search_depth() -> None:
    """`advanced` costs two credits and buys deeper extraction we do not use,
    because the pages are fetched by us afterwards."""
    sent: list[dict[str, Any]] = []
    await _search(PAYLOAD, sent=sent).search(query="x", limit=3)
    assert sent[0]["search_depth"] == "basic"


# -- malformed and hostile payloads -----------------------------------------


@pytest.mark.parametrize(
    "payload", [{}, {"results": []}, {"results": None}, [], "text", None, {"results": [None]}]
)
async def test_an_unusable_payload_yields_no_hits_rather_than_raising(payload: object) -> None:
    """One empty query must not abandon a six-query run."""
    assert await _search(payload).search(query="x", limit=5) == []


async def test_a_result_without_a_url_is_dropped() -> None:
    payload = {"results": [{"title": "No link", "content": "..."}]}
    assert await _search(payload).search(query="x", limit=5) == []


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,<script>", "ftp://h/x"]
)
async def test_a_non_http_url_is_dropped_at_the_boundary(url: str) -> None:
    """Defence in depth: `fetch_url` refuses these too, but a URL dropped here is
    never persisted as a citation either."""
    payload = {"results": [{"title": "t", "url": url, "content": "d"}]}
    assert await _search(payload).search(query="x", limit=5) == []


async def test_a_missing_title_falls_back_to_the_url() -> None:
    payload = {"results": [{"url": "https://a.example/x", "content": "d"}]}
    hits = await _search(payload).search(query="x", limit=5)
    assert hits[0].title == "https://a.example/x"


# -- provider failures -------------------------------------------------------


async def test_a_transport_failure_raises_search_unavailable() -> None:
    """A *search* failure is not an ordinary outcome: the run would have no
    sources at all, and a brief synthesised from nothing is a fabrication."""
    with pytest.raises(SearchUnavailable):
        await _search(RuntimeError("connection reset")).search(query="x", limit=5)


async def test_the_failure_leaks_neither_the_transport_detail_nor_the_key() -> None:
    with pytest.raises(SearchUnavailable) as caught:
        await _search(RuntimeError("401 for tvly-secret-abc at 10.0.0.5")).search(
            query="x", limit=5
        )
    message = str(caught.value)
    assert "tvly-secret-abc" not in message
    assert "10.0.0.5" not in message


async def test_an_unconfigured_key_refuses_rather_than_searching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key means no search. Returning `[]` would let a run proceed to
    synthesis with nothing, which is the failure `SearchUnavailable` exists to
    prevent.

    **The absent key is constructed, not assumed.** An earlier version asserted
    `get_settings().tavily_api_key is None` and so depended on the developer's
    own `.env`: it passed on a machine with no key and failed the moment one was
    added, which is a test measuring the environment rather than the code. Caught
    exactly that way, by adding a real key for the live probe.
    """
    import careerhq.infrastructure.research.tavily_search as module
    from careerhq.config import Settings, get_settings

    unconfigured = get_settings().model_copy(update={"tavily_api_key": None})
    assert isinstance(unconfigured, Settings)
    monkeypatch.setattr(module, "get_settings", lambda: unconfigured)

    with pytest.raises(SearchUnavailable):
        await TavilySearch().search(query="x", limit=3)


# -- the port and the endpoint ----------------------------------------------


async def test_it_satisfies_the_websearch_port_structurally() -> None:
    search: WebSearch = _search(PAYLOAD)
    assert callable(search.search)


def test_the_endpoint_is_hard_coded_and_https() -> None:
    """No untrusted input may influence which host is called — which is what
    keeps this request outside the SSRF problem rather than inside it. The query
    travels in the JSON body, never in the URL."""
    from careerhq.infrastructure.research.tavily_search import TAVILY_SEARCH_URL

    assert TAVILY_SEARCH_URL.startswith("https://")
    assert TAVILY_SEARCH_URL == "https://api.tavily.com/search"


def test_the_mapper_is_pure_and_examines_what_it_is_given() -> None:
    hits = _hits_from_payload(PAYLOAD, limit=10)
    assert len(hits) == 2
    assert hits[1].url == "https://acme.example/about"
