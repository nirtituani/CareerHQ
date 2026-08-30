"""Layer 2 end to end, against scripted doubles (plan.md §8 step 4).

No network, no provider, no paid call: `ScriptedSearch` and `ScriptedSeam` are
what make that true, and they are the same doubles Layer 1 uses.

**What this file is really guarding is the boundary between the two layers.**
Layer 2 is allowed to know the job; Layer 1 is not, and the reuse in `plan.md`
§6 rests entirely on that asymmetry holding. So the tests below check both
directions: that the role genuinely reaches Layer 2's prompts, and that building
Layer 2 changes nothing about the Layer 1 snapshot it was handed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from careerhq.application.ports import FetchedSource, SearchHit
from careerhq.application.research_company import TASK_SYNTHESISE_COMPANY
from careerhq.application.research_role import (
    TASK_PLAN_ROLE_QUERIES,
    TASK_SYNTHESISE_ROLE,
    build_role_query_prompt,
    build_role_synthesis_prompt,
    research_role,
)
from careerhq.application.research_windows import effective_retrieved_at
from careerhq.domain.schemas.research import (
    Claim,
    CompanyResearch,
    Evidence,
    ResearchSection,
)
from tests.support.scripted_seam import ScriptedSeam
from tests.support.scripted_search import ScriptedSearch

# Only the pipeline tests are async; the prompt builders are pure functions.


ROLE_TITLE = "Senior Backend Engineer"
ROLE_DESCRIPTION = "Own the payments ledger. Go, Postgres, Kafka, on-call."
REQUIREMENTS = ["5+ years backend", "Distributed systems", "Go or Rust"]

PAGE = "Acme runs a service per team and a shared Kafka backbone for the ledger."
QUERIES = ['"Acme" engineering blog', '"Acme" backend architecture']
PAGE_URL = "https://acme.example/eng"


def _section(claims: list[dict[str, object]] | None = None) -> dict[str, object]:
    if claims:
        return {"claims": claims}
    return {"claims": [], "empty_reason": "No public source covered this."}


def _layer1() -> CompanyResearch:
    """A Layer 1 brief with one quotable fact, so the synthesis prompt has
    something recognisable to carry."""
    empty = ResearchSection(claims=[], empty_reason="Not covered by the sources.")
    return CompanyResearch(
        what_the_company_does=ResearchSection(
            claims=[
                Claim(
                    id="l1",
                    text="Acme processes payments for European retailers.",
                    tier="fact",
                    evidence=[Evidence(source_id="s1", excerpt="payments for European retailers")],
                )
            ]
        ),
        products_and_services=empty,
        market_and_customers=empty,
        practical_facts=empty,
        interview_preparation=empty,
    )


def _plan_answer(queries: list[str] | None = None) -> dict[str, object]:
    return {"queries": queries if queries is not None else list(QUERIES)}


def _brief_answer(excerpt: str = "a service per team") -> dict[str, object]:
    return {
        "findings": [
            {
                "heading": "Architecture",
                "claims": [
                    {
                        "id": "c1",
                        "text": "They run a service-per-team topology.",
                        "tier": "fact",
                        "evidence": [{"source_id": "s1", "excerpt": excerpt}],
                    }
                ],
            }
        ],
        "interview_preparation": _section(),
    }


def _seam(
    plan: dict[str, object] | None = None, brief: dict[str, object] | None = None
) -> ScriptedSeam:
    return ScriptedSeam(
        script={
            TASK_PLAN_ROLE_QUERIES: [plan or _plan_answer()],
            TASK_SYNTHESISE_ROLE: [brief or _brief_answer()],
        }
    )


def _search() -> ScriptedSearch:
    """Every query the *model* asked for must be scripted, or the double raises.

    Keyed by query rather than by call order deliberately: it is what lets a
    test assert which searches the planner actually produced, which is the
    subject of OQ-I.
    """
    script: dict[str, list[SearchHit]] = {q: [] for q in QUERIES}
    script[QUERIES[0]] = [SearchHit(url=PAGE_URL, title="Acme Engineering", snippet="s")]
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
        return FetchedSource(url=url, title="Acme Engineering", text=text)


async def _run(**overrides: object):  # type: ignore[no-untyped-def]
    kwargs: dict[str, object] = {
        "company_name": "Acme",
        "domain": "acme.example",
        "role_title": ROLE_TITLE,
        "role_description": ROLE_DESCRIPTION,
        "requirements": REQUIREMENTS,
        "company_research": _layer1(),
        "search": _search(),
        "fetcher": _Fetcher({PAGE_URL: PAGE}),
        "completion": _seam(),
    }
    kwargs.update(overrides)
    return await research_role(**kwargs)  # type: ignore[arg-type]


# -- the pipeline ------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer_two_produces_a_brief_from_scripted_sources() -> None:
    result = await _run()
    assert [f.heading for f in result.research.findings] == ["Architecture"]
    assert result.sources[0].url == "https://acme.example/eng"


@pytest.mark.asyncio
async def test_it_makes_exactly_two_model_calls() -> None:
    """plan.md §2: [4] role queries and [6] synthesise_role. A third would mean
    something was added without being justified against the cost table."""
    seam = _seam()
    await _run(completion=seam)
    assert len(seam.calls) == 2, f"expected 2 model calls, got {[c.task for c in seam.calls]}"


@pytest.mark.asyncio
async def test_the_two_calls_use_their_own_task_names() -> None:
    """Model-per-node is configuration, not a branch. Both names must resolve to
    a configured model or they silently run on Opus at ~2.5x."""
    seam = _seam()
    await _run(completion=seam)
    assert [c.task for c in seam.calls] == [TASK_PLAN_ROLE_QUERIES, TASK_SYNTHESISE_ROLE]


# -- FR-022: the role drives it ---------------------------------------------


def test_the_query_prompt_carries_the_role_and_its_requirements() -> None:
    prompt = build_role_query_prompt(
        company_name="Acme",
        domain=None,
        role_title=ROLE_TITLE,
        role_description=ROLE_DESCRIPTION,
        requirements=REQUIREMENTS,
    )
    assert ROLE_TITLE in prompt
    for requirement in REQUIREMENTS:
        assert requirement in prompt, f"{requirement!r} never reached the query planner"


def test_the_synthesis_prompt_carries_the_role() -> None:
    prompt = build_role_synthesis_prompt(
        company_name="Acme",
        role_title=ROLE_TITLE,
        role_description=ROLE_DESCRIPTION,
        requirements=REQUIREMENTS,
        company_research=_layer1(),
        sources=(),
    )
    assert ROLE_TITLE in prompt


def test_the_synthesis_prompt_carries_the_layer_one_understanding() -> None:
    """FR-023's other half: Layer 2 is built *on* Layer 1, so Layer 1's findings
    have to reach the prompt — otherwise the lineage recorded on the row is a
    claim about a document the model never read."""
    prompt = build_role_synthesis_prompt(
        company_name="Acme",
        role_title=ROLE_TITLE,
        role_description=ROLE_DESCRIPTION,
        requirements=REQUIREMENTS,
        company_research=_layer1(),
        sources=(),
    )
    assert "Acme processes payments for European retailers." in prompt


def test_the_synthesis_prompt_never_mentions_the_applicant() -> None:
    """FR-022 — the lens is the job, not the person.

    Asserted against the *whole* prompt, which is safe here because nothing in
    Layer 2's inputs legitimately contains these words.
    """
    prompt = build_role_synthesis_prompt(
        company_name="Acme",
        role_title=ROLE_TITLE,
        role_description=ROLE_DESCRIPTION,
        requirements=REQUIREMENTS,
        company_research=_layer1(),
        sources=(),
    ).lower()
    for word in ("your profile", "the candidate", "the applicant", "your experience"):
        assert word not in prompt, f"{word!r} reached the Layer 2 prompt; FR-022 forbids it"


# -- untrusted content -------------------------------------------------------


def test_fetched_pages_are_framed_as_data() -> None:
    """The pages came from the public web and may address the model directly."""
    prompt = build_role_synthesis_prompt(
        company_name="Acme",
        role_title=ROLE_TITLE,
        role_description=ROLE_DESCRIPTION,
        requirements=REQUIREMENTS,
        company_research=_layer1(),
        sources=(FetchedSource(url="u", title="t", text=PAGE, source_id="s1"),),
    )
    assert "data" in prompt.lower() and "ignore" in prompt.lower()


# -- FR-032: the verbatim check runs on Layer 2 too -------------------------


@pytest.mark.asyncio
async def test_a_fabricated_excerpt_is_rejected() -> None:
    """Citation laundering defeated in Layer 2 exactly as in Layer 1. Without
    this the check would guard half the system."""
    result = await _run(completion=_seam(brief=_brief_answer("not on the page")))
    assert result.citations.rejected, "the fabricated excerpt survived the verbatim check"
    assert result.research.findings[0].claims == []


@pytest.mark.asyncio
async def test_the_checker_reports_what_it_examined() -> None:
    """A gate with nothing to examine passes forever."""
    result = await _run()
    assert result.citations.examined == 1


# -- FR-009: a failed fetch is recorded -------------------------------------


@pytest.mark.asyncio
async def test_a_page_that_cannot_be_fetched_is_recorded_not_dropped() -> None:
    result = await _run(fetcher=_Fetcher({}))
    assert result.failed_urls == ("https://acme.example/eng",)


# -- Layer 1 is not disturbed ------------------------------------------------


@pytest.mark.asyncio
async def test_running_layer_two_does_not_alter_the_layer_one_snapshot() -> None:
    """The reuse guarantee in operational form: a Layer 1 snapshot handed to
    Layer 2 must come back byte-identical, or it is no longer the same research
    the next application would reuse."""
    layer1 = _layer1()
    before = layer1.model_dump_json()
    await _run(company_research=layer1)
    assert layer1.model_dump_json() == before


@pytest.mark.asyncio
async def test_layer_two_never_asks_for_a_company_brief() -> None:
    """Layer 2 must not re-derive Layer 1. Merging the two calls would feed role
    context into company research, break FR-021 and forfeit the caching."""
    seam = _seam()
    await _run(completion=seam)
    assert TASK_SYNTHESISE_COMPANY not in [c.task for c in seam.calls]


# -- FR-023: lineage back to the Layer 1 snapshot ---------------------------


@pytest.mark.asyncio
async def test_the_result_records_which_layer_one_it_rests_on() -> None:
    """FR-023. Both the identity *and* the timestamp, because "how old was the
    company research this rests on" is the question FR-033 then judges freshness
    by, and an id alone cannot answer it without a second query."""
    snapshot_id = uuid.uuid4()
    retrieved = datetime(2026, 1, 1, tzinfo=UTC)
    result = await _run(company_snapshot_id=snapshot_id, company_retrieved_at=retrieved)
    assert result.company_snapshot_id == snapshot_id
    assert result.company_retrieved_at == retrieved


# -- FR-033: effective age is the older of the two --------------------------


def test_a_fresh_brief_on_stale_company_research_is_stale() -> None:
    """The whole point of FR-033. A role analysis written today on top of
    year-old company research is not fresh, and showing it as fresh is the
    "silently wrong" failure."""
    role = datetime(2026, 8, 29, tzinfo=UTC)
    company = datetime(2025, 8, 29, tzinfo=UTC)
    assert effective_retrieved_at(role_retrieved_at=role, company_retrieved_at=company) == company


def test_effective_age_is_the_role_s_own_when_it_is_the_older() -> None:
    role = datetime(2025, 8, 29, tzinfo=UTC)
    company = datetime(2026, 8, 29, tzinfo=UTC)
    assert effective_retrieved_at(role_retrieved_at=role, company_retrieved_at=company) == role


def test_a_missing_lineage_does_not_make_a_brief_infinitely_stale() -> None:
    """A missing timestamp and an ancient one need different fixes, so they must
    not collapse to the same answer."""
    role = datetime(2026, 8, 29, tzinfo=UTC)
    assert effective_retrieved_at(role_retrieved_at=role, company_retrieved_at=None) == role


# -- Principle V: the audit record ------------------------------------------


@pytest.mark.asyncio
async def test_both_model_calls_are_billed_and_kept_apart() -> None:
    """One `Usage` per call, never a sum.

    `Usage` carries the model that produced it, so summing would fabricate a
    model name in the one record whose job is to say what actually ran. Slice
    005 stores totals only, and that is precisely why its output-token overrun
    has no attributable cause.
    """
    result = await _run()
    assert len(result.usages) == 2, "a per-call breakdown is required, not a total"
    assert result.cost == sum(u.cost for u in result.usages)
    assert result.input_tokens > 0 and result.output_tokens > 0


# -- OQ-I: what the planner asked for is recorded ---------------------------


@pytest.mark.asyncio
async def test_the_chosen_queries_are_kept() -> None:
    """OQ-I's revisit trigger compares query strategies by what survives into the
    brief. It cannot be run against a pipeline that discards its own queries."""
    result = await _run()
    assert result.queries == tuple(QUERIES)


@pytest.mark.asyncio
async def test_a_query_the_planner_did_not_choose_is_never_searched() -> None:
    """The double raises on an unscripted query, so this asserts the application
    searched for exactly what the model asked for and nothing it invented."""
    search = _search()
    await _run(search=search)
    assert search.queries == [QUERIES[0], QUERIES[1]]
