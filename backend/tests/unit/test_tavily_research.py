"""The Tavily Research adapter, tested against the request it actually builds.

Everything here asserts on **what the capturing double received or returned**,
never on the adapter's constants (testing rule: a double fed by someone who
read the code proves plumbing, not behaviour — so the double captures, and the
assertions read the capture).

Response fixtures are shaped like the POC's recorded responses: `content` came
back both as an object and as a JSON string across runs, and both must map.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from careerhq.application.ports import (
    ProviderSource,
    ResearchOutcome,
    ResearchProviderRejected,
    ResearchProviderUnavailable,
)
from careerhq.config import get_settings
from careerhq.infrastructure.research.tavily_research import TavilyResearch

JD = "Join our Parking Domain at Pango. Python, AWS, DynamoDB. Petah Tikva."


def _content() -> dict[str, Any]:
    return {
        "company_identification": {
            "official_name": "Pango Pay & Go Ltd.",
            "website": "https://www.pango.co.il",
            "headquarters": "Petah Tikva, Israel",
            "how_identified": "Matched the posting's location and parking domain.",
        },
        "company_overview": "An Israeli smart-mobility company.",
        "products_and_services": "Mobile parking payments.",
        "business_and_market": "Transaction-fee SaaS; owned by Milgam (2024 reporting).",
        "relevant_to_your_role": "Python and AWS at scale on the Parking team.",
        "what_to_know_before_the_interview": ["Owned by Milgam and Unicell."],
        "questions_worth_asking": ["How is DynamoDB scaled for peak traffic?"],
    }


def _response(content: Any) -> dict[str, Any]:
    return {
        "request_id": "req-1",
        "status": "completed",
        "content": content,
        "sources": [
            {"title": "Pango on LinkedIn", "url": "https://linkedin.com/company/pango"},
            {"title": "Crunchbase", "url": "https://crunchbase.com/organization/pango"},
        ],
    }


class CapturingPost:
    """Answers once with a canned payload and remembers what was asked."""

    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self.payload = payload
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(body)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


async def _run(post: CapturingPost, **overrides: Any) -> ResearchOutcome:
    adapter = TavilyResearch(post=post)
    kwargs: dict[str, Any] = {
        "company_name": "Pango",
        "domain": None,
        "role_title": "Senior Back End Developer - Parking Team",
        "posting_text": JD,
    }
    kwargs.update(overrides)
    return await adapter.research(**kwargs)


async def test_a_successful_response_maps_to_a_provider_outcome() -> None:
    post = CapturingPost(_response(_content()))
    outcome = await _run(post)

    assert outcome.prompt_version == "app-v1"
    assert outcome.produced_by == "provider:tavily-research"
    assert outcome.usage is None
    assert isinstance(outcome.cost_estimate, Decimal)
    assert outcome.cost_estimate > 0
    # Sources: minted ids, attribution only — no excerpts a verifier never saw.
    assert [source.source_id for source in outcome.sources] == ["s1", "s2"]
    assert all(source.excerpt is None for source in outcome.sources)
    assert all(isinstance(source, ProviderSource) for source in outcome.sources)
    # The estimate's basis facts travel with the run, for the audit trail.
    assert "credits_documented_range" in outcome.run_facts


async def test_content_arriving_as_a_json_string_also_maps() -> None:
    post = CapturingPost(_response(json.dumps(_content())))
    outcome = await _run(post)
    assert outcome.prompt_version == "app-v1"


async def test_schema_violating_output_is_rejected_not_partially_accepted() -> None:
    broken = _content()
    del broken["company_identification"]
    post = CapturingPost(_response(broken))
    with pytest.raises(ResearchProviderRejected):
        await _run(post)


async def test_transport_failure_is_unavailable() -> None:
    post = CapturingPost(ConnectionError("boom"))
    with pytest.raises(ResearchProviderUnavailable):
        await _run(post)


async def test_without_a_key_the_real_post_refuses_before_any_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    # A developer machine's .env can carry a real key; the refusal under test
    # is the no-key path, so the file must not answer for the environment.
    monkeypatch.setattr("careerhq.config.Settings.model_config", {"env_file": None})
    get_settings.cache_clear()
    try:
        assert get_settings().tavily_api_key is None, "key still visible; isolation failed"
        with pytest.raises(ResearchProviderUnavailable):
            await TavilyResearch().research(
                company_name="Pango", domain=None, role_title=None, posting_text=None
            )
    finally:
        get_settings.cache_clear()


async def test_the_request_carries_the_contract() -> None:
    """The request body IS the prompt-side contract: mini tier, our output
    schema with its descriptions, untrusted framing, and the three D4 clauses
    each earned by a measured POC failure."""
    post = CapturingPost(_response(_content()))
    await _run(post)

    (body,) = post.bodies
    assert body["model"] == "mini"
    assert body["citation_format"] == "numbered"
    schema = body["output_schema"]
    assert "company_identification" in schema["properties"]

    prompt = body["input"]
    # Entity resolution: same-named companies must be excluded (Pango mixing).
    assert "same name" in prompt or "same or a similar name" in prompt
    # Primary-source preference (the Silverfort data-broker HQ error).
    assert "primary sources" in prompt
    # Dated claims (the 2014/2024 news blending).
    assert "date" in prompt.lower()
    # Untrusted-data framing for the posting (FR-019), and the posting present.
    assert "data to research" in prompt or "as data" in prompt
    assert JD in prompt
    assert "Senior Back End Developer" in prompt


async def test_a_long_posting_is_truncated_from_the_end_and_recorded() -> None:
    limit = get_settings().research_posting_max_chars
    long_posting = "requirements first. " + ("x" * limit)
    post = CapturingPost(_response(_content()))
    outcome = await _run(post, posting_text=long_posting)

    (body,) = post.bodies
    sent = long_posting[:limit]
    assert sent in body["input"]
    assert long_posting not in body["input"]
    # The head survives — requirements concentrate early (C4).
    assert "requirements first." in body["input"]
    assert outcome.run_facts["posting_truncated"] is True
    assert outcome.run_facts["posting_chars_sent"] == limit


async def test_an_untruncated_posting_records_nothing_about_truncation() -> None:
    post = CapturingPost(_response(_content()))
    outcome = await _run(post)
    assert "posting_truncated" not in outcome.run_facts


# -- US2: no posting means honest company-only research (T022) ---------------


async def test_without_a_posting_the_request_asks_for_company_only_research() -> None:
    """D7: the input carries no role framing at all — no posting block, no
    target position — and explicitly instructs company-only research with the
    absence stated rather than a role guessed."""
    post = CapturingPost(_response(_content()))
    await _run(post, role_title=None, posting_text=None)

    (body,) = post.bodies
    prompt = body["input"]
    assert "JOB POSTING" not in prompt
    assert "TARGET POSITION" not in prompt
    assert "No job posting was provided" in prompt
    assert "invent a role" in prompt  # the clause wraps across a line in the template


async def test_without_a_posting_nothing_records_a_truncation() -> None:
    post = CapturingPost(_response(_content()))
    outcome = await _run(post, role_title=None, posting_text=None)
    assert "posting_truncated" not in outcome.run_facts


async def test_the_output_schema_is_inlined_to_what_the_provider_accepts() -> None:
    """Found by the Docker verification, not by any double: the endpoint 400s
    on anything but `properties` + `required` at the top level — no `$defs`,
    no `$ref`, no `title`, no top-level `type` — while pydantic's
    `model_json_schema()` emits all four. The adapter must inline the schema,
    keeping every description (they are the prompt-side contract)."""
    post = CapturingPost(_response(_content()))
    await _run(post)

    (body,) = post.bodies
    schema = body["output_schema"]
    assert set(schema.keys()) <= {"properties", "required"}, sorted(schema.keys())

    flattened = json.dumps(schema)
    assert "$ref" not in flattened and "$defs" not in flattened

    # The nested identification survived inlining, descriptions intact, and
    # the nullable field collapsed to its base type.
    ident = schema["properties"]["company_identification"]
    assert ident["type"] == "object"
    assert ident["properties"]["how_identified"]["description"]
    assert ident["properties"]["headquarters"].get("type") == "string"
    assert "anyOf" not in json.dumps(ident)


class PendingThenDone:
    """POST answers a pending envelope; GET serves the finished record.

    Found by the Docker verification: the endpoint answers `status: "pending"`
    in under a second and the result must be fetched by request id — the POC
    harness polled, the first adapter did not.
    """

    def __init__(self, final: dict[str, Any], *, pending_polls: int = 1) -> None:
        self.final = final
        self.pending_polls = pending_polls
        self.bodies: list[dict[str, Any]] = []
        self.polled: list[str] = []

    async def post(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(body)
        return {"request_id": "req-42", "status": "pending"}

    async def get(self, request_id: str) -> dict[str, Any]:
        self.polled.append(request_id)
        if len(self.polled) <= self.pending_polls:
            return {"request_id": request_id, "status": "pending"}
        return self.final


async def test_a_pending_envelope_is_polled_to_completion() -> None:
    double = PendingThenDone(_response(_content()))
    adapter = TavilyResearch(post=double.post, get=double.get, poll_seconds=0)
    outcome = await adapter.research(
        company_name="Pango", domain=None, role_title=None, posting_text=None
    )
    assert outcome.prompt_version == "app-v1"
    assert double.polled == ["req-42", "req-42"]


async def test_a_provider_side_failure_is_unavailable_with_its_bill() -> None:
    double = PendingThenDone({"request_id": "req-42", "status": "failed"}, pending_polls=0)
    adapter = TavilyResearch(post=double.post, get=double.get, poll_seconds=0)
    with pytest.raises(ResearchProviderUnavailable) as caught:
        await adapter.research(
            company_name="Pango", domain=None, role_title=None, posting_text=None
        )
    # The provider may have billed for the failed run; the estimate travels.
    assert caught.value.cost_estimate is not None
