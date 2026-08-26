"""Request-ID propagation and access logging.

Deliberately pure ASGI rather than BaseHTTPMiddleware: streaming responses such
as FileResponse pass through untouched and there is no extra task boundary that
would break contextvars for downstream work.
"""

import contextvars
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.datastructures import Headers

logger = logging.getLogger(__name__)

# Groundwork for structured traces: handlers and future log filters can read the
# active id from here without threading it through every signature.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

_MAX_REQUEST_ID_LEN = 64

Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


def sanitize_request_id(raw: str) -> str:
    """Header-safe id: printable ASCII only, capped length, generated when empty."""
    cleaned = "".join(ch for ch in raw if 0x21 <= ord(ch) <= 0x7E)[:_MAX_REQUEST_ID_LEN]
    return cleaned or uuid.uuid4().hex


class RequestIDMiddleware:
    def __init__(self, app: Callable[[Any, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = Headers(scope=scope).get("x-request-id", "")
        request_id = sanitize_request_id(raw)
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "http_request method=%s path=%s status=%d duration_ms=%.1f request_id=%s",
                scope.get("method"),
                scope.get("path"),
                status_code,
                duration_ms,
                request_id,
            )
            request_id_ctx.reset(token)
