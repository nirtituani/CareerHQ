"""The six tailoring endpoints (contracts/http-api.md).

Driven over the real ASGI app with the completion seam overridden, so routing,
dependency resolution, the background task and response encoding are all
exercised — only the provider is removed (FR-045).

Two rules here are not ordinary endpoint hygiene:

* **A 422 must say *which* precondition failed.** "Run a match analysis" and
  "your profile changed, re-run it" are different actions, and a single message
  covering both makes the interface guess.
* **No `ungrounded` finding ever appears beside a surviving proposal.** The
  discard happens before persistence, so this is really a test that the route
  cannot route around `finalise` — an endpoint reading upstream of persistence
  would defeat FR-018 while every other test still passed.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.api.deps import get_structured_completion
from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import (
    MatchStatus,
    ProfessionalProfile,
    ProposalDecision,
    ResumeVersion,
    TailoringRun,
    User,
    VersionStatus,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import Seeded, seed_tailorable

pytestmark = pytest.mark.asyncio


def _plan() -> dict[str, Any]:
    return {
        "emphasise": [
            {
                "what": "Six years owning a payments platform",
                "serves_requirement": "5+ years backend services",
            }
        ],
        "de_emphasise": [],
        "protected_gaps": [
            {
                "requirement": "Kubernetes in production",
                "why_protected": "The profile mentions containers but never Kubernetes.",
            }
        ],
        "strategy": "Lead with platform ownership at scale.",
    }


def _draft(bullet_id: uuid.UUID, text: str = "Owned the payments platform for six years.") -> dict:
    return {
        "items": [
            {
                "source_item_id": str(bullet_id),
                "source_kind": "experience_bullet",
                "position": 0,
                "included": True,
                "text": text,
                "reason": "Leads with the posting's primary requirement.",
            }
        ]
    }


def _review(confidence: int, findings: list[dict] | None = None) -> dict:
    return {"confidence": confidence, "findings": findings or []}


def _clean_script(bullet_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """Plan, draft, one clean review. Three calls, no revision."""
    return {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet_id)],
        "tailor_review": [_review(90)],
    }


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


def _seam(app: Any, script: dict[str, list[dict[str, Any]]]) -> ScriptedSeam:
    """Bind one seam instance for the whole test, so calls can be counted.

    The override returns the *same* object rather than constructing one per
    request, which is what makes "rejecting triggers no AI work" checkable —
    a fresh double per request would show zero calls no matter what happened.
    """
    seam = ScriptedSeam(script=script)
    app.dependency_overrides[get_structured_completion] = lambda: seam
    return seam


async def _seeded(session: AsyncSession, **kwargs: Any) -> Seeded:
    seeded = await seed_tailorable(session, **kwargs)
    await session.commit()
    return seeded


async def _tailored(
    client: httpx.AsyncClient, app: Any, seeded: Seeded, script: dict[str, list[dict[str, Any]]]
) -> tuple[dict[str, Any], ScriptedSeam]:
    """Run one tailoring through the API and return the 202 body.

    Background tasks run inside the ASGI call, so the run has finished by the
    time this returns — which is what lets the read endpoints below be asserted
    without polling.
    """
    seam = _seam(app, script)
    response = await _as(client, seeded.user).post(
        f"/api/applications/{seeded.application.id}/tailor"
    )
    assert response.status_code == 202, response.text
    return dict(response.json()), seam


# -- POST /api/applications/{id}/tailor -------------------------------------


async def test_starting_a_run_returns_202_with_both_ids(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """FR-003. The version and the run exist before the response is sent, so
    the id in the body is immediately pollable rather than a promise."""
    seeded = await _seeded(db_session, sub="api-start", email="api-start@example.com")
    body, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))

    assert body["status"] == "tailoring"
    assert uuid.UUID(body["version_id"])
    assert uuid.UUID(body["run_id"])

    version = await db_session.get(ResumeVersion, uuid.UUID(body["version_id"]))
    assert version is not None
    run = await db_session.scalar(
        select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
    )
    assert run is not None
    assert str(run.id) == body["run_id"]


async def test_a_second_run_while_one_is_in_flight_is_409(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """FR-004. The partial unique index is the enforcement; this is its surface.

    A 202 here would let five clicks queue five runs against one job, each
    billing a provider.
    """
    seeded = await _seeded(db_session, sub="api-flight", email="api-flight@example.com")
    await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    _seam(app, _clean_script(seeded.bullet_ids[0]))
    response = await _as(client, seeded.user).post(
        f"/api/applications/{seeded.application.id}/tailor"
    )

    assert response.status_code == 409


async def test_an_unscored_job_is_422_naming_no_analysis(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    seeded = await _seeded(
        db_session,
        sub="api-unscored",
        email="api-unscored@example.com",
        analysis_status=MatchStatus.PENDING,
    )
    _seam(app, _clean_script(seeded.bullet_ids[0]))

    response = await _as(client, seeded.user).post(
        f"/api/applications/{seeded.application.id}/tailor"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "no_analysis"


async def test_a_profile_edited_since_scoring_is_422_naming_stale_analysis(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """The two 422s must be distinguishable by the client (FR-001).

    Same status code, different `reason`, because the recovery differs: one
    offers "run a match analysis", the other "re-run it".
    """
    seeded = await _seeded(db_session, sub="api-stale", email="api-stale@example.com")
    await db_session.execute(
        update(ProfessionalProfile)
        .where(ProfessionalProfile.id == seeded.profile.id)
        .values(updated_at=datetime.now(UTC) + timedelta(minutes=5))
    )
    await db_session.commit()
    _seam(app, _clean_script(seeded.bullet_ids[0]))

    response = await _as(client, seeded.user).post(
        f"/api/applications/{seeded.application.id}/tailor"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "stale_analysis"


async def test_a_job_that_is_not_yours_is_404(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    owner = await _seeded(db_session, sub="api-owner", email="api-owner@example.com")
    stranger = await _seeded(db_session, sub="api-stranger", email="api-stranger@example.com")
    _seam(app, _clean_script(owner.bullet_ids[0]))

    response = await _as(client, stranger.user).post(
        f"/api/applications/{owner.application.id}/tailor"
    )

    assert response.status_code == 404


# -- GET /api/versions/{id} -------------------------------------------------


async def test_a_running_version_has_no_items_and_no_score(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-039. The interface renders progress, not an empty diff — and an empty
    diff is exactly what "nothing changed" looks like."""
    seeded = await _seeded(db_session, sub="api-running", email="api-running@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    response = await _as(client, seeded.user).get(f"/api/versions/{version.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "tailoring"
    assert body["items"] == []
    assert body["confidence_score"] is None


async def test_a_finished_version_carries_its_items_and_provenance(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """FR-022. Every stored value reaches the screen — the check that found
    four display bugs in slice 003 which the suite could not."""
    seeded = await _seeded(db_session, sub="api-done", email="api-done@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))

    body = (await _as(client, seeded.user).get(f"/api/versions/{started['version_id']}")).json()

    assert body["status"] == "awaiting_approval"
    assert body["confidence_score"] == 90
    assert body["is_fixture"] is False
    assert body["model"]
    assert body["source_profile_updated_at"]
    assert body["items"], "a finished version with no items renders as a broken feature"

    proposed = [item for item in body["items"] if item["proposed_text"]]
    assert len(proposed) == 1
    assert proposed[0]["source_kind"] == "experience_bullet"
    assert proposed[0]["original_text"] == "Led the payments platform team for six years."
    assert proposed[0]["proposed_text"] == "Owned the payments platform for six years."
    assert proposed[0]["final_text"] == proposed[0]["proposed_text"]
    assert proposed[0]["decision"] == "pending"


async def test_findings_nest_under_the_item_they_concern(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """FR-042. A finding rendered as a page banner is unattributable — the
    reader cannot tell which of eleven proposals it objects to."""
    seeded = await _seeded(db_session, sub="api-findings", email="api-findings@example.com")
    bullet = seeded.bullet_ids[0]
    script = _clean_script(bullet)
    script["tailor_review"] = [
        _review(
            85,
            [
                {
                    "kind": "overstated",
                    "source_item_id": str(bullet),
                    "detail": "'Owned' inflates a team lead role.",
                    "quoted_text": "Owned the payments platform",
                },
                {
                    "kind": "uncovered",
                    "source_item_id": None,
                    "detail": "Kubernetes is never addressed.",
                    "quoted_text": None,
                },
            ],
        )
    ]
    started, _ = await _tailored(client, app, seeded, script)

    body = (await _as(client, seeded.user).get(f"/api/versions/{started['version_id']}")).json()

    item = next(row for row in body["items"] if row["proposed_text"])
    assert [f["kind"] for f in item["findings"]] == ["overstated"]
    assert item["findings"][0]["quoted_text"] == "Owned the payments platform"

    # `uncovered` concerns the draft as a whole and has no item to attach to.
    assert [f["kind"] for f in body["draft_findings"]] == ["uncovered"]
    assert all(f["kind"] != "uncovered" for row in body["items"] for f in row["findings"])


async def test_an_ungrounded_claim_never_reaches_the_response(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """Principle III, at the surface a person actually touches.

    The proposal was discarded before persistence, so there is nothing here to
    approve. The finding survives as evidence the guardrail ran.
    """
    seeded = await _seeded(db_session, sub="api-ungrounded", email="api-ungrounded@example.com")
    bullet = seeded.bullet_ids[0]
    fabricated = "Ran Kubernetes clusters across three regions."
    ungrounded = [
        {
            "kind": "ungrounded",
            "source_item_id": str(bullet),
            "detail": "The profile never mentions Kubernetes.",
            "quoted_text": "Ran Kubernetes clusters",
        }
    ]
    # An ungrounded finding fails the draft regardless of confidence, so the
    # loop spends its whole budget: three reviews and two revisions.
    script: dict[str, list[dict[str, Any]]] = {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet, fabricated)],
        "tailor_review": [_review(95, ungrounded) for _ in range(3)],
        "tailor_revise": [_draft(bullet, fabricated)],
        "tailor_revise_escalated": [_draft(bullet, fabricated)],
    }
    started, seam = await _tailored(client, app, seeded, script)

    body = (await _as(client, seeded.user).get(f"/api/versions/{started['version_id']}")).json()

    assert seam.times_called("tailor_revise_escalated") == 1, "the revision bound must be spent"
    for item in body["items"]:
        assert fabricated not in (item["proposed_text"] or "")
        assert fabricated not in item["final_text"]
        assert not (
            item["proposed_text"] and any(f["kind"] == "ungrounded" for f in item["findings"])
        ), "a discarded claim must not be shown beside an approve button"

    item = next(row for row in body["items"] if row["findings"])
    assert item["proposed_text"] is None
    assert item["final_text"] == item["original_text"]
    assert any(f["kind"] == "ungrounded" for f in item["findings"])


# -- PATCH /api/versions/{id}/items/{item_id} -------------------------------


async def test_the_version_serves_only_the_final_pass_s_findings(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """The version is the decision surface, and a decision is about the draft
    as it now stands.

    A pass-0 `ungrounded` finding describes a proposal the Reviser has since
    replaced; serving it under the surviving fixed proposal tells the owner
    the current wording is unsupported — and reprints the fabricated words
    (`quoted_text`) beside a valid proposal. A pass-0 `uncovered` the revision
    resolved misleads the same way at draft level. Both persist in the
    database as the audit record (the workflow suite asserts that); neither
    belongs in the version payload once a later pass has re-judged the draft.
    """
    seeded = await _seeded(db_session, sub="api-final-pass", email="api-final-pass@example.com")
    bullet = seeded.bullet_ids[0]
    fabrication = "Shipped 0-to-1 products under real ambiguity."
    fixed = "Built backend services with Python and FastAPI."
    script = {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet, fabrication)],
        "tailor_revise": [_draft(bullet, fixed)],
        "tailor_review": [
            _review(
                60,
                [
                    {
                        "kind": "ungrounded",
                        "source_item_id": str(bullet),
                        "detail": "Nothing in the profile describes ambiguity.",
                        "quoted_text": fabrication,
                    },
                    {
                        "kind": "uncovered",
                        "source_item_id": None,
                        "detail": "Kubernetes is never addressed.",
                        "quoted_text": None,
                    },
                ],
            ),
            # The revision cleared: the final pass raises nothing.
            _review(90),
        ],
    }
    started, _ = await _tailored(client, app, seeded, script)

    body = (await _as(client, seeded.user).get(f"/api/versions/{started['version_id']}")).json()

    item = next(row for row in body["items"] if str(row["source_item_id"]) == str(bullet))
    assert item["proposed_text"] == fixed
    assert item["decision"] == "pending"
    assert item["findings"] == [], (
        "a finding about wording the Reviser replaced is history, not a "
        "verdict on the surviving proposal"
    )
    assert body["draft_findings"] == []
    assert fabrication not in json.dumps(body)


async def test_accepting_takes_the_proposal(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    seeded = await _seeded(db_session, sub="api-accept", email="api-accept@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    version_id = started["version_id"]
    item = await _proposed_item(client, seeded.user, version_id)

    response = await _as(client, seeded.user).patch(
        f"/api/versions/{version_id}/items/{item['id']}", json={"decision": "accepted"}
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "accepted"
    assert response.json()["final_text"] == item["proposed_text"]


async def test_rejecting_restores_the_original_and_triggers_no_ai_work(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """FR-026. Rejecting one bullet must not silently start another run —
    a re-write on reject is a provider call the person did not ask for."""
    seeded = await _seeded(db_session, sub="api-reject", email="api-reject@example.com")
    started, seam = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    version_id = started["version_id"]
    item = await _proposed_item(client, seeded.user, version_id)
    calls_before = seam.call_count

    response = await _as(client, seeded.user).patch(
        f"/api/versions/{version_id}/items/{item['id']}", json={"decision": "rejected"}
    )

    assert response.status_code == 200
    assert response.json()["final_text"] == item["original_text"]
    assert seam.call_count == calls_before


async def test_editing_stores_the_owners_words_and_stays_distinguishable(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """FR-027. `edited` is what keeps owner-written text tellable apart from
    both the agent's proposal and the master's original."""
    seeded = await _seeded(db_session, sub="api-edit", email="api-edit@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    version_id = started["version_id"]
    item = await _proposed_item(client, seeded.user, version_id)

    response = await _as(client, seeded.user).patch(
        f"/api/versions/{version_id}/items/{item['id']}",
        json={"decision": "edited", "text": "Led payments platform work for six years."},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["decision"] == "edited"
    assert body["final_text"] == "Led payments platform work for six years."
    assert body["final_text"] not in (item["original_text"], item["proposed_text"])


async def test_an_edit_with_no_text_is_422(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    seeded = await _seeded(db_session, sub="api-blank", email="api-blank@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    version_id = started["version_id"]
    item = await _proposed_item(client, seeded.user, version_id)

    response = await _as(client, seeded.user).patch(
        f"/api/versions/{version_id}/items/{item['id']}",
        json={"decision": "edited", "text": "   "},
    )

    assert response.status_code == 422


async def test_an_unknown_decision_is_422(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """The decision vocabulary is closed. `discarded` is the *import*
    reviewer's word and must not be accepted here — two enums with one meaning
    is how the distinction between them goes quiet."""
    seeded = await _seeded(db_session, sub="api-bogus", email="api-bogus@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    version_id = started["version_id"]
    item = await _proposed_item(client, seeded.user, version_id)

    response = await _as(client, seeded.user).patch(
        f"/api/versions/{version_id}/items/{item['id']}", json={"decision": "discarded"}
    )

    assert response.status_code == 422


async def test_an_item_from_another_version_is_404(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """The item id is scoped by the version in the path, not trusted on its own."""
    seeded = await _seeded(db_session, sub="api-scope", email="api-scope@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))

    response = await _as(client, seeded.user).patch(
        f"/api/versions/{started['version_id']}/items/{uuid.uuid4()}",
        json={"decision": "accepted"},
    )

    assert response.status_code == 404


# -- POST /api/versions/{id}/approve ----------------------------------------


async def test_a_drop_is_served_decidable_and_rejecting_it_restores_inclusion(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """A drop (`included: false`) is a proposed change to existing content, so
    it must reach the client in a shape it can render as a decision (FR-024) —
    and the PATCH response must carry the restored inclusion, because the
    client swaps that object into its item list and an answer still saying
    `included: false` would render a rejection the document ignores.
    """
    seeded = await _seeded(db_session, sub="api-drop", email="api-drop@example.com")
    rewritten, dropped = seeded.bullet_ids
    draft = _draft(rewritten)
    draft["items"].append(
        {
            "source_item_id": str(dropped),
            "source_kind": "experience_bullet",
            "position": 1,
            "included": False,
        }
    )
    script = {
        "tailor_plan": [_plan()],
        "tailor_draft": [draft],
        "tailor_review": [_review(90)],
    }
    started, _ = await _tailored(client, app, seeded, script)

    me = _as(client, seeded.user)
    body = (await me.get(f"/api/versions/{started['version_id']}")).json()
    row = next(i for i in body["items"] if str(i["source_item_id"]) == str(dropped))
    assert row["proposed_text"] is None
    assert row["included"] is False
    assert row["decision"] == "pending"

    answer = await me.patch(
        f"/api/versions/{started['version_id']}/items/{row['id']}",
        json={"decision": "rejected"},
    )
    assert answer.status_code == 200
    patched = answer.json()
    assert patched["decision"] == "rejected"
    assert patched["included"] is True, "the response is what the client renders"
    assert patched["final_text"] == row["original_text"]


async def test_approving_accepts_everything_untouched_and_starts_nothing(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """FR-025 and FR-028. The import-review precedent: an untouched review adds
    everything not discarded, and approval begins no further AI work."""
    seeded = await _seeded(db_session, sub="api-approve", email="api-approve@example.com")
    started, seam = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    version_id = started["version_id"]
    calls_before = seam.call_count

    response = await _as(client, seeded.user).post(f"/api/versions/{version_id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {item["decision"] for item in body["items"]} == {"accepted"}
    assert seam.call_count == calls_before


async def test_approving_keeps_a_rejection(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """ "Everything pending counts as accepted" must not reach past a decision
    the owner already made."""
    seeded = await _seeded(db_session, sub="api-keep", email="api-keep@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    version_id = started["version_id"]
    item = await _proposed_item(client, seeded.user, version_id)
    await _as(client, seeded.user).patch(
        f"/api/versions/{version_id}/items/{item['id']}", json={"decision": "rejected"}
    )

    body = (await _as(client, seeded.user).post(f"/api/versions/{version_id}/approve")).json()

    decided = next(row for row in body["items"] if row["id"] == item["id"])
    assert decided["decision"] == "rejected"
    assert decided["final_text"] == item["original_text"]


async def test_approving_a_version_that_is_not_awaiting_approval_is_409(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seeded(db_session, sub="api-early", email="api-early@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    response = await _as(client, seeded.user).post(f"/api/versions/{version.id}/approve")

    assert response.status_code == 409


async def test_deciding_an_item_before_the_run_finishes_is_409(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The status check the contract puts here rather than in slice 006."""
    seeded = await _seeded(db_session, sub="api-tooearly", email="api-tooearly@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    response = await _as(client, seeded.user).patch(
        f"/api/versions/{version.id}/items/{uuid.uuid4()}", json={"decision": "accepted"}
    )

    assert response.status_code == 409


# -- GET /api/versions/{id}/run ---------------------------------------------


async def test_the_run_endpoint_is_the_whole_audit_record(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """Principle V, and slice 007 reads exactly this shape programmatically.

    A field missing here is a benchmark that cannot be computed later, which is
    not discoverable until the slice that needs it.
    """
    seeded = await _seeded(db_session, sub="api-audit", email="api-audit@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))

    response = await _as(client, seeded.user).get(f"/api/versions/{started['version_id']}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == started["run_id"]
    assert body["status"] == "succeeded"
    assert body["attempts"] == 0
    assert body["plan"]["strategy"] == "Lead with platform ownership at scale."
    assert body["finalisation_rules_version"]
    assert body["models"]["tailor_review"] != body["models"]["tailor_draft"], (
        "the Reviewer runs on the stronger model (docs/08 §3.2.3); "
        "identical entries mean the per-task configuration is not being read"
    )
    assert body["input_tokens"] == 3000
    assert body["output_tokens"] == 1500
    # A Decimal audit value, as a string. A float here would drift.
    assert body["cost"] == "0.030000"
    assert body["is_fixture"] is False
    assert body["started_at"] and body["finished_at"]

    # FR-016: every guideline the run consumed, each with its source. Slice 006
    # replaces the source; the field is what makes the swap measurable.
    assert body["guidelines_used"]
    assert all(g["source"] for g in body["guidelines_used"])


async def test_a_failed_run_says_why(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """There is no `failed` version status — the version returns to `draft` and
    the run carries the explanation. Without this endpoint that reason is
    unreachable, and the interface can only say "nothing happened"."""
    seeded = await _seeded(db_session, sub="api-failed", email="api-failed@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        # An empty script: the first call raises, which is what a provider
        # outage looks like from inside the graph.
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script={}),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    body = (await _as(client, seeded.user).get(f"/api/versions/{version.id}/run")).json()
    assert body["status"] == "failed"
    assert body["failure_reason"]

    version_body = (await _as(client, seeded.user).get(f"/api/versions/{version.id}")).json()
    assert version_body["status"] == "draft"
    assert version_body["failure_reason"]


# -- GET /api/applications/{id}/versions ------------------------------------


async def test_versions_are_listed_newest_first(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    seeded = await _seeded(db_session, sub="api-list", email="api-list@example.com")
    first, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))
    await _as(client, seeded.user).post(f"/api/versions/{first['version_id']}/approve")
    second, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))

    response = await _as(client, seeded.user).get(
        f"/api/applications/{seeded.application.id}/versions"
    )

    assert response.status_code == 200
    rows = response.json()["versions"]
    assert [row["id"] for row in rows] == [second["version_id"], first["version_id"]]
    assert rows[0]["name"] and rows[0]["status"] and rows[0]["created_at"]
    assert rows[0]["confidence_score"] == 90


async def test_a_job_with_no_versions_lists_none(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Empty is an ordinary answer, not a 404."""
    seeded = await _seeded(db_session, sub="api-empty", email="api-empty@example.com")

    response = await _as(client, seeded.user).get(
        f"/api/applications/{seeded.application.id}/versions"
    )

    assert response.status_code == 200
    assert response.json()["versions"] == []


# -- the enum trap slice 004 shipped ----------------------------------------


async def test_approval_works_when_the_version_is_read_by_a_fresh_session(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """Status and decision columns are `String`, so a row loaded in a session
    that did not create it returns a plain `str`. An `is` comparison against
    the enum member then never matches, nothing raises, and the whole endpoint
    quietly does nothing — which is exactly how slice 004's analyses sat
    `pending` forever under 270 green tests.

    The route is the fresh session, so this asserts the real path rather than
    the one the writing test happens to hold open.
    """
    seeded = await _seeded(db_session, sub="api-fresh", email="api-fresh@example.com")
    started, _ = await _tailored(client, app, seeded, _clean_script(seeded.bullet_ids[0]))

    await _as(client, seeded.user).post(f"/api/versions/{started['version_id']}/approve")

    async with db_session.begin_nested():
        pass
    version = await db_session.get(
        ResumeVersion, uuid.UUID(started["version_id"]), populate_existing=True
    )
    assert version is not None
    await db_session.refresh(version, ["items"])
    assert version.status == VersionStatus.READY
    assert [item.decision for item in version.items] == [
        ProposalDecision.ACCEPTED for _ in version.items
    ]


async def _proposed_item(client: httpx.AsyncClient, user: User, version_id: str) -> dict[str, Any]:
    body = (await _as(client, user).get(f"/api/versions/{version_id}")).json()
    return next(item for item in body["items"] if item["proposed_text"])


# -- T090: what a failure is allowed to say ---------------------------------


async def test_a_failure_names_its_kind_to_the_owner_and_its_detail_to_the_log(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Found by the T090 security review, and it was the wrong way round.

    `run_tailoring` wrote `f"{type(exc).__name__}: {exc}"` into two columns that
    two endpoints return verbatim and the interface renders in an alert, while
    logging only the exception's class. The detail went to the browser and the
    type went to the operator — precisely inverted from the rule `health.py`
    established under T068.

    It is not hypothetical. A `psycopg.OperationalError` stringifies to
    `connection to server at "172.19.0.4", port 5432 failed: FATAL: password
    authentication failed for user "careerhq"` — the internal address, port and
    database user, on screen.

    So this asserts both halves: the secret is absent from the response **and**
    present in the log. Asserting only the first would pass against a fix that
    threw the detail away, which trades a disclosure for an undebuggable
    failure.
    """
    secret = 'connection to server at "172.19.0.4", port 5432 failed: user "careerhq"'

    class _Exploding:
        async def complete(self, *, task: str, schema: Any, prompt: str) -> Any:
            raise RuntimeError(secret)

    seeded = await _seeded(db_session, sub="api-leak", email="api-leak@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    with caplog.at_level(logging.WARNING, logger="careerhq.application.tailor_resume"):
        async with session_factory() as session:
            await run_tailoring(
                session,
                version_id=version.id,
                completion=_Exploding(),  # type: ignore[arg-type]
                guidelines=StaticGuidelines(),
            )
            await session.commit()

    body = (await _as(client, seeded.user).get(f"/api/versions/{version.id}")).json()
    run_body = (await _as(client, seeded.user).get(f"/api/versions/{version.id}/run")).json()

    # Nothing the driver said reaches the caller, through either endpoint.
    assert secret not in json.dumps(body)
    assert secret not in json.dumps(run_body)
    assert "172.19.0.4" not in json.dumps(body) + json.dumps(run_body)

    # The owner still learns what happened and what to do about it, and the run
    # still names the class — enough for a support conversation without a trace.
    assert body["failure_reason"]
    assert body["failure_reason"] == "The tailoring run stopped before it finished."
    assert run_body["failure_reason"] == "RuntimeError"

    # And the operator keeps the detail. In `extra={}` rather than the message,
    # because Railway blanks the message field of parsed JSON logs.
    assert any(secret in str(getattr(record, "detail", "")) for record in caplog.records), (
        "the detail must survive somewhere an operator can read it"
    )


async def test_a_validation_failure_does_not_leak_the_model_output_into_the_log(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Found while verifying the T090 fix, in the log it had just written.

    `str(ValidationError)` embeds `input_value=` — so logging `str(exc)`
    reinstated, one layer up, exactly the model output the gateway strips from
    its own record. The gateway's guarantee was real and bypassable.

    Both logs now use the same extractor: field paths and constraint types, and
    our own validator sentences, never the value.
    """
    invented = "Ran Kubernetes clusters for the Ministry of Fabricated Experience"

    class _Rejecting:
        """Returns a well-formed object whose *content* fails validation, the
        way a real provider does — not a transport error."""

        async def complete(self, *, task: str, schema: Any, prompt: str) -> Any:
            from careerhq.domain.schemas.tailoring import TailoringPlan

            TailoringPlan.model_validate({"strategy": invented})  # raises
            raise AssertionError("unreachable")

    seeded = await _seeded(db_session, sub="api-noleak", email="api-noleak@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    with caplog.at_level(logging.WARNING, logger="careerhq.application.tailor_resume"):
        async with session_factory() as session:
            await run_tailoring(
                session,
                version_id=version.id,
                completion=_Rejecting(),  # type: ignore[arg-type]
                guidelines=StaticGuidelines(),
            )
            await session.commit()

    logged = " ".join(f"{r.getMessage()} {getattr(r, 'detail', '')}" for r in caplog.records)
    assert invented not in logged
    assert "input_value" not in logged
    # Still names the field and the constraint.
    assert "emphasise" in logged


async def test_the_run_endpoint_reports_how_much_of_the_plan_was_carried_out(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """Reported per run so evidence accumulates without anyone re-deriving it.

    **Deliberately not a gate.** Two real runs disagreed sharply — eight planned
    emphases and four rewrites on one job, six and one on another — and a
    threshold chosen from two samples would encode a guess as a rule. Slice 007
    is what turns a distribution into a judgement; this only makes sure there is
    a distribution to look at.
    """
    seeded = await _seeded(db_session, sub="api-adherence", email="api-adherence@example.com")
    bullet = seeded.bullet_ids[0]

    script = _clean_script(bullet)
    # A plan naming two facts; the draft rewrites one of them.
    script["tailor_plan"] = [
        {
            "emphasise": [
                {
                    "source_item_id": str(bullet),
                    "what": "Six years owning a payments platform",
                    "serves_requirement": "5+ years backend services",
                },
                {
                    "source_item_id": str(seeded.skill_ids[0]),
                    "what": "Python",
                    "serves_requirement": "Python",
                },
            ],
            "de_emphasise": [],
            "protected_gaps": [],
            "strategy": "Lead with platform ownership.",
        }
    ]
    started, _ = await _tailored(client, app, seeded, script)

    body = (await _as(client, seeded.user).get(f"/api/versions/{started['version_id']}/run")).json()

    adherence = body["plan_adherence"]
    assert adherence["planned"] == 2
    assert adherence["with_ids"] == 2
    assert adherence["executed"] == 1
    assert adherence["adherence"] == 0.5
    assert adherence["unexecuted_ids"] == [str(seeded.skill_ids[0])]


async def test_a_failed_run_reports_adherence_without_a_plan(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A run that died before planning still has to answer the endpoint."""
    seeded = await _seeded(db_session, sub="api-noplan", email="api-noplan@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script={}),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    body = (await _as(client, seeded.user).get(f"/api/versions/{version.id}/run")).json()

    assert body["plan_adherence"]["planned"] == 0
    assert body["plan_adherence"]["adherence"] is None


async def test_the_payload_says_which_items_were_reordered(
    client: httpx.AsyncClient, db_session: AsyncSession, app: Any
) -> None:
    """A position-only proposal moves a line in the rendered document, so the
    interface must be able to say so — without `displaced_position` it counted
    a moved item as "left unchanged", which is a false statement about the
    resume the person is approving. Ordering itself is approved at version
    level (FR-025); this serves the *fact*, not a new per-item decision.
    """
    seeded = await _seeded(db_session, sub="api-reorder", email="api-reorder@example.com")
    rewritten, moved = seeded.bullet_ids
    draft = _draft(rewritten)
    draft["items"].append(
        {
            "source_item_id": str(moved),
            "source_kind": "experience_bullet",
            "position": 0,
            "included": True,
            # No text: a pure reorder.
        }
    )
    script = {
        "tailor_plan": [_plan()],
        "tailor_draft": [draft],
        "tailor_review": [_review(90)],
    }
    started, _ = await _tailored(client, app, seeded, script)

    body = (await _as(client, seeded.user).get(f"/api/versions/{started['version_id']}")).json()
    row = next(i for i in body["items"] if str(i["source_item_id"]) == str(moved))
    assert row["proposed_text"] is None and row["included"] is True
    assert row["displaced_position"] is not None, (
        "the one record that the draft moved this item must reach the client"
    )
    untouched = next(
        i
        for i in body["items"]
        if i["proposed_text"] is None
        and str(i["source_item_id"]) not in (str(moved), str(rewritten))
    )
    assert untouched["displaced_position"] is None
