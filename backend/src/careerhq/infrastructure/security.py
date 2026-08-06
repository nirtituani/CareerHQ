"""Session tokens and cookies.

The session is a signed JWT in an HttpOnly cookie — there is no session table.
Stateless keeps the API horizontally scalable and keeps Redis off the
authentication request path (research.md R-002).

The trade-off accepted: a token cannot be revoked before it expires. For a
seven-day personal-productivity session that is acceptable, and a Redis
deny-list can be added later without changing the cookie contract.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Response

from careerhq.config import get_settings

logger = logging.getLogger("careerhq.security")

SESSION_COOKIE = "careerhq_session"
ALGORITHM = "HS256"


def create_session_token(user_id: str, ttl_days: int | None = None) -> str:
    """Sign a session token for ``user_id``.

    ``ttl_days`` is overridable so tests can mint an already-expired token
    without waiting or patching the clock.
    """
    settings = get_settings()
    ttl = settings.session_ttl_days if ttl_days is None else ttl_days
    now = datetime.now(UTC)

    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + timedelta(days=ttl)},
        settings.session_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )


def read_session_token(token: str) -> str | None:
    """Return the user id from a valid token, or ``None``.

    Every failure — bad signature, expired, malformed, missing subject —
    collapses to ``None``. The caller turns that into a 401; the distinction
    between "forged" and "expired" is useful to an attacker and to nobody else.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.session_secret.get_secret_value(),
            algorithms=[ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        logger.info("rejected session token", extra={"reason": exc.__class__.__name__})
        return None

    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie.

    ``httponly`` is what satisfies FR-016 — browser scripts cannot read it, so
    an XSS bug cannot exfiltrate the session. ``samesite="lax"`` blocks the
    cookie on cross-site POSTs while still allowing the top-level redirect back
    from Google. ``secure`` is off locally because localhost is plain HTTP.
    """
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Expire the session cookie. Safe to call when already signed out."""
    settings = get_settings()
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
