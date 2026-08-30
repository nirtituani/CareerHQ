"""The web-search boundary, and the two things its *type* has to guarantee.

Slice 008 fetches from the untrusted public web. The design decision recorded in
`specs/008-company-research/plan.md` §3 is that the search provider returns
**URLs and snippets only**, and CareerHQ does its own fetching through the
existing SSRF guard. That is what makes every byte a model sees provably ours,
and what makes the verbatim excerpt check of FR-032 possible at all.

**So the boundary lives in the type, not in a convention.** A `SearchHit`
carries no page body. An adapter that wanted to hand us page content would have
to change this protocol to do it — a visible change, reviewed, rather than a
silent one.

**`WebSearch` is deliberately not slice 006's retrieval port** (coordination item
S3). They answer different questions — *find me public pages* versus *find me
relevant passages from our curated corpus* — and their trust properties are
opposites. Unifying them would produce an interface that is honest about
neither.
"""

from __future__ import annotations

import inspect

import pytest

from careerhq.application.ports import SearchHit, WebSearch
from tests.support.scripted_search import ScriptedSearch, SearchScriptExhausted


def _hit(url: str = "https://example.com/about") -> SearchHit:
    return SearchHit(url=url, title="About us", snippet="We build payment infrastructure.")


# --- the boundary, asserted on the type ------------------------------------


def test_a_search_hit_carries_no_page_content() -> None:
    """**The trust boundary as a type.** A hit is a pointer plus a teaser. Page
    text arrives only via our own fetching, through the SSRF guard."""
    fields = set(SearchHit.__dataclass_fields__)
    assert fields == {"url", "title", "snippet"}
    for forbidden in ("text", "content", "body", "html", "raw", "markdown", "page"):
        assert forbidden not in fields, (
            f"SearchHit must not carry {forbidden!r}: content that did not come through "
            "our fetch layer has not passed the SSRF guard and cannot be excerpt-checked"
        )


def test_web_search_is_a_protocol_taking_a_query_and_a_limit() -> None:
    """A bounded call. FR-004 bounds the run in code, not in a prompt."""
    sig = inspect.signature(WebSearch.search)
    assert set(sig.parameters) >= {"query", "limit"}


async def test_the_port_is_structural_so_a_double_satisfies_it_without_inheriting() -> None:
    """Same property `StructuredCompletion` relies on: a plain object stands in,
    which is what keeps the suite provider-free and network-free.

    Asserted by *use* rather than by `isinstance`. The protocol is not
    `@runtime_checkable` — none in this codebase are — so conformance is checked
    statically by mypy on the annotation below, and dynamically by the call
    actually working. Marking the production protocol `@runtime_checkable`
    merely to enable an `isinstance` in a test would be a test dictating
    production design.
    """

    async def use(search: WebSearch) -> list[SearchHit]:
        return await search.search(query="acme about", limit=1)

    assert await use(ScriptedSearch(script={"acme about": [_hit()]})) == [_hit()]


# --- the double -------------------------------------------------------------


async def test_the_double_answers_a_scripted_query() -> None:
    search = ScriptedSearch(script={"acme about": [_hit()]})
    hits = await search.search(query="acme about", limit=5)
    assert [h.url for h in hits] == ["https://example.com/about"]


async def test_the_double_records_what_was_asked_and_in_what_order() -> None:
    """Tests need to assert *which* queries the application chose — that is the
    whole subject of OQ-I."""
    search = ScriptedSearch(script={"a": [_hit()], "b": []})
    await search.search(query="a", limit=3)
    await search.search(query="b", limit=3)
    assert search.queries == ["a", "b"]
    assert search.call_count == 2


async def test_the_double_honours_the_limit() -> None:
    search = ScriptedSearch(script={"many": [_hit(f"https://example.com/{i}") for i in range(10)]})
    hits = await search.search(query="many", limit=3)
    assert len(hits) == 3, "the limit is the run's budget and must be respected by the double too"


async def test_an_unscripted_query_fails_loudly() -> None:
    """Mirrors `ScriptedSeam`: a silent empty result would let a test pass while
    the application searched for something nobody intended."""
    search = ScriptedSearch(script={"expected": [_hit()]})
    with pytest.raises(SearchScriptExhausted) as exc:
        await search.search(query="something else", limit=5)
    assert "something else" in str(exc.value)


async def test_a_scripted_empty_result_is_not_an_error() -> None:
    """Finding nothing is a real outcome, and distinct from not being asked."""
    search = ScriptedSearch(script={"obscure": []})
    assert await search.search(query="obscure", limit=5) == []
