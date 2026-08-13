"""API response contracts.

Separate from the ORM models on purpose: what is stored and what is exposed are
different concerns, and coupling them means a new column silently becomes a new
public field.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    """The signed-in identity, as returned by ``GET /api/auth/me``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str | None
    avatar_url: str | None
    created_at: datetime


class ProfileOut(BaseModel):
    """The user's Professional Profile. Empty in this slice."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class GoogleClaims(BaseModel):
    """Verified claims from a Google ID token.

    The seam between "we talked to Google" and everything downstream. Tests
    substitute this object rather than mocking Authlib's internals, so the
    callback route, provisioning, and cookie issuance are all exercised for
    real (research.md R-009).
    """

    sub: str
    email: EmailStr
    name: str | None = None
    picture: str | None = None
