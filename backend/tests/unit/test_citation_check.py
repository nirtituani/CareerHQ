"""FR-032: every excerpt must appear verbatim in the page CareerHQ retrieved.

**This is the MVP's only verification layer** (OQ-B). Semantic verification —
does the excerpt actually *support* the claim? — is deferred, because it needs a
model call and slice 005 measured its Reviewer at 49% of run cost. What is left
is free, and it catches the failure that matters most: **citation laundering**,
where an invented claim is paired with a real URL and therefore looks correct.

The check is possible only because the application does its own fetching (OQ-A).
A provider that returned page content would leave us checking a model's quote
against a model's summary, which proves nothing.

**Whitespace is normalised; wording is not.** A page's line wrapping is an
artifact of HTML, not of what it says, so an excerpt that differs only in
newlines is the same excerpt. Anything else — a changed word, a paraphrase, an
invented sentence — is a different claim and is rejected.
"""

from __future__ import annotations

from careerhq.application.citation_check import verify_excerpts
from careerhq.domain.schemas.research import Claim, CompanyResearch, Evidence, ResearchSection

PAGE = (
    "Acme Payments builds payment infrastructure for European retailers.\n"
    "It processes over four million transactions each day."
)


def _claim(claim_id: str, excerpt: str, source_id: str = "s1") -> Claim:
    return Claim(
        id=claim_id,
        text="They build payment infrastructure.",
        tier="fact",
        evidence=[Evidence(source_id=source_id, excerpt=excerpt)],
    )


def _research(*claims: Claim) -> CompanyResearch:
    empty = ResearchSection(claims=[], empty_reason="Not researched in this fixture.")
    return CompanyResearch(
        what_the_company_does=ResearchSection(claims=list(claims))
        if claims
        else ResearchSection(claims=[], empty_reason="none"),
        products_and_services=empty,
        market_and_customers=empty,
        practical_facts=empty,
        interview_preparation=empty,
    )


def _sources() -> dict[str, str]:
    return {"s1": PAGE}


# --- the check itself -------------------------------------------------------


def test_an_excerpt_present_in_the_page_survives() -> None:
    research = _research(_claim("c1", "builds payment infrastructure for European retailers"))
    report = verify_excerpts(research, sources=_sources())

    assert report.rejected == ()
    assert report.examined == 1
    assert len(report.research.what_the_company_does.claims) == 1


def test_an_invented_excerpt_is_rejected_and_its_claim_removed() -> None:
    """**Citation laundering.** A real source id, a quote the page never
    contained. This is the failure the whole check exists for."""
    research = _research(_claim("c1", "is the market leader in South America"))
    report = verify_excerpts(research, sources=_sources())

    assert [r.claim_id for r in report.rejected] == ["c1"]
    assert report.research.what_the_company_does.claims == [], (
        "a claim whose excerpt is not in the page must not be presented as sourced"
    )


def test_line_wrapping_does_not_break_a_genuine_excerpt() -> None:
    """The page is wrapped by HTML; the sentence is not. An excerpt spanning a
    newline is the same excerpt."""
    research = _research(_claim("c1", "European retailers. It processes over four million"))
    report = verify_excerpts(research, sources=_sources())
    assert report.rejected == ()


def test_extra_internal_whitespace_is_tolerated() -> None:
    research = _research(_claim("c1", "builds   payment    infrastructure"))
    report = verify_excerpts(research, sources=_sources())
    assert report.rejected == ()


def test_a_changed_word_is_not_tolerated() -> None:
    """Normalising whitespace must not slide into normalising meaning."""
    research = _research(_claim("c1", "builds payment infrastructure for American retailers"))
    report = verify_excerpts(research, sources=_sources())
    assert [r.claim_id for r in report.rejected] == ["c1"]


def test_a_claim_citing_an_unknown_source_is_rejected() -> None:
    """We can only vouch for pages we fetched. A citation to anything else is
    unverifiable, and unverifiable is not sourced."""
    research = _research(_claim("c1", "builds payment infrastructure", source_id="s9"))
    report = verify_excerpts(research, sources=_sources())

    assert [r.claim_id for r in report.rejected] == ["c1"]
    assert "s9" in report.rejected[0].reason


# --- the other two tiers are untouched -------------------------------------


def test_an_inference_carries_no_excerpt_and_is_never_rejected() -> None:
    """FR-029: an inference may cite nothing. It is labelled, not evidenced, so
    there is nothing here to verify — and dropping it would delete exactly the
    analysis the tiers exist to permit."""
    inference = Claim(id="c2", text="They likely run event-driven systems.", tier="inference")
    report = verify_excerpts(_research(inference), sources=_sources())

    assert report.rejected == ()
    assert report.examined == 0, "an inference has no excerpt to examine"
    assert len(report.research.what_the_company_does.claims) == 1


def test_an_interpretation_resting_on_facts_is_not_excerpt_checked() -> None:
    interpretation = Claim(
        id="c3", text="The volume implies high throughput.", tier="interpretation", rests_on=["c1"]
    )
    report = verify_excerpts(_research(interpretation), sources=_sources())
    assert report.rejected == () and report.examined == 0


# --- the report must be able to prove it did something ---------------------


def test_the_report_counts_what_it_examined() -> None:
    """**A gate with nothing to examine passes forever.** This project has
    shipped that four times, so the count is part of the result rather than
    something a caller has to infer from an empty rejection list."""
    research = _research(
        _claim("c1", "builds payment infrastructure"),
        _claim("c2", "four million transactions each day"),
        _claim("c3", "invented entirely"),
    )
    report = verify_excerpts(research, sources=_sources())

    assert report.examined == 3, "every fact's excerpt must be checked, not just the first"
    assert len(report.rejected) == 1


def test_every_section_is_checked_not_only_the_first() -> None:
    """The five sections are separate fields; a checker that walked one of them
    would pass its tests and verify almost nothing."""
    good = _claim("c1", "builds payment infrastructure")
    bad = _claim("c2", "entirely fabricated sentence")
    research = CompanyResearch(
        what_the_company_does=ResearchSection(claims=[good]),
        products_and_services=ResearchSection(claims=[bad]),
        market_and_customers=ResearchSection(claims=[], empty_reason="none"),
        practical_facts=ResearchSection(claims=[], empty_reason="none"),
        interview_preparation=ResearchSection(claims=[], empty_reason="none"),
    )
    report = verify_excerpts(research, sources=_sources())

    assert report.examined == 2
    assert [r.claim_id for r in report.rejected] == ["c2"]
    assert report.research.products_and_services.claims == []
    assert report.research.products_and_services.empty_reason is not None, (
        "a section emptied by rejection must still explain itself"
    )
