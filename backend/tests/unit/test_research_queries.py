"""Layer 1's search queries are generated deterministically, with no model.

`plan.md` §2 eliminates the Layer 1 query-planning model call: the queries depend
only on company identity, and `Company.domain` disambiguates it, so a template
chooses from a space that does not vary. Every model call that does not earn its
place is a cost and latency defect on this system — slice 005 measured output at
57-86% of cost, and adaptive thinking silently adding 42-60% on top.

Layer 2's role queries **do** use a model (OQ-I), because Brave's index is
keyword-oriented and mapping a role onto productive search terms is world
knowledge a template cannot supply. That call is not this module's business.
"""

from __future__ import annotations

import pytest

from careerhq.application.research_queries import MAX_GENERAL_QUERIES, general_queries


def test_the_same_company_always_produces_the_same_queries() -> None:
    """Deterministic means deterministic: no ordering wobble, no randomness.
    A template that varied would reintroduce the reason to use a model."""
    first = general_queries(company_name="Acme Payments", domain="acme.com")
    second = general_queries(company_name="Acme Payments", domain="acme.com")
    assert first == second
    assert first, "the template must actually produce queries"


def test_every_query_names_the_company() -> None:
    for query in general_queries(company_name="Acme Payments", domain=None):
        assert "Acme Payments" in query


def test_the_domain_is_used_to_disambiguate_when_known() -> None:
    """Two companies share a name; a domain does not. This is why `docs/07:141`
    specifies the input as 'company name and domain'."""
    with_domain = general_queries(company_name="Acme", domain="acme.com")
    assert any("acme.com" in q for q in with_domain)


def test_no_domain_query_is_emitted_when_the_domain_is_unknown() -> None:
    """`Company.domain` is nullable. A `site:None` query would be worse than
    none at all."""
    queries = general_queries(company_name="Acme", domain=None)
    assert all("site:" not in q for q in queries)
    assert queries, "a company with no known domain must still be researchable"


def test_the_query_count_is_bounded() -> None:
    """FR-004: the run is bounded by a named constant, not by a prompt."""
    queries = general_queries(company_name="A Very Long Company Name Ltd", domain="example.com")
    assert len(queries) <= MAX_GENERAL_QUERIES
    assert MAX_GENERAL_QUERIES <= 8, "a wider fan-out is an output-token decision, not a default"


def test_exceeding_the_budget_raises_rather_than_silently_dropping_a_query() -> None:
    """**Found by drilling.** The budget was applied with a slice, so a query
    added beyond it vanished — and a drill of the role-independence test below
    came up green because the offending query had been truncated away before the
    assertion ran. A silently shorter search is worse than a loud failure."""
    import careerhq.application.research_queries as mod

    original = mod.MAX_GENERAL_QUERIES
    mod.MAX_GENERAL_QUERIES = 2
    try:
        with pytest.raises(ValueError) as exc:
            mod.general_queries(company_name="Acme", domain="acme.com")
        assert "budget" in str(exc.value)
    finally:
        mod.MAX_GENERAL_QUERIES = original


def test_no_query_mentions_a_role_or_a_job() -> None:
    """**FR-021 as a test.** Layer 1 is role-independent, so its queries cannot
    be about a job. If a role ever reaches this function, this fails."""
    queries = " ".join(general_queries(company_name="Acme", domain="acme.com")).lower()
    for forbidden in ("engineer", "developer", "role", "job", "hiring", "vacancy", "salary"):
        assert forbidden not in queries, (
            f"a Layer 1 query mentioned {forbidden!r}; the general layer must read "
            "identically for two different jobs at the same employer"
        )


def test_queries_are_free_of_duplicates() -> None:
    queries = general_queries(company_name="Acme", domain="acme.com")
    assert len(queries) == len(set(queries)), "a duplicate query spends the budget twice"


def test_a_company_name_with_punctuation_is_quoted_for_the_engine() -> None:
    """Brave is keyword-oriented; an unquoted multi-word name matches loosely."""
    queries = general_queries(company_name="Acme Payments", domain=None)
    assert any('"Acme Payments"' in q for q in queries)
