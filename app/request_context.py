"""Per-request correlation id shared by middleware, logging, and services.

A leaf module on purpose: both the HTTP layer and the service layer depend on
it without depending on each other.
"""

import contextvars

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
actor_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("actor", default=None)


def current_request_id() -> str:
    """Active request id, or '' outside the request cycle."""
    return request_id_ctx.get()


def current_actor() -> str | None:
    """The authenticated principal's subject, or None when unauthenticated
    (service-direct callers such as the eval harness write no actor)."""
    return actor_ctx.get()
