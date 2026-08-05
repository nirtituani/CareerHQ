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

from careerhq.config import Settings, get_settings
from careerhq.infrastructure.logging import RequestContextMiddleware, configure_logging

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

    from careerhq.api.routes import health

    app.include_router(health.router, prefix="/api")

    return app


app = create_app()
