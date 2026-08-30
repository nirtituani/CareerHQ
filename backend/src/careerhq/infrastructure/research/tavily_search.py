"""The real `WebSearch`: Tavily, over its ordinary HTTP API.

**Plain HTTPS, not MCP, and that is a deliberate simplification.** An earlier
draft of this slice reached Tavily's predecessor through an MCP stdio server,
which meant a Node process, an extra SDK and a second failure mode for no
behaviour the product needs. What the requirement is actually about is that the
research agent calls a **real external web-search tool at runtime** rather than
inventing sources; one authenticated POST does that, and does it with fewer
moving parts. `spec.md` names no vendor, so this is a plan-level choice.

**This is not a second fetching implementation, and the distinction is exact.**
`infrastructure/jobs/fetch.py` guards requests to addresses that a *user or a
model* chose, which is where SSRF lives. This module posts to one hard-coded
host, `api.tavily.com`, that no untrusted input can influence — the query text
travels in the JSON body, never in the URL. Those are different problems and
collapsing them would make the guard's purpose harder to state, not easier.

    WebSearch  ->  URLs + snippets  ->  SourceFetcher  ->  guarded fetch  ->  synthesis

**`include_raw_content` is sent as `False` explicitly, and that single field is
the whole trust boundary.** Tavily *can* return page bodies. If it did, CareerHQ
would be summarising text it never retrieved, the SSRF guard would be routed
around entirely, and FR-032's verbatim check would degrade into comparing a
model's quotation against a provider's summary — while every test still passed.
OQ-A recorded this as the reason Brave was preferred: "one careless change routes
content around the guard silently." Two things stop that here: the flag is sent
rather than left to a default that could change under us, and `_hits_from_payload`
reads only `title`, `url` and `content`, so a body that arrived anyway would be
dropped on the floor. A test asserts both.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from careerhq.application.ports import SearchHit
from careerhq.config import get_settings

logger = logging.getLogger(__name__)

#: The one endpoint this module talks to. Hard-coded on purpose: nothing
#: user-supplied may influence which host is called, which is what keeps this
#: request outside the SSRF problem rather than inside it.
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

#: A search is a short round trip and the research run has its own overall
#: budget; a long tail here delays every subsequent step for one slow query.
TIMEOUT_SECONDS = 20.0

#: Only these reach the fetcher. `fetch_url` refuses the rest anyway, but a
#: scheme dropped here is never persisted as a citation either — and a citation
#: pointing at `javascript:` would outlive the failed fetch that produced it.
FETCHABLE_SCHEMES = frozenset({"http", "https"})


class SearchUnavailable(RuntimeError):
    """The search provider could not be reached, or answered unusably.

    **Distinct from "found nothing", and the distinction is load-bearing.** An
    empty result set is an ordinary outcome that a run records honestly. A
    provider that is *down* means the run has no sources at all, and synthesising
    a brief from nothing would be a fabrication carrying a clean bill of health —
    so this propagates rather than degrading into an empty list.

    The message never carries the transport detail or the key: the detail goes to
    the operator's log, the type goes to the caller.
    """


def _snippet_of(result: dict[str, Any]) -> str:
    """Tavily's own teaser, from `content`.

    Enough to choose what is worth fetching, never enough to summarise from —
    summarising a snippet would cite a page nobody read. **`raw_content` is not
    consulted here even if present**: see the module docstring.
    """
    value = result.get("content")
    return value.strip() if isinstance(value, str) else ""


def _hits_from_payload(payload: object, *, limit: int) -> list[SearchHit]:
    """Map one Tavily response onto `SearchHit`s. Pure, and total.

    Returns `[]` for anything it cannot read rather than raising: a malformed or
    empty answer to one of six queries must not abandon a research run, and the
    run already records how little it consulted.

    **A result without a usable http(s) URL is dropped**, because it can be
    neither fetched nor cited nor verified, and putting it in front of the model
    would offer a source id that resolves to nothing.
    """
    if not isinstance(payload, dict):
        return []

    results = payload.get("results")
    if not isinstance(results, list):
        return []

    hits: list[SearchHit] = []
    for result in results:
        if len(hits) >= limit:
            break
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        if urlparse(url).scheme.lower() not in FETCHABLE_SCHEMES:
            continue
        title = result.get("title")
        hits.append(
            SearchHit(
                url=url.strip(),
                title=title.strip() if isinstance(title, str) and title.strip() else url.strip(),
                snippet=_snippet_of(result),
            )
        )
    return hits


class TavilySearch:
    """`WebSearch` over Tavily's HTTP API.

    `post` is injected so the mapping is testable with no network and no key. It
    is a seam for tests, not a configuration knob: anything substituted must
    uphold the same no-page-content contract.
    """

    def __init__(self, post: Any | None = None) -> None:
        self._post = post or self._post_to_tavily

    async def _post_to_tavily(self, body: dict[str, Any]) -> object:
        """One authenticated POST. The key is read at call time and never logged.

        Read from configuration on each call rather than captured at
        construction, so a deployment that adds the key does not also need a
        restart of anything holding a stale instance.
        """
        settings = get_settings()
        key = settings.tavily_api_key
        if key is None:
            raise SearchUnavailable("Web search is not configured.")

        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                TAVILY_SEARCH_URL,
                json=body,
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
            )
            response.raise_for_status()
            return response.json()

    async def search(self, *, query: str, limit: int) -> list[SearchHit]:
        """Run one query. `limit` is the caller's budget and is not advisory.

        Enforced twice — asked of the provider *and* applied to what comes back —
        because a provider returning more than requested would otherwise widen
        the run's source budget, and FR-004 puts that bound in code rather than
        in a request.
        """
        body: dict[str, Any] = {
            "query": query,
            "max_results": limit,
            # The trust boundary. See the module docstring: sent explicitly so a
            # change in the provider's default cannot quietly route page content
            # around our own fetching.
            "include_raw_content": False,
            "include_answer": False,
            # `basic` is one credit; `advanced` is two and buys deeper extraction
            # we do not use, because we fetch the pages ourselves.
            "search_depth": "basic",
        }

        try:
            payload = await self._post(body)
        except SearchUnavailable:
            raise
        except Exception as exc:
            # The detail reaches the operator; the caller gets the kind of
            # failure, never an address, a body or a key.
            logger.warning(
                "web search failed",
                extra={"query_length": len(query), "error": exc.__class__.__name__},
            )
            raise SearchUnavailable("Web search could not be reached.") from exc

        return _hits_from_payload(payload, limit=limit)


__all__ = [
    "FETCHABLE_SCHEMES",
    "TAVILY_SEARCH_URL",
    "SearchUnavailable",
    "TavilySearch",
]
