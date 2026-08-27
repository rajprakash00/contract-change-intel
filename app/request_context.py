"""Per-request correlation id shared by middleware, logging, and services.

A leaf module on purpose: both the HTTP layer and the service layer depend on
it without depending on each other.
"""

import contextvars

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def current_request_id() -> str:
    """Active request id, or '' outside the request cycle."""
    return request_id_ctx.get()
