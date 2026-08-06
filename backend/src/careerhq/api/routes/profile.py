"""Professional Profile routes.

There is deliberately no ``GET /api/profile/{id}``. The profile is always
resolved from the session, so cross-user access is impossible by construction
rather than by a permission check that a future endpoint could omit
(FR-015, SC-005).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from careerhq.api.deps import get_current_profile
from careerhq.domain.models import ProfessionalProfile
from careerhq.domain.schemas import ProfileOut

router = APIRouter(tags=["profile"])

CurrentProfile = Annotated[ProfessionalProfile, Depends(get_current_profile)]


@router.get("/profile", response_model=ProfileOut, summary="The signed-in user's profile")
async def read_profile(profile: CurrentProfile) -> ProfileOut:
    """Return the profile. Empty in this slice; later slices populate it."""
    return ProfileOut.model_validate(profile)
