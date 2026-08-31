"""The ResearchOutcome invariants (contracts/research-provider-seam.md, T009).

Enforced in the type's own `__post_init__` rather than trusted, because the
two adapters are written separately and a pairing bug between them would
otherwise surface as a wrong `cost_basis` in an audit row.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from careerhq.application.ports import ProviderSource, ResearchOutcome, Usage
from careerhq.domain.schemas.research import ApplicationResearch, CompanyResearch


def _application_research() -> ApplicationResearch:
    return ApplicationResearch.model_validate(
        {
            "company_identification": {
                "official_name": "Pango",
                "website": "https://pango.co.il",
                "how_identified": "posting location and domain",
            },
            "company_overview": "o",
            "products_and_services": "p",
            "business_and_market": "b",
            "relevant_to_your_role": "r",
            "what_to_know_before_the_interview": ["k"],
            "questions_worth_asking": ["q"],
        }
    )


def _company_research() -> CompanyResearch:
    section = {"claims": [], "empty_reason": "fixture"}
    return CompanyResearch.model_validate(dict.fromkeys(CompanyResearch.model_fields, section))


def _usage() -> Usage:
    return Usage(model="m", input_tokens=1, output_tokens=1, cost=Decimal("0.01"))


def test_exactly_one_cost_channel_neither_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ResearchOutcome(
            research=_application_research(),
            sources=(),
            produced_by="provider:tavily-research",
            prompt_version="app-v1",
        )


def test_exactly_one_cost_channel_both_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ResearchOutcome(
            research=_application_research(),
            sources=(),
            produced_by="provider:tavily-research",
            prompt_version="app-v1",
            usage=_usage(),
            cost_estimate=Decimal("0.1"),
        )


def test_shape_and_version_must_pair_app_v1() -> None:
    with pytest.raises(ValueError, match="app-v1"):
        ResearchOutcome(
            research=_company_research(),
            sources=(),
            produced_by="provider:tavily-research",
            prompt_version="app-v1",
            cost_estimate=Decimal("0.1"),
        )


def test_shape_and_version_must_pair_v2_dense() -> None:
    with pytest.raises(ValueError, match="v2-dense"):
        ResearchOutcome(
            research=_application_research(),
            sources=(),
            produced_by="builtin",
            prompt_version="v2-dense",
            usage=_usage(),
        )


def test_the_two_valid_pairings_construct() -> None:
    provider = ResearchOutcome(
        research=_application_research(),
        sources=(ProviderSource(source_id="s1", url="https://x", title="t"),),
        produced_by="provider:tavily-research",
        prompt_version="app-v1",
        cost_estimate=Decimal("0.1"),
    )
    fallback = ResearchOutcome(
        research=_company_research(),
        sources=(),
        produced_by="builtin",
        prompt_version="v2-dense",
        usage=_usage(),
    )
    assert provider.sources[0].excerpt is None  # attribution by default
    assert fallback.usage is not None
