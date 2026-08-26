"""Aggregates all route modules into the single router included by create_app."""

from fastapi import APIRouter

from app.api.routes import documents, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(documents.router)
