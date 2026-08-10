"""Structured JSON logging with per-request correlation (FR-008).

Every log line carries the request id of the request that produced it, so a
single request can be followed across modules. The id is taken from an inbound
``X-Request-ID`` header when present — letting a proxy or client correlate
across services — and generated otherwise. It is always echoed back on the
response.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# ContextVar rather than a thread local: the server is async, and a single
# thread interleaves many requests.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the id of the request being handled, if any."""
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Anything passed via logger.info("...", extra={"key": value}).
        standard = logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
        for key, value in record.__dict__.items():
            if key not in standard and key not in payload and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger, replacing any handlers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; let records propagate to ours instead
    # so that every line in the container is JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id to the context and log the completed request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = _request_id.set(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger("careerhq.request").exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise
        finally:
            _request_id.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        logging.getLogger("careerhq.request").info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response
