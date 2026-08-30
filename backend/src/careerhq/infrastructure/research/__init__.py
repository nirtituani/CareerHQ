"""Slice 008's outward-facing adapters: web search and page retrieval.

**Everything that talks to the public internet or to a vendor SDK lives here**,
behind the `WebSearch` and `SourceFetcher` protocols in
`application/ports.py`. The application layer imports the protocols and never
this package, which is what `test_architecture.py` enforces.

Separate from `infrastructure/jobs/` on purpose. That package fetches **one URL
a user typed** for a single posting; this one fetches **N machine-chosen URLs**
from search results. They share the guard — `web_fetcher` calls
`jobs.fetch.fetch_url` rather than reimplementing it — but not their trust
story, and merging them would blur which is which.
"""

from careerhq.infrastructure.research.tavily_search import SearchUnavailable, TavilySearch
from careerhq.infrastructure.research.web_fetcher import WebSourceFetcher

__all__ = ["SearchUnavailable", "TavilySearch", "WebSourceFetcher"]
