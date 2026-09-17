"""Per-tenant rate limiting for LLM-enqueue endpoints.

`limits` (FixedWindowRateLimiter over in-process MemoryStorage) provides the
counting; this module owns the app-facing seam: one shared limiter per process,
a keyed hit per (kind, tenant), and a reset hook for tests. The amount is part
of the key, so a settings change cannot resurrect a spent budget.

Tenants on the demo list (ADR-011) are budgeted at the demo tier; everyone
else at the standard thresholds.

MemoryStorage is deliberate: one API replica today (W6·B), and per-replica
budgeting errs on the safe side if replicas grow before shared storage lands
(ADR-010 documents the Redis path as the deliberate scaling step).
"""

import time
from typing import Literal

from limits import RateLimitItem, parse
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from app.config import Settings

# The two endpoints whose worker side spends LLM budget; each is its own
# budget (ADR-010).
Kind = Literal["extraction", "change_report"]

_parsed: dict[int, RateLimitItem] = {}


def _limit_for(amount: int) -> RateLimitItem:
    if amount not in _parsed:
        _parsed[amount] = parse(f"{amount}/hour")
    return _parsed[amount]


_storage = MemoryStorage()
_limiter = FixedWindowRateLimiter(_storage)


class RateLimitExceededError(Exception):
    """The tenant has spent its configured budget for this endpoint kind."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"rate limit exceeded; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


def enforce(kind: Kind, tenant_id: str, settings: Settings) -> None:
    """Consume one unit of the tenant's budget for `kind` or raise."""
    item = _limit_for(_amount_for(kind, tenant_id, settings))
    if not _limiter.hit(item, kind, tenant_id):
        reset_time, _ = _limiter.get_window_stats(item, kind, tenant_id)
        retry_after = max(1, int(reset_time - time.time()) + 1)
        raise RateLimitExceededError(retry_after)


def _amount_for(kind: Kind, tenant_id: str, settings: Settings) -> int:
    if tenant_id.lower() in _demo_ids(settings):
        return {
            "extraction": settings.demo_rate_limit_extraction_per_hour,
            "change_report": settings.demo_rate_limit_change_report_per_hour,
        }[kind]
    return {
        "extraction": settings.rate_limit_extraction_per_hour,
        "change_report": settings.rate_limit_change_report_per_hour,
    }[kind]


def _demo_ids(settings: Settings) -> frozenset[str]:
    return frozenset(
        part.strip().lower() for part in settings.demo_tenant_ids.split(",") if part.strip()
    )


def reset() -> None:
    """Drop every counter; test isolation only."""
    _storage.reset()
