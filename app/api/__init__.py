"""HTTP layer: route modules plus the aggregated api_router wired into create_app."""

from app.api.main import api_router

__all__ = ["api_router"]
