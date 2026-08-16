"""Removing things from the profile.

Until this existed, anything that reached the profile was permanent — a badly
parsed role could be discarded during review but never afterwards, and review is
where a mistake is easiest to miss, because there are dozens of items and no
consequence has been felt yet.
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.domain.models import (
    ExperienceBullet,
    ProfessionalProfile,
    Skill,
    Source,
    User,
    WorkExperience,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token


async def _user_with_content(session: AsyncSession) -> tuple[User, WorkExperience, Skill]:
    user = User(google_sub=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@example.com")
    session.add(user)
    await session.flush()
    profile = ProfessionalProfile(user_id=user.id)
    session.add(profile)
    await session.flush()

    role = WorkExperience(profile_id=profile.id, company="Acme", source=Source.EXTRACTED)
    skill = Skill(profile_id=profile.id, name="Python", source=Source.EXTRACTED)
    session.add_all([role, skill])
    await session.flush()
    session.add(
        ExperienceBullet(experience_id=role.id, text="Did a thing", source=Source.EXTRACTED)
    )
    await session.commit()
    return user, role, skill


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


async def test_one_item_can_be_removed(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user, _, skill = await _user_with_content(db_session)

    response = await _as(client, user).delete(f"/api/profile/skill/{skill.id}")

    assert response.status_code == 204
    assert (await db_session.scalar(select(func.count()).select_from(Skill))) == 0


async def test_a_whole_section_can_be_cleared(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The case that motivated it: a skills block parsed badly enough that
    removing twenty-two entries one at a time is not a realistic repair."""
    user, _, _ = await _user_with_content(db_session)
    db_session.add_all(
        [
            Skill(
                profile_id=(
                    await db_session.scalar(
                        select(ProfessionalProfile.id).where(ProfessionalProfile.user_id == user.id)
                    )
                ),
                name=f"Skill {n}",
                source=Source.EXTRACTED,
            )
            for n in range(5)
        ]
    )
    await db_session.commit()

    response = await _as(client, user).delete("/api/profile/skill")

    assert response.status_code == 204
    assert (await db_session.scalar(select(func.count()).select_from(Skill))) == 0


