"""The real `SourceFetcher` — slice 008's adapter over the shared SSRF guard.

This is S1 discharged. What it must get right, and why each is load-bearing:

* **It reuses `fetch_url`.** A second SSRF implementation is a second thing to
  get wrong, which is the whole reason S1 was a coordination item rather than a
  slice-008 file. A test asserts the delegation rather than trusting it.
* **It returns the final post-redirect URL** (`Retrieved.url`), because that
  value is persisted and displayed as a citation.
* **A failure returns `None`, never raises.** FR-009 requires an unreachable
  source to be recorded as attempted-and-failed; a raise would abort a whole run
  because one page of six was down.
* **A refusal is a `None` too, but for a different reason** — and the pipeline
  records both as consulted. FR-017: a page that yields only template
  placeholders is refused as unreadable rather than "extracted" into
  `{{position.name}}`.

Nothing here touches the network: `fetch_url` is substituted.
"""

from __future__ import annotations

import pytest

from careerhq.application.ports import FetchedSource
from careerhq.infrastructure.jobs.fetch import JobFetchError, Retrieved, UnsafeUrlError
from careerhq.infrastructure.research.web_fetcher import WebSourceFetcher

pytestmark = pytest.mark.asyncio

PAGE = """
<html><head><title>  Acme Engineering  </title></head>
<body><h1>How we build</h1>
<p>Acme runs a service per team, with a shared Kafka backbone carrying the ledger.
Each team owns its deploys end to end and is on call for what it ships.</p>
<p>We run on Postgres, and we have written about the migration at length.</p>
</body></html>
"""


def _fetcher(result: object) -> tuple[WebSourceFetcher, list[str]]:
    """A `WebSourceFetcher` whose transport is scripted. Returns the requested urls."""
    requested: list[str] = []

    async def _retrieve(url: str) -> Retrieved:
        requested.append(url)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, Retrieved)
        return result

    return WebSourceFetcher(retrieve=_retrieve), requested


async def test_it_returns_the_page_as_a_fetched_source() -> None:
    fetcher, requested = _fetcher(Retrieved(url="https://acme.example/eng", body=PAGE))
    source = await fetcher.fetch(url="https://acme.example/eng")

    assert isinstance(source, FetchedSource)
    assert requested == ["https://acme.example/eng"]
    assert "service per team" in source.text
    assert "<p>" not in source.text, "HTML reached the model; the page was not converted to text"


async def test_it_returns_the_final_url_not_the_requested_one() -> None:
    """The reason `fetch_url` exists.

    `FetchedSource.url` is persisted as the citation. A page that redirected must
    be cited at the address that actually served it, or a reader following the
    citation lands somewhere the excerpt was never taken from.
    """
    fetcher, _ = _fetcher(Retrieved(url="https://acme.example/blog/final", body=PAGE))
    source = await fetcher.fetch(url="https://acme.example/short-link")

    assert source is not None
    assert source.url == "https://acme.example/blog/final"


async def test_it_takes_the_title_from_the_page() -> None:
    fetcher, _ = _fetcher(Retrieved(url="https://acme.example/eng", body=PAGE))
    source = await fetcher.fetch(url="https://acme.example/eng")
    assert source is not None
    assert source.title == "Acme Engineering", "the title was not trimmed or not found"


async def test_a_page_with_no_title_still_yields_a_source() -> None:
    """A missing `<title>` is ordinary. Refusing the page over it would discard
    evidence for a cosmetic reason."""
    untitled = PAGE.replace("<title>  Acme Engineering  </title>", "")
    fetcher, _ = _fetcher(Retrieved(url="https://acme.example/x", body=untitled))
    source = await fetcher.fetch(url="https://acme.example/x")
    assert source is not None
    assert "service per team" in source.text
    assert source.title == "https://acme.example/x", (
        "a titleless page should fall back to its URL, so a citation still has a label"
    )


