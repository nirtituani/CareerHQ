"""The CV import flow (T031, T034-T043).

Principle II is the subject of this file. Extraction stages content; approval is
what writes to the profile; and an import nobody approved leaves nothing behind.
Most of these tests are about that boundary rather than about extraction
quality.

No test contacts a provider: the completion seam is overridden, which is the
whole reason it is a seam (FR-027, obligation O6).
"""

from __future__ import annotations

import pathlib
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.api.deps import get_structured_completion
from careerhq.application.ports import Completion, Usage
from careerhq.domain.models import (
    ExperienceBullet,
    ImportedResume,
    ImportStatus,
    ResumeProfile,
    Skill,
    Source,
    User,
    WorkExperience,
)
from careerhq.infrastructure import storage
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

#: The real fixture, so these tests exercise the actual PDF extractor. Only the
#: model call is stubbed — which is the one thing that would otherwise need a
#: network and an API key.
PDF = (pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sample_cv.pdf").read_bytes()

RICH_EXTRACTION: dict[str, Any] = {
    "contact": {"full_name": "Alex Morgan", "email": "alex@example.com", "confidence": 0.95},
    "titles": [{"title": "Senior Backend Engineer", "confidence": 0.9}],
    "summary": {"text": "Eight years building distributed systems.", "confidence": 0.8},
    "work_experience": [
        {
            "company": "Northwind Payments",
            "title": "Staff Engineer",
            "start_date": "March 2021",
            "is_current": True,
            "confidence": 0.92,
            "bullets": [
                {"text": "Led the ledger migration.", "confidence": 0.88},
                {"text": "Designed the idempotency layer.", "confidence": 0.3},
            ],
        }
    ],
    "skills": [{"name": "Python", "confidence": 0.99}],
}


class _Stub:
    """A completion client returning a fixed payload. No network, no key."""

    def __init__(self, payload: dict[str, Any] | None = None, *, fixture: bool = False) -> None:
        self._payload = RICH_EXTRACTION if payload is None else payload
        self._fixture = fixture

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        return Completion(
            value=schema.model_validate(self._payload),
            usage=Usage(
                model="stub/model",
                input_tokens=100,
                output_tokens=50,
                cost=Decimal("0.001"),
                is_fixture=self._fixture,
            ),
        )


@pytest.fixture(autouse=True)
def _no_object_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploads go nowhere. MinIO's real credentials are not the test's subject."""

    async def _put(key: str, data: bytes, *, content_type: str) -> None:
        return None

    monkeypatch.setattr(storage, "put_object", _put)


def _stub_completion(app: Any, client: _Stub) -> None:
    app.dependency_overrides[get_structured_completion] = lambda: client


async def _sign_in(session: AsyncSession, client: httpx.AsyncClient) -> User:
    user = User(google_sub=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@example.com")
    session.add(user)
    await session.flush()
    from careerhq.domain.models import ProfessionalProfile

    session.add(ProfessionalProfile(user_id=user.id))
    await session.commit()
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return user


async def _upload(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post(
        "/api/imports/resume",
        files={"file": ("cv.pdf", PDF, "application/pdf")},
    )


async def _profile_counts(session: AsyncSession) -> tuple[int, int]:
    roles = await session.scalar(select(func.count()).select_from(WorkExperience))
    skills = await session.scalar(select(func.count()).select_from(Skill))
    return roles or 0, skills or 0


# -- T031: staging is staging -----------------------------------------------


async def test_extraction_writes_nothing_to_the_profile(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T031, FR-003, FR-007 — the point of the whole staging design.

    If this fails, Principle II is not being enforced: content reached the
    user's professional profile without a human approving it.
    """
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())

    response = await _upload(client)

    assert response.status_code == 202
    assert await _profile_counts(db_session) == (0, 0)
    assert response.json()["items"], "the staged items must still be returned for review"


