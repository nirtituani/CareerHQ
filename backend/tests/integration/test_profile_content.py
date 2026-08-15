"""Every stored field reaches the API (FR-004 and the reason this file exists).

Three separate bugs in this slice were the same bug: extraction and storage were
correct, and the display discarded what they produced. A phone number and two
profile links were captured and never shown; skill categories were captured and
flattened; certification years and education grades were stored and never
returned.

None of them could fail a test, because the tests used fixtures — and a fixture
only contains the fields whoever wrote it thought to include, which is the same
set the renderer was written against. Each was found by a person looking at a
real CV.

This test closes that loop from the other end. Rather than asserting a chosen
list of fields, it reads the **columns of the models themselves** and requires
each one's value to appear in the response. A field added later is covered the
day it is added, without anyone remembering to extend this.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.domain.models import (
    Certification,
    ContactInformation,
    Education,
    ExperienceBullet,
    Language,
    MilitaryService,
    ProfessionalProfile,
    ProfessionalTitle,
    Project,
    Skill,
    Source,
    SummaryBlock,
    User,
    VolunteerExperience,
    WorkExperience,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

#: Structural columns. Their absence from the response is not a lost fact.
IGNORED = {"id", "profile_id", "experience_id", "user_id", "created_at", "updated_at", "ordinal"}


async def _populated_profile(session: AsyncSession) -> tuple[User, ProfessionalProfile]:
    """One fully-populated row of every kind, with distinctive values.

    Every value is unique so that finding it in the response cannot be a
    coincidence — "Tel Aviv" appearing twice would not prove the location field
    was rendered.
    """
    user = User(google_sub=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@example.com")
    session.add(user)
    await session.flush()

    profile = ProfessionalProfile(user_id=user.id)
    session.add(profile)
    await session.flush()

    role = WorkExperience(
        profile_id=profile.id,
        company="COMPANY-marker",
        title="TITLE-marker",
        location="LOCATION-marker",
        start_date="START-marker",
        end_date="END-marker",
        is_current=False,
        source=Source.EXTRACTED,
    )
    session.add(role)
    await session.flush()
    # The foreign key is set directly rather than appending through the
    # relationship: appending would lazy-load the collection, which async
    # SQLAlchemy refuses outside a greenlet.
    session.add(
        ExperienceBullet(
            experience_id=role.id,
            text="BULLET-marker",
            ordinal=0,
            source=Source.USER_CORRECTED,
        )
    )

    session.add_all(
        [
            ContactInformation(
                profile_id=profile.id,
                full_name="FULLNAME-marker",
                email="EMAIL-marker@example.com",
                phone="PHONE-marker",
                location="CONTACTLOCATION-marker",
                links="LINKONE-marker\nLINKTWO-marker",
                source=Source.EXTRACTED,
            ),
            ProfessionalTitle(
                profile_id=profile.id, title="PROFTITLE-marker", source=Source.EXTRACTED
            ),
            SummaryBlock(profile_id=profile.id, text="SUMMARY-marker", source=Source.EXTRACTED),
            Skill(
                profile_id=profile.id,
                name="SKILLNAME-marker",
                category="SKILLCATEGORY-marker",
                source=Source.EXTRACTED,
            ),
            Project(
                profile_id=profile.id,
                name="PROJECTNAME-marker",
                description="PROJECTDESC-marker",
                url="PROJECTURL-marker",
                source=Source.EXTRACTED,
            ),
            Education(
                profile_id=profile.id,
                institution="INSTITUTION-marker",
                qualification="QUALIFICATION-marker",
                field_of_study="FIELDOFSTUDY-marker",
                start_date="EDUSTART-marker",
                end_date="EDUEND-marker",
                grade="GRADE-marker",
                source=Source.EXTRACTED,
            ),
            Certification(
                profile_id=profile.id,
                name="CERTNAME-marker",
                issuer="CERTISSUER-marker",
                year="CERTYEAR-marker",
                source=Source.EXTRACTED,
            ),
            Language(
                profile_id=profile.id,
                name="LANGNAME-marker",
                proficiency="LANGPROF-marker",
                source=Source.EXTRACTED,
            ),
            MilitaryService(
                profile_id=profile.id,
                branch="BRANCH-marker",
                role="MILROLE-marker",
                start_date="MILSTART-marker",
                end_date="MILEND-marker",
                source=Source.EXTRACTED,
            ),
            VolunteerExperience(
                profile_id=profile.id,
                organisation="ORGANISATION-marker",
                role="VOLROLE-marker",
                start_date="VOLSTART-marker",
                end_date="VOLEND-marker",
                source=Source.EXTRACTED,
            ),
        ]
    )
    await session.commit()
    return user, profile


async def test_every_stored_field_reaches_the_api(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Read the models' own columns and require each value in the response.

    Deliberately not a list of expected fields: a list has to be remembered, and
    the three bugs this test exists for were all fields nobody remembered.
    """
    user, _ = await _populated_profile(db_session)
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))

    response = await client.get("/api/profile/content")
    assert response.status_code == 200
    body: str = json.dumps(response.json())

    missing: list[str] = []
    for model in (
        ContactInformation,
        ProfessionalTitle,
        SummaryBlock,
        WorkExperience,
        ExperienceBullet,
        Skill,
        Project,
        Education,
        Certification,
        Language,
        MilitaryService,
        VolunteerExperience,
    ):
        instance = (await db_session.scalars(select(model))).first()
        assert instance is not None, f"{model.__name__} was not created"

        for column in inspect(model).columns:
            if column.key in IGNORED:
                continue
            value: Any = getattr(instance, column.key)
            if value is None or isinstance(value, bool):
                continue
            for part in str(value).splitlines():
                if part.strip() and part not in body:
                    missing.append(f"{model.__name__}.{column.key} = {part!r}")

    assert not missing, (
        "these stored values never reach the API, so the interface cannot show them "
        f"and the user cannot verify them: {missing}"
    )