async def test_removing_a_role_removes_its_bullets(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Otherwise an achievement outlives the job it belonged to."""
    user, role, _ = await _user_with_content(db_session)

    assert (
        await _as(client, user).delete(f"/api/profile/work_experience/{role.id}")
    ).status_code == 204

    assert (await db_session.scalar(select(func.count()).select_from(ExperienceBullet))) == 0


async def test_a_bullet_can_be_removed_on_its_own(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, _, _ = await _user_with_content(db_session)
    bullet = await db_session.scalar(select(ExperienceBullet))
    assert bullet is not None

    assert (await _as(client, user).delete(f"/api/profile/bullet/{bullet.id}")).status_code == 204

    assert (await db_session.scalar(select(func.count()).select_from(ExperienceBullet))) == 0


async def test_another_users_item_cannot_be_removed(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-019 — and enforced by the WHERE clause, not by a check beside it.

    Ownership is part of the query, so the statement that could delete someone
    else's row does not exist. Guessing an id achieves nothing.
    """
    _, _, victim_skill = await _user_with_content(db_session)
    attacker, _, _ = await _user_with_content(db_session)

    response = await _as(client, attacker).delete(f"/api/profile/skill/{victim_skill.id}")

    assert response.status_code == 404, "404, not 403 — do not confirm it exists"
    assert (await db_session.get(Skill, victim_skill.id)) is not None


async def test_another_users_section_is_untouched(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Clearing a section must clear only your own."""
    _victim, _, victim_skill = await _user_with_content(db_session)
    attacker, _, _ = await _user_with_content(db_session)

    assert (await _as(client, attacker).delete("/api/profile/skill")).status_code == 204

    assert (await db_session.get(Skill, victim_skill.id)) is not None


async def test_an_unknown_section_is_not_found(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, _, _ = await _user_with_content(db_session)

    assert (await _as(client, user).delete("/api/profile/nonsense")).status_code == 404


async def test_removal_requires_authentication(client: httpx.AsyncClient) -> None:
    client.cookies.clear()
    assert (await client.delete(f"/api/profile/skill/{uuid.uuid4()}")).status_code == 401
    assert (await client.delete("/api/profile/skill")).status_code == 401


async def test_the_whole_profile_can_be_cleared(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Starting over is reasonable after a bad import.

    Clearing eleven sections one at a time is not a way anyone would actually do
    it, so the absence of this was the difference between "you can fix a
    mistake" and "you can fix a mistake if you are patient enough".
    """
    from careerhq.domain.models import ResumeProfile

    user, _, _ = await _user_with_content(db_session)
    profile_id = await db_session.scalar(
        select(ProfessionalProfile.id).where(ProfessionalProfile.user_id == user.id)
    )
    db_session.add(ResumeProfile(profile_id=profile_id, name="Master Resume", is_master=True))
    await db_session.commit()

    assert (await _as(client, user).delete("/api/profile/content")).status_code == 204

    for model in (Skill, WorkExperience, ExperienceBullet, ResumeProfile):
        assert (await db_session.scalar(select(func.count()).select_from(model))) == 0


async def test_clearing_keeps_the_profile_and_the_user(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Principle I: exactly one profile per user.

    Deleting and recreating the profile row would briefly break that invariant
    and orphan anything later pointed at it. Clearing empties the container
    rather than replacing it.
    """
    user, _, _ = await _user_with_content(db_session)

    await _as(client, user).delete("/api/profile/content")

    assert (await db_session.get(User, user.id)) is not None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProfessionalProfile)
            .where(ProfessionalProfile.user_id == user.id)
        )
    ) == 1


async def test_clearing_one_profile_leaves_another_alone(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _victim, _, victim_skill = await _user_with_content(db_session)
    attacker, _, _ = await _user_with_content(db_session)

    assert (await _as(client, attacker).delete("/api/profile/content")).status_code == 204

    assert (await db_session.get(Skill, victim_skill.id)) is not None


# -- Correcting a fact already in the profile --------------------------------


async def test_an_item_in_the_profile_can_be_corrected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Review lets a user correct before approving; this is correcting after.

    Without it, a one-character typo in a job title cost the whole entry,
    because deleting was the only repair available.
    """
    user, _, skill = await _user_with_content(db_session)

    response = await _as(client, user).patch(
        f"/api/profile/skill/{skill.id}", json={"name": "Rust", "category": "Languages"}
    )

    assert response.status_code == 200
    await db_session.refresh(skill)
    assert skill.name == "Rust"
    assert skill.category == "Languages"


async def test_correcting_marks_the_item_verified(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The same state a review correction produces, with the same consequence:
    a later import will not overwrite it."""
    user, _, skill = await _user_with_content(db_session)

    await _as(client, user).patch(f"/api/profile/skill/{skill.id}", json={"name": "Rust"})

    await db_session.refresh(skill)
    assert skill.source == Source.USER_CORRECTED


async def test_a_patch_cannot_move_a_row_to_another_profile(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The whitelist is the point.

    Without it a request could set `profile_id` and hand its own row to someone
    else's profile, or rewrite `source` and forge the provenance that decides
    what a later import is allowed to overwrite.
    """
    user, _, skill = await _user_with_content(db_session)
    original_profile = skill.profile_id

    await _as(client, user).patch(
        f"/api/profile/skill/{skill.id}",
        json={"name": "Rust", "profile_id": str(uuid.uuid4()), "source": "extracted"},
    )

    await db_session.refresh(skill)
    assert skill.profile_id == original_profile
    assert skill.source == Source.USER_CORRECTED, "source is set by the server, not the request"


async def test_another_users_item_cannot_be_corrected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _victim, _, victim_skill = await _user_with_content(db_session)
    attacker, _, _ = await _user_with_content(db_session)

    response = await _as(client, attacker).patch(
        f"/api/profile/skill/{victim_skill.id}", json={"name": "Owned"}
    )

    assert response.status_code == 404
    await db_session.refresh(victim_skill)
    assert victim_skill.name == "Python"