async def test_extracted_items_arrive_pending_whatever_their_confidence(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T041, FR-029 — no confidence value auto-accepts.

    Principle II admits no threshold. "We were very sure about this one" is
    exactly how an approval gate quietly stops being one, so the 0.99 skill and
    the 0.3 bullet must be equally pending.
    """
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())

    body = (await _upload(client)).json()

    assert {item["decision"] for item in body["items"]} == {"pending"}
    assert any(item["confidence"] >= 0.9 for item in body["items"])


# -- T034: one master resume, even when approved twice ----------------------


async def test_approving_twice_yields_one_master_resume(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T034, SC-004, constraint C4.

    A double-clicked button is the realistic path to this bug.
    """
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    import_id = (await _upload(client)).json()["id"]

    first = await client.post(f"/api/imports/{import_id}/approve")
    second = await client.post(f"/api/imports/{import_id}/approve")

    assert first.status_code == 200
    assert second.status_code == 409, "a second approval is a conflict, not a second resume"

    masters = await db_session.scalar(
        select(func.count()).select_from(ResumeProfile).where(ResumeProfile.is_master)
    )
    assert masters == 1


async def test_approval_populates_the_profile(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The other half of T031: approval is what writes."""
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    import_id = (await _upload(client)).json()["id"]

    assert (await client.post(f"/api/imports/{import_id}/approve")).status_code == 200

    roles, skills = await _profile_counts(db_session)
    assert roles == 1
    assert skills == 1


# -- T035: corrections win ---------------------------------------------------


async def test_a_corrected_item_is_stored_instead_of_the_extraction(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T035, FR-004, Scenario 2 — and the correction is marked as one."""
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    body = (await _upload(client)).json()
    import_id = body["id"]
    skill = next(item for item in body["items"] if item["kind"] == "skill")

    patched = await client.patch(
        f"/api/imports/{import_id}/items/{skill['id']}",
        json={"payload": {"name": "Rust", "confidence": 0.99}},
    )
    assert patched.status_code == 200
    assert patched.json()["source"] == "user_corrected"

    await client.post(f"/api/imports/{import_id}/approve")

    stored = (await db_session.scalars(select(Skill))).all()
    assert [s.name for s in stored] == ["Rust"]
    assert stored[0].source == Source.USER_CORRECTED


# -- T036: abandonment leaves nothing ---------------------------------------


async def test_an_abandoned_import_leaves_the_profile_empty(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T036, FR-007, Scenario 6."""
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    import_id = (await _upload(client)).json()["id"]

    assert (await client.delete(f"/api/imports/{import_id}")).status_code == 204
    assert await _profile_counts(db_session) == (0, 0)


async def test_a_discarded_item_does_not_reach_the_profile(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    body = (await _upload(client)).json()
    import_id = body["id"]
    skill = next(item for item in body["items"] if item["kind"] == "skill")

    await client.patch(
        f"/api/imports/{import_id}/items/{skill['id']}", json={"decision": "discarded"}
    )
    await client.post(f"/api/imports/{import_id}/approve")

    assert (await db_session.scalar(select(func.count()).select_from(Skill))) == 0


# -- T037, T038: refusals ----------------------------------------------------


async def test_an_unsupported_format_is_refused_and_stores_nothing(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T037, FR-001, Scenario 5."""
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())

    response = await client.post(
        "/api/imports/resume", files={"file": ("notes.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    assert (await db_session.scalar(select(func.count()).select_from(ImportedResume))) == 0


async def test_an_extraction_that_finds_nothing_is_a_failure_not_an_empty_form(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T038, FR-008 — the failure that must not look like success.

    422 with an explanation, never 202 with an empty item list: the latter tells
    the user their CV was read and found to contain nothing.
    """
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub(payload={}))

    response = await _upload(client)

    assert response.status_code == 422
    assert response.json()["detail"]

    stored = (await db_session.scalars(select(ImportedResume))).all()
    assert [record.status for record in stored] == [ImportStatus.FAILED]
    assert stored[0].extraction_error


# -- T039: the first-run path ------------------------------------------------


async def test_no_provider_configured_returns_503_naming_the_setting(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T039, FR-028, obligation O7.

    Before credentials exist, every user hits this. It must name what to set —
    not crash, and not silently produce an empty extraction.
    """
    await _sign_in(db_session, client)
    app.dependency_overrides.pop(get_structured_completion, None)

    from careerhq.api import deps
    from careerhq.config import DependencyNotConfiguredError

    def _unconfigured() -> str:
        raise DependencyNotConfiguredError("AI provider", "ANTHROPIC_API_KEY")

    original = deps.build_completion_client
    deps.build_completion_client = _unconfigured  # type: ignore[assignment]
    try:
        response = await _upload(client)
    finally:
        deps.build_completion_client = original  # type: ignore[assignment]

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


# -- T040: one profile, always -----------------------------------------------


async def test_a_second_import_does_not_create_a_second_profile(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T040, FR-009, constraint C1."""
    from careerhq.domain.models import ProfessionalProfile

    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())

    first = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{first}/approve")
    second = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{second}/approve")

    profiles = await db_session.scalar(select(func.count()).select_from(ProfessionalProfile))
    assert profiles == 1


# -- T043: ownership ---------------------------------------------------------


async def test_another_users_import_is_not_found_rather_than_forbidden(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T043, FR-019 — 404, not 403.

    403 would confirm the resource exists, which is a disclosure in itself.
    """
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    import_id = (await _upload(client)).json()["id"]

    await _sign_in(db_session, client)  # a different user
    assert (await client.get(f"/api/imports/{import_id}")).status_code == 404
    assert (await client.post(f"/api/imports/{import_id}/approve")).status_code == 404


async def test_import_routes_require_authentication(client: httpx.AsyncClient) -> None:
    client.cookies.clear()
    assert (await _upload(client)).status_code == 401
    assert (await client.get(f"/api/imports/{uuid.uuid4()}")).status_code == 401


# -- FR-009: a second import merges, it does not duplicate -------------------


async def test_reimporting_the_same_cv_adds_nothing(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The bug this file most needed and did not have.

    Approving three imports of one CV produced 66 skills, 27 bullets and three
    contact rows on a real profile. FR-009 requires a subsequent import to be
    merged rather than appended, and only the "no second profile" half had been
    implemented — so nothing failed, and the profile quietly became three copies
    of itself.
    """
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())

    first = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{first}/approve")
    after_first = await _profile_counts(db_session)

    second = (await _upload(client)).json()["id"]
    assert (await client.post(f"/api/imports/{second}/approve")).status_code == 200

    assert await _profile_counts(db_session) == after_first, (
        "re-importing the same CV must add nothing"
    )

    bullets = await db_session.scalar(select(func.count()).select_from(ExperienceBullet))
    assert bullets == 2, "the same achievements must not be recorded twice"


async def test_a_second_import_adds_only_what_is_new(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """An updated CV is the realistic case, not an identical one."""
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    first = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{first}/approve")

    updated = {
        **RICH_EXTRACTION,
        "skills": [
            {"name": "Python", "confidence": 0.99},
            {"name": "Rust", "confidence": 0.9},
        ],
    }
    _stub_completion(app, _Stub(payload=updated))
    second = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{second}/approve")

    names = sorted(s.name for s in (await db_session.scalars(select(Skill))).all())
    assert names == ["Python", "Rust"], "the new skill lands, the existing one is not doubled"


async def test_contact_and_summary_are_single_valued(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A person has one set of contact details. A newer CV supersedes the older."""
    from careerhq.domain.models import ContactInformation, SummaryBlock

    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    for _ in range(2):
        import_id = (await _upload(client)).json()["id"]
        await client.post(f"/api/imports/{import_id}/approve")

    contacts = await db_session.scalar(select(func.count()).select_from(ContactInformation))
    summaries = await db_session.scalar(select(func.count()).select_from(SummaryBlock))
    assert (contacts, summaries) == (1, 1)


async def test_a_new_achievement_attaches_to_the_role_already_on_the_profile(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The case that would otherwise orphan a bullet.

    An updated CV repeats the job you are still in and adds an achievement to
    it. The role is skipped as a duplicate, so its new bullet needs the role
    already on the profile to attach to — or it is silently dropped.
    """
    await _sign_in(db_session, client)
    _stub_completion(app, _Stub())
    first = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{first}/approve")

    grown = {
        **RICH_EXTRACTION,
        "work_experience": [
            {
                **RICH_EXTRACTION["work_experience"][0],  # type: ignore[index]
                "bullets": [
                    {"text": "Led the ledger migration.", "confidence": 0.88},
                    {"text": "Designed the idempotency layer.", "confidence": 0.3},
                    {"text": "Shipped the reconciliation service.", "confidence": 0.9},
                ],
            }
        ],
    }
    _stub_completion(app, _Stub(payload=grown))
    second = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{second}/approve")

    roles = (await db_session.scalars(select(WorkExperience))).all()
    assert len(roles) == 1, "the same job must not appear twice"

    texts = sorted(b.text for b in (await db_session.scalars(select(ExperienceBullet))).all())
    assert texts == [
        "Designed the idempotency layer.",
        "Led the ledger migration.",
        "Shipped the reconciliation service.",
    ]


async def test_a_corrected_summary_survives_a_later_import(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-009: a verified fact is never silently overwritten.

    Contact and summary are single-valued, so a later CV replaces them — which
    is right when the value came from an extraction nobody checked, and wrong
    when the user rewrote it. A summary is among the most likely things a person
    edits by hand and the least likely thing they expect a stale CV to erase.

    Before this, re-importing replaced a corrected summary silently and the user
    had no way to know it had happened.
    """
    from careerhq.domain.models import SummaryBlock

    await _sign_in(db_session, client)
    _stub_completion(
        app, _Stub(payload={**RICH_EXTRACTION, "summary": {"text": "First", "confidence": 0.9}})
    )
    first = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{first}/approve")

    stored = (await db_session.scalars(select(SummaryBlock))).all()
    stored[0].text = "The summary I wrote myself"
    stored[0].source = Source.USER_CORRECTED
    await db_session.commit()

    _stub_completion(
        app, _Stub(payload={**RICH_EXTRACTION, "summary": {"text": "Second", "confidence": 0.9}})
    )
    second = (await _upload(client)).json()["id"]
    assert (await client.post(f"/api/imports/{second}/approve")).status_code == 200

    after = (await db_session.scalars(select(SummaryBlock))).all()
    assert [s.text for s in after] == ["The summary I wrote myself"]
    assert after[0].source == Source.USER_CORRECTED


async def test_an_untouched_summary_is_replaced_by_a_newer_cv(
    app: Any, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The other half: replacing is correct when nobody verified the old value.

    Otherwise the first CV ever imported would pin the summary forever.
    """
    from careerhq.domain.models import SummaryBlock

    await _sign_in(db_session, client)
    _stub_completion(
        app, _Stub(payload={**RICH_EXTRACTION, "summary": {"text": "First", "confidence": 0.9}})
    )
    first = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{first}/approve")

    _stub_completion(
        app, _Stub(payload={**RICH_EXTRACTION, "summary": {"text": "Second", "confidence": 0.9}})
    )
    second = (await _upload(client)).json()["id"]
    await client.post(f"/api/imports/{second}/approve")

    after = (await db_session.scalars(select(SummaryBlock))).all()
    assert [s.text for s in after] == ["Second"]