# -- FR-009: a failure is recorded, not raised ------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        UnsafeUrlError("That address is not reachable from CareerHQ."),
        JobFetchError("The site took too long to respond."),
        JobFetchError("This site does not allow automated access."),
    ],
)
async def test_a_failure_returns_none_rather_than_raising(failure: Exception) -> None:
    """One unreachable page of six must not abort the run.

    `research_company` records the URL in `failed_urls` when it gets `None`, so
    returning `None` is what makes FR-009's "attempted-and-failed" record happen.
    A raise would lose the other five pages and the money already spent.
    """
    fetcher, _ = _fetcher(failure)
    assert await fetcher.fetch(url="https://acme.example/gone") is None


async def test_an_ssrf_refusal_is_not_re_raised_as_a_crash() -> None:
    """Specifically the guard's own refusal: a machine-chosen URL that resolves
    inward is an expected outcome of searching the open web, not a bug."""
    fetcher, _ = _fetcher(UnsafeUrlError("That address is not reachable from CareerHQ."))
    assert await fetcher.fetch(url="http://169.254.169.254/") is None


async def test_an_unexpected_error_is_not_swallowed() -> None:
    """Only fetch failures become `None`. A programming error must still surface,
    or a broken adapter looks exactly like an unreachable internet."""
    fetcher, _ = _fetcher(ValueError("a bug, not a fetch failure"))
    with pytest.raises(ValueError):
        await fetcher.fetch(url="https://acme.example/eng")


# -- FR-017: a template shell is refused, not "extracted" -------------------


async def test_a_page_that_only_shipped_its_template_is_refused() -> None:
    """FR-017. A client-rendered board serves `{{position.name}}`; treating that
    as content would put placeholders into a research brief, which reads as a
    broken feature rather than an unreadable page."""
    shell = "<html><body><h1>{{company.name}}</h1><p>{{position.description}}</p></body></html>"
    fetcher, _ = _fetcher(Retrieved(url="https://board.example/x", body=shell))
    assert await fetcher.fetch(url="https://board.example/x") is None


async def test_an_empty_page_is_refused() -> None:
    """Nothing to quote means nothing to cite, and an empty source would occupy a
    slot in the run's budget while contributing no evidence."""
    fetcher, _ = _fetcher(Retrieved(url="https://acme.example/x", body="<html></html>"))
    assert await fetcher.fetch(url="https://acme.example/x") is None


# -- the guard is reused, not reimplemented ---------------------------------


def test_the_adapter_delegates_to_the_shared_guard() -> None:
    """S1's whole point, asserted rather than assumed.

    The default transport must be `fetch_url` from the shared module. An adapter
    that grew its own `httpx` client would bypass `assert_fetchable`, the
    per-hop redirect re-check and the peer verification in one step, and nothing
    else in the suite would notice.
    """
    import ast
    import inspect

    from careerhq.infrastructure.jobs import fetch as guard
    from careerhq.infrastructure.research import web_fetcher

    tree = ast.parse(inspect.getsource(web_fetcher))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported, "examined zero imports; this gate is looking at the wrong module"
    for network in ("httpx", "requests", "urllib3", "aiohttp", "socket"):
        assert network not in imported, (
            f"the adapter imports {network} directly; it must fetch through fetch_url so the "
            "SSRF guard, the per-hop redirect re-check and the peer check all apply"
        )

    assert WebSourceFetcher().retrieve is guard.fetch_url, (
        "the default transport is not the shared guarded fetch"
    )


def test_the_default_construction_needs_no_arguments() -> None:
    """It is wired at a composition root, not configured per call."""
    assert WebSourceFetcher() is not None


async def test_it_satisfies_the_port_structurally() -> None:
    """`SourceFetcher` is a Protocol, so conformance is structural. A signature
    drift would be caught here rather than at the first real run."""
    from careerhq.application.ports import SourceFetcher

    fetcher: SourceFetcher = WebSourceFetcher()
    assert callable(fetcher.fetch)
