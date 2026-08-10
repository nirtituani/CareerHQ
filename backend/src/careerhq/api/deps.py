"""Shared request dependencies."""

from __future__ import annotations

import logging
from typing import Annotated

from authlib.integrations.starlette_client import OAuth
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.config import Settings, get_settings
from careerhq.domain.models import ProfessionalProfile, User
from careerhq.domain.schemas import GoogleClaims
from careerhq.infrastructure.database import get_db
from careerhq.infrastructure.security import SESSION_COOKIE, read_session_token

logger = logging.getLogger("careerhq.auth")

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_oauth(settings: Annotated[Settings, Depends(get_settings)]) -> OAuth:
    """Configured Authlib client for Google.

    Raises rather than failing at import when Google is not configured: the
    platform must start and report healthy before an OAuth client exists, so
    the failure belongs on the routes that actually need it.
    """
    if not settings.google_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET, then run: docker compose up -d backend"
            ),
        )

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=(
            settings.google_client_secret.get_secret_value()
            if settings.google_client_secret
            else None
        ),
        # Explicit endpoints rather than server_metadata_url: discovery costs a
        # network round trip on every sign-in and makes tests depend on
        # Google being reachable. These endpoints are stable.
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        # S106 is suppressed below because it flags any argument whose name
        # contains "token" as a possible hardcoded credential. This is a public
        # endpoint URL, not a secret.
        access_token_url="https://oauth2.googleapis.com/token",  # noqa: S106
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


async def get_verified_google_claims(
    request: Request,
    oauth: Annotated[OAuth, Depends(get_oauth)],
) -> GoogleClaims | None:
    """Exchange the authorization code and return verified identity claims.

    **This is the seam.** Everything downstream — provisioning, cookie issuance,
    redirect — depends on this returning claims, not on how they were obtained.
    Tests override this dependency, so the whole flow is exercised for real with
    only the network call to Google removed (research.md R-009).

    Returns ``None`` when the user declined at Google's prompt. That is not an
    error and must not raise: the route turns it into a redirect back to the
    sign-in page, and no account is created.
    """
    if request.query_params.get("error"):
        logger.info("google sign-in declined", extra={"error": request.query_params.get("error")})
        return None

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        logger.warning("google token exchange failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not complete Google sign-in.",
        ) from exc

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not return identity information.",
        )

    return GoogleClaims(
        sub=userinfo["sub"],
        email=userinfo["email"],
        name=userinfo.get("name"),
        picture=userinfo.get("picture"),
    )


VerifiedClaims = Annotated[GoogleClaims | None, Depends(get_verified_google_claims)]


async def get_current_user(
    session: DbSession,
    careerhq_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    """Resolve the signed-in user, or raise 401.

    Every failure is a 401: no cookie, bad signature, expired, or a subject
    whose account no longer exists. That last case is the spec's "session no
    longer valid" edge case — it is treated as unauthenticated, never as an
    error page.
    """
    unauthenticated = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )

    if not careerhq_session:
        raise unauthenticated

    user_id = read_session_token(careerhq_session)
    if user_id is None:
        raise unauthenticated

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        logger.info("session referenced a user that no longer exists")
        raise unauthenticated

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_profile(
    session: DbSession,
    user: CurrentUser,
) -> ProfessionalProfile:
    """The signed-in user's profile, resolved from the session only.

    There is deliberately no variant that takes a profile id from the client.
    Ownership is derived, never asserted by the caller (FR-015).
    """
    profile = await session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == user.id)
    )
    if profile is None:  # pragma: no cover - provisioning guarantees one exists
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Professional profile not found.",
        )
    return profile
