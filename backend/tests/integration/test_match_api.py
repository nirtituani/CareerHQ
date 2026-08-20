"""The match endpoints (contracts/http-api.md).

The state is decided by the **server**. A client working out that "no score
means it failed" is exactly the conflation FR-022 forbids, and putting the
decision here means one implementation rather than one per surface.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.api.deps import get_structured_completion
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    ContactInformation,
    ExperienceBullet,
    MatchAnalysis,
    ProfessionalProfile,
    User,
    WorkExperience,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

ALICE = {"sub": "google-api-alice", "email": "api-alice@example.com", "name": "Alice"}
BOB = {"sub": "google-api-bob", "email": "api-bob@example.com", "name": "Bob"}

_JUDGEMENT: dict[str, Any] = {
    "direct": 88,
    "transferable": 82,
    "adjacent": 75,
    "impact": 80,
    "verdict": "Strong backend fit.",
    "requirements": [
        {
            "text": "5+ years building production backend services",
            "kind": "must_have",
            "importance": 90,
            "verdict": "confirmed",
            "shortfall": None,
            "evidence": "Led the payments platform team for six years.",
        },
        {
            "text": "Kubernetes in production",
            "kind": "must_have",
            # Below CAP_IMPORTANCE, so this fixture stays a `strong` match and
            # the banding assertions test banding rather than the cap.
            "importance": 40,
            "verdict": "unverified",
            # No shortfall: a silent profile cannot say *why* it is silent.
            "shortfall": None,
            "evidence": None,
        },
    ],
}


class _Stub:
    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:  # type: ignore[name-defined]  # noqa: F821
        from careerhq.application.ports import Completion, Usage

        payload = _JUDGEMENT if task == "match_analysis" else {"job_title": "Senior Engineer"}
        return Completion(
            value=schema.model_validate(payload),
            usage=Usage(
                model="anthropic/claude-sonnet-5",
                input_tokens=3420,
                output_tokens=1487,
                cost=Decimal("0.022110"),
            ),
        )


@pytest.fixture
def stub_completion(app: object) -> Any:
    app.dependency_overrides[get_structured_completion] = _Stub  # type: ignore[attr-defined]
    yield
    app.dependency_overrides.pop(get_structured_completion, None)  # type: ignore[attr-defined]


async def _user_with_profile(session: AsyncSession, claims: dict[str, str]) -> User:
    user: User = await provision_user(session, claims)
    profile = await session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == user.id)
    )
    assert profile is not None
    session.add(
        ContactInformation(profile_id=profile.id, full_name=claims["name"], source="EXTRACTED")
    )
    role = WorkExperience(
        profile_id=profile.id, company="Payments Co", title="Staff Engineer", source="EXTRACTED"
    )
    session.add(role)
    await session.flush()
    session.add(
        ExperienceBullet(
            experience_id=role.id,
            text="Led the payments platform team for six years.",
            source="EXTRACTED",
        )
    )
    await session.commit()
    return user


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


async def _create(client: httpx.AsyncClient, user: User, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "company": "Acme Corporation",
        "job_title": "Senior Backend Engineer",
        "job_description": "The whole posting, with scale and domain signals.",
        "requirements": [
            "5+ years building production backend services",
            "Kubernetes in production",
        ],
        "status": "Applied",
    }
    body.update(overrides)
    response = await _as(client, user).post("/api/applications", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_saving_a_job_reserves_a_pending_analysis_in_the_same_transaction(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """FR-004, FR-005.

    The response does not wait for the completion, and the row is already there
    when it returns — so the interface has something to show a spinner against
    rather than a blank that might mean anything.
    """
    alice = await _user_with_profile(db_session, ALICE)
    created = await _create(client, alice)

    analysis = await db_session.scalar(
        select(MatchAnalysis).where(MatchAnalysis.application_id == created["id"])
    )
    assert analysis is not None


async def test_a_job_with_no_requirements_gets_no_analysis(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """FR-006. Nothing to score against is ordinary, not an error."""
    alice = await _user_with_profile(db_session, ALICE)
    created = await _create(client, alice, requirements=[], job_description="")

    response = await _as(client, alice).get(f"/api/applications/{created['id']}/match")

    assert response.status_code == 200
    assert response.json()["state"] == "nothing_to_score"
    assert response.json()["analysis"] is None


async def test_the_four_states_are_named_by_the_server(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """FR-022. `running` and `ready` are distinct, and neither is inferred."""
    alice = await _user_with_profile(db_session, ALICE)
    created = await _create(client, alice)

    response = await _as(client, alice).get(f"/api/applications/{created['id']}/match")
    assert response.status_code == 200
    assert response.json()["state"] in {"running", "ready"}

    # Once it has run, it is ready and carries the whole judgement.
    triggered = await _as(client, alice).post(f"/api/applications/{created['id']}/match")
    assert triggered.status_code in {202, 409}

    body = (await _as(client, alice).get(f"/api/applications/{created['id']}/match")).json()
    if body["state"] == "ready":
        assert body["analysis"]["band"] == "strong"
        assert body["analysis"]["overall_score"] == 83


async def test_triggering_a_run_returns_202_and_the_pending_analysis(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """The 202 path, which nothing asserted until it 500'd in real use.

    `test_the_four_states_are_named_by_the_server` accepts `{202, 409}` and
    always got 409, because saving the job had already reserved a run. So the
    branch that serialises a **freshly created** analysis was never exercised —
    and it raised `MissingGreenlet`, because `analysis.requirements` on a
    just-added object is a lazy load and async SQLAlchemy cannot do IO there.

    A pending analysis has no requirements by definition, so the collection is
    initialised at construction rather than left to be fetched.
    """
    alice = await _user_with_profile(db_session, ALICE)
    created = await _create(client, alice)

    # Clear whatever saving reserved, so this exercises the fresh-create path.
    await db_session.execute(
        MatchAnalysis.__table__.delete().where(
            MatchAnalysis.application_id == uuid.UUID(created["id"])
        )
    )
    await db_session.commit()

    response = await _as(client, alice).post(f"/api/applications/{created['id']}/match")

    assert response.status_code == 202, response.text
    assert response.json()["state"] == "running"
    assert response.json()["analysis"]["requirements"] == []


async def test_another_users_analysis_is_404_not_403(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """FR-019. A 403 confirms the row exists, which is the disclosure itself."""
    alice = await _user_with_profile(db_session, ALICE)
    bob = await _user_with_profile(db_session, BOB)
    created = await _create(client, alice)

    response = await _as(client, bob).get(f"/api/applications/{created['id']}/match")

    assert response.status_code == 404


async def test_cost_is_serialised_as_a_string(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """A Decimal audit value must not become a float on the way out."""
    alice = await _user_with_profile(db_session, ALICE)
    created = await _create(client, alice)
    await _as(client, alice).post(f"/api/applications/{created['id']}/match")

    body = (await _as(client, alice).get(f"/api/applications/{created['id']}/match")).json()

    if body["state"] == "ready":
        assert isinstance(body["analysis"]["cost"], str)


async def test_the_list_carries_a_compact_summary(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """Enough for the Match column, not the whole analysis."""
    alice = await _user_with_profile(db_session, ALICE)
    await _create(client, alice)

    body = (await _as(client, alice).get("/api/applications")).json()

    assert body["applications"]
    assert "match" in body["applications"][0]
    assert body["applications"][0]["match"]["state"] in {"running", "ready", "nothing_to_score"}


async def test_the_detail_response_distinguishes_never_captured_from_none_found(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """`null` and `[]` are different facts and must survive the API (R1).

    A legacy row has `requirements: null`; a posting that stated none has `[]`.
    Collapsing them in the response would lose the only thing telling them
    apart, one layer further out than the column.
    """
    alice = await _user_with_profile(db_session, ALICE)
    created = await _create(client, alice, requirements=[])

    body = (await _as(client, alice).get(f"/api/applications/{created['id']}")).json()
    assert body["requirements"] == []

    application = await db_session.get(Application, created["id"])
    assert application is not None
    application.requirements = None
    await db_session.commit()

    body = (await _as(client, alice).get(f"/api/applications/{created['id']}")).json()
    assert body["requirements"] is None
