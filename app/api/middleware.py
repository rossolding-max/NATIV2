"""Request-scoped middleware. See ``docs/api_conventions.md`` § 9.

``RequestContextMiddleware``:
- Generates a ``request_id`` if the client did not send ``X-Request-Id``.
- Honours an inbound ``X-Request-Id`` (idempotent retries).
- Binds ``request_id`` to the structlog context for the request's duration.
- Stamps the same value on the outbound ``X-Request-Id`` response header.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

_REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_PREFIX = "req_"


def _generate_request_id() -> str:
    return f"{_REQUEST_ID_PREFIX}{uuid4().hex}"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind ``request_id`` to the structlog context per request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        inbound = request.headers.get(_REQUEST_ID_HEADER)
        request_id = inbound or _generate_request_id()

        bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers[_REQUEST_ID_HEADER] = request_id
            return response
        finally:
            clear_contextvars()
