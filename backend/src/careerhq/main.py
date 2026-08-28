"""Application factory.

Everything the API is made of is assembled here: configuration is read (and
validated, so a missing value stops the process now rather than later), logging
is installed, middleware is attached, and routers are registered.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from careerhq.config import Settings, get_settings
from careerhq.infrastructure.embeddings import get_embedding_source
from careerhq.infrastructure.logging import RequestContextMiddleware, configure_logging
from careerhq.infrastructure.security import SecurityHeadersMiddleware

logger = logging.getLogger("careerhq")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "careerhq starting",
        extra={"environment": settings.environment, "version": app.version},
    )
    if not settings.google_oauth_configured:
        # Not fatal: the platform runs and reports healthy without it, so the
        # environment can be verified before a Google Cloud client exists.
        logger.warning("google oauth is not configured; sign-in will be unavailable")
    if settings.guideline_source == "retrieval":
        # T030, deferred from T008 because nothing held an embedder until now.
        # SC-007 excludes model initialisation from its budget *because* it is
        # paid at startup — which is only true if something actually pays it
        # here. Skipped under the static rubric: loading 64 MB of weights a
        # static run will never consult is pure startup cost.
        try:
            await get_embedding_source().warm_up()
        except Exception:
            # **Not fatal, and FR-010 decides that rather than a preference.**
            # Retrieval may never fail a tailoring run, so it may certainly
            # never fail the process: every run falls back to the static rubric
            # and records that it did. A degraded platform, not no platform.
            logger.warning(
                "the embedding model failed to warm up; runs will fall back to the "
                "static rubric until it loads",
                exc_info=True,
            )
    yield
    logger.info("careerhq shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Accepts settings so tests can substitute them."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="CareerHQ API",
        description="AI-powered career intelligence platform.",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)

    # Authlib stores the OAuth `state` parameter here between the redirect to
    # Google and the callback. It is a signed cookie, not server-side storage,
    # so nothing needs to be shared between API instances.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        same_site="lax",
        https_only=settings.is_production,
        max_age=600,  # the sign-in round trip, not the user's session
    )

    from careerhq.api.routes import applications, auth, health, imports, profile, tailoring

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(profile.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(applications.router, prefix="/api")
    # No prefix of its own: it serves both `/api/applications/{id}/tailor` and
    # `/api/versions/{id}`, which are two resources rather than one subtree.
    app.include_router(tailoring.router, prefix="/api")

    return app


app = create_app()
