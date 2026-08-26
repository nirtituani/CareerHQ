"""T055 — ownership comes from the session, and never from the request.

Six routes is the largest surface this project has added at once since slice
003, and all six take an id from the URL. That is precisely the shape where an
ownership check gets forgotten on one endpoint out of six and nothing notices,
because the other five are covered and the suite is green.

So this file checks **every** route rather than a sample, and checks two
different things about each:

* **Another owner's resource is 404, not 403.** A 403 confirms the id names
  something real, which is the disclosure the rule exists to prevent. Handing a
  stranger a working oracle for "does this version id exist" is a slower leak
  than handing them the version, not a smaller one.
* **No route has an owner to supply.** The behavioural checks below would still
  pass if a route read `user_id` from the body and merely happened to be given
  the right one, so the structural check at the end reads the published schema —
  which lists exactly what a client may send, and nothing else.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.api.routes import tailoring
from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import ResumeVersion, User
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import Seeded, seed_tailorable

pytestmark = pytest.mark.asyncio

#: Anything a client might hope names an owner. None of these may be read.
OWNER_FIELDS = ("user_id", "profile_id", "owner_id", "owner", "user")


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


def _script(bullet_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    return {
        "tailor_plan": [
            {
                "emphasise": [
                    {
                        "what": "Six years owning a payments platform",
                        "serves_requirement": "5+ years backend services",
                    }
                ],
                "de_emphasise": [],
                "protected_gaps": [],
                "strategy": "Lead with platform ownership at scale.",
            }
        ],
        "tailor_draft": [
            {
                "items": [
                    {
                        "source_item_id": str(bullet_id),
                        "source_kind": "experience_bullet",
                        "position": 0,
                        "included": True,
                        "text": "Owned the payments platform for six years.",
                        "reason": "Leads with the posting's primary requirement.",
                    }
                ]
            }
        ],
        "tailor_review": [{"confidence": 90, "findings": []}],
    }


async def _finished_version(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    seeded: Seeded,
) -> ResumeVersion:
    """A version belonging to `seeded`, taken all the way to awaiting approval.

    Driven through the use case rather than the API, so this file's subject is
    ownership rather than the workflow.
    """
    version = await create_pending_version(session, seeded.application)
    await session.commit()
    async with session_factory() as worker:
        await run_tailoring(
            worker,
            version_id=version.id,
            completion=ScriptedSeam(script=_script(seeded.bullet_ids[0])),
            guidelines=StaticGuidelines(),
        )
        await worker.commit()
    return version


@pytest.fixture
async def two_users(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]:
    """An owner with a finished version, and a stranger with their own job."""
    owner = await seed_tailorable(db_session, sub="own-owner", email="own-owner@example.com")
    stranger = await seed_tailorable(
        db_session, sub="own-stranger", email="own-stranger@example.com"
    )
    await db_session.commit()

    version = await _finished_version(db_session, session_factory, owner)
    item_id = await _proposed_item_id(session_factory, version.id)
    return owner, stranger, version, item_id


async def _proposed_item_id(
    session_factory: async_sessionmaker[AsyncSession], version_id: uuid.UUID
) -> uuid.UUID:
    """One item id from the finished version, for the PATCH routes."""
    from sqlalchemy import select

    from careerhq.domain.models import ResumeVersionItem

    async with session_factory() as session:
        item = await session.scalar(
            select(ResumeVersionItem)
            .where(ResumeVersionItem.resume_version_id == version_id)
            .where(ResumeVersionItem.proposed_text.is_not(None))
        )
        assert item is not None
        return item.id


# -- another owner's resource is 404 on every route -------------------------


async def test_a_stranger_cannot_read_a_version(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    _, stranger, version, _ = two_users
    response = await _as(client, stranger.user).get(f"/api/versions/{version.id}")
    assert response.status_code == 404


async def test_a_stranger_cannot_read_the_run(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    """The audit record names the model, the cost and the plan. It is the most
    disclosive of the six and the easiest one to forget to scope."""
    _, stranger, version, _ = two_users
    response = await _as(client, stranger.user).get(f"/api/versions/{version.id}/run")
    assert response.status_code == 404


async def test_a_stranger_cannot_decide_someone_elses_item(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    _, stranger, version, item_id = two_users
    response = await _as(client, stranger.user).patch(
        f"/api/versions/{version.id}/items/{item_id}", json={"decision": "accepted"}
    )
    assert response.status_code == 404


async def test_a_stranger_cannot_approve_someone_elses_version(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    _, stranger, version, _ = two_users
    response = await _as(client, stranger.user).post(f"/api/versions/{version.id}/approve")
    assert response.status_code == 404


async def test_a_stranger_cannot_start_a_run_on_someone_elses_job(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    owner, stranger, _, _ = two_users
    response = await _as(client, stranger.user).post(
        f"/api/applications/{owner.application.id}/tailor"
    )
    assert response.status_code == 404


async def test_a_stranger_cannot_list_someone_elses_versions(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    """A count is a disclosure too: "this job has three tailored versions" says
    how hard someone is trying, about a job they never shared."""
    owner, stranger, _, _ = two_users
    response = await _as(client, stranger.user).get(
        f"/api/applications/{owner.application.id}/versions"
    )
    assert response.status_code == 404


async def test_the_refusal_is_404_and_not_403(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    """A 403 distinguishes "exists, not yours" from "does not exist", which
    turns any of these endpoints into an oracle for guessing ids."""
    _, stranger, version, _ = two_users

    real = await _as(client, stranger.user).get(f"/api/versions/{version.id}")
    imaginary = await _as(client, stranger.user).get(f"/api/versions/{uuid.uuid4()}")

    assert real.status_code == imaginary.status_code == 404
    assert real.json()["detail"] == imaginary.json()["detail"]


# -- no route has an owner to supply ----------------------------------------


async def test_an_owner_field_in_the_body_is_ignored(
    client: httpx.AsyncClient, two_users: tuple[Seeded, Seeded, ResumeVersion, uuid.UUID]
) -> None:
    """The only route taking a body is PATCH, and it must read nothing but the
    decision. A body-supplied owner that *happened* to be correct would pass
    every test above while the check was doing nothing."""
    owner, stranger, version, item_id = two_users

    response = await _as(client, stranger.user).patch(
        f"/api/versions/{version.id}/items/{item_id}",
        json={"decision": "accepted"} | {field: str(owner.user.id) for field in OWNER_FIELDS},
    )

    assert response.status_code == 404


async def test_no_tailoring_route_accepts_an_owner_parameter(app: Any) -> None:
    """Read the published schema, because the behavioural tests cannot see this.

    A route growing an `owner_id` query parameter would be caught here and
    nowhere else — every test above would still pass, since none of them sends
    one.

    **The OpenAPI schema is the right place to look**, and the signature is not.
    Every one of these endpoints has a `user` parameter and must: it is
    `CurrentUser`, a dependency resolved from the session cookie. Reading the
    signature cannot tell that apart from an argument a client sets, and a check
    that cannot tell them apart either fails on all six or passes on all six.
    The schema lists exactly what a client may send, which is the actual claim.
    """
    tailoring_paths = {
        path
        for path in app.openapi()["paths"]
        if path.startswith("/api/versions/") or path.endswith(("/tailor", "/versions"))
    }
    assert len(tailoring_paths) == 6, (
        f"expected the six contracted paths, found {sorted(tailoring_paths)}"
    )

    offenders: list[str] = []
    for path in tailoring_paths:
        for method, operation in app.openapi()["paths"][path].items():
            for parameter in operation.get("parameters", []):
                if parameter["name"] in OWNER_FIELDS:
                    offenders.append(f"{method.upper()} {path} ({parameter['name']})")

    assert not offenders, f"routes taking a client-supplied owner: {offenders}"


async def test_the_six_contracted_routes_all_exist() -> None:
    """T054's count, asserted rather than eyeballed.

    The contract and `tasks.md` disagreed about this once — five routes against
    six — and `/speckit-analyze` is what caught it. A number in prose is not
    checkable; this is.
    """
    registered = {
        (sorted(route.methods)[0], route.path)  # type: ignore[attr-defined]
        for route in tailoring.router.routes
    }
    assert registered == {
        ("POST", "/applications/{application_id}/tailor"),
        ("GET", "/applications/{application_id}/versions"),
        ("GET", "/versions/{version_id}"),
        ("PATCH", "/versions/{version_id}/items/{item_id}"),
        ("POST", "/versions/{version_id}/approve"),
        ("GET", "/versions/{version_id}/run"),
    }
