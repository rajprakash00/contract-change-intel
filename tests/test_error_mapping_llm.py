"""Unit tests for the LlmError → HTTP mapping registered app-wide in errors.py.

No route in the app raises LlmError today (LLM calls live in the worker, not
the request path), so the mapping is exercised through a probe route: the
behaviour being locked is the mapping table itself, not any endpoint.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_exception_handlers
from app.llm.client import LlmCallError, LlmNotConfiguredError, LlmOutputError
from app.services.extraction import ExtractionJobNotFoundError


def _client_for(exc: Exception) -> TestClient:
    """App with one GET /raise route that raises `exc` through the mapping table."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise")
    async def raise_exc() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


class TestLlmErrorMapping:
    def test_llm_call_error_maps_to_502_bad_gateway(self) -> None:
        client = _client_for(LlmCallError("gpt-4o-mini", RuntimeError("boom")))

        response = client.get("/raise")

        assert response.status_code == 502
        assert "llm call failed" in response.json()["detail"]

    def test_llm_output_error_maps_to_502_bad_gateway(self) -> None:
        client = _client_for(LlmOutputError("model output failed schema validation"))

        response = client.get("/raise")

        assert response.status_code == 502

    def test_llm_not_configured_maps_to_503_service_unavailable(self) -> None:
        client = _client_for(LlmNotConfiguredError())

        response = client.get("/raise")

        assert response.status_code == 503

    def test_unknown_extraction_job_maps_to_404(self) -> None:
        client = _client_for(ExtractionJobNotFoundError(uuid.uuid4()))

        response = client.get("/raise")

        assert response.status_code == 404
