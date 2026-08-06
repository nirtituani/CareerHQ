"""Authentication routes: Google sign-in, identity, sign-out."""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from careerhq.api.deps import CurrentUser, DbSession, VerifiedClaims, get_oauth
from careerhq.application.provision_user import provision_user
from careerhq.domain.schemas import UserOut
from careerhq.infrastructure.security import (
    clear_session_cookie,
    create_session_token,
    set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("careerhq.auth")

CALLBACK_PATH = "/api/auth/google/callback"
DEFAULT_DESTINATION = "/dashboard"
LOGIN_PATH = "/login"
REDIRECT_KEY = "post_login_redirect"


def _safe_destination(next_path: str | None) -> str:
    """Return a destination that cannot leave this site.

    An unchecked ``next`` is an open redirect: an attacker sends a link that
    signs the user in and then lands them somewhere they control, at the moment
    the user is most likely to trust what they see. Only same-site absolute
    paths pass — ``//evil.com`` is rejected too, since browsers read it as
    protocol-relative.
    """
    if not next_path:
        return DEFAULT_DESTINATION
    if not next_path.startswith("/") or next_path.startswith("//"):
        logger.warning("rejected off-site redirect target", extra={"next": next_path})
        return DEFAULT_DESTINATION
    return next_path


@router.get("/google/login", summary="Begin Google sign-in")
async def google_login(
    request: Request,
    oauth: Annotated[OAuth, Depends(get_oauth)],
    next: Annotated[str | None, Query(description="Same-site path to return to")] = None,
) -> Response:
    """Redirect to Google's consent screen.

    Authlib generates the ``state`` parameter and stores it in the signed
    session cookie. That is what ties the callback back to this browser and
    defeats CSRF on the sign-in flow.
    """
    request.session[REDIRECT_KEY] = _safe_destination(next)
    redirect_uri = str(request.base_url).rstrip("/") + CALLBACK_PATH
    # Authlib is untyped here; it returns a Starlette RedirectResponse.
    redirect: Response = await oauth.google.authorize_redirect(request, redirect_uri)
    return redirect


@router.get("/google/callback", summary="Complete Google sign-in")
async def google_callback(
    request: Request,
    session: DbSession,
    claims: VerifiedClaims,
) -> Response:
    """Google's redirect target: provision the account and issue a session.

    ``claims`` is ``None`` when the user declined at Google's prompt — not an
    error, so they go back to sign-in with an explanation and nothing is created.
    """
    if claims is None:
        reason = request.query_params.get("error", "access_denied")
        return RedirectResponse(
            url=f"{LOGIN_PATH}?{urlencode({'error': reason})}",
            status_code=status.HTTP_302_FOUND,
        )

    user = await provision_user(session, claims.model_dump())
    await session.commit()

    destination = request.session.pop(REDIRECT_KEY, DEFAULT_DESTINATION)
    response = RedirectResponse(url=destination, status_code=status.HTTP_302_FOUND)
    set_session_cookie(response, create_session_token(str(user.id)))

    logger.info("sign-in complete", extra={"user_id": str(user.id)})
    return response


@router.get("/me", response_model=UserOut, summary="The signed-in identity")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout() -> Response:
    """End the session.

    Deliberately safe to call when already signed out — it returns 204 either
    way, so the interface needs no "was I signed in?" special case.
    """
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response
