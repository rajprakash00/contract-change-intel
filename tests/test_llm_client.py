"""Unit tests for the OpenAI wrapper at its public seam.

The wire is faked with an httpx2.MockTransport injected through the SDK's
http_client hook, so tests exercise real request/response handling, retry
behavior, usage accounting and logging — no network, no database.
"""

import json

import httpx2
import pytest
from openai import APIStatusError

from app.llm.client import LlmCallError, LlmNotConfiguredError, OpenAiClient
from tests.fake_openai import TEST_KEY, completion_body, fake_llm_client, make_settings


class TestConfiguration:
    def test_empty_api_key_fails_fast(self) -> None:
        with pytest.raises(LlmNotConfiguredError):
            OpenAiClient(make_settings(openai_api_key=""))


class TestComplete:
    async def test_returns_text_and_usage_cost(self) -> None:
        async with fake_llm_client("the answer", prompt_tokens=100, completion_tokens=20) as (
            client,
            requests,
        ):
            result = await client.complete(system="be brief", user="question")

        assert result.text == "the answer"
        assert result.model == "gpt-4o-mini"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 20
        # Independent worked example: 100/1M * $0.15 + 20/1M * $0.60.
        assert result.cost_usd == pytest.approx(0.000027)
        sent = json.loads(requests[0].content)
        assert sent["model"] == "gpt-4o-mini"
        assert sent["messages"] == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "question"},
        ]

    async def test_logs_tokens_and_cost_per_call(self, caplog: pytest.LogCaptureFixture) -> None:
        async with fake_llm_client("ok", prompt_tokens=100, completion_tokens=20) as (
            client,
            _,
        ):
            with caplog.at_level(20, logger="app.llm.client"):
                await client.complete(system="s", user="u")

        line = caplog.text
        assert "llm call" in line
        assert "model=gpt-4o-mini" in line
        assert "prompt_tokens=100" in line
        assert "completion_tokens=20" in line
        assert "cost_usd=0.000027" in line
        assert TEST_KEY not in line

    async def test_rate_limit_retried_then_succeeds(self) -> None:
        calls: list[int] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx2.Response(429, headers={"Retry-After": "0"}, content=b"{}")
            body = completion_body("recovered", prompt_tokens=10, completion_tokens=5)
            return httpx2.Response(200, content=json.dumps(body).encode())

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(openai_max_retries=1), http_client=wire)
            result = await client.complete(system="s", user="u")

        assert result.text == "recovered"
        assert len(calls) == 2

    async def test_persistent_error_surfaces_as_llm_call_error(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(500, content=b"boom")

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(openai_max_retries=1), http_client=wire)
            with pytest.raises(LlmCallError) as excinfo:
                await client.complete(system="s", user="u")
        assert isinstance(excinfo.value.__cause__, APIStatusError)

    async def test_configured_timeout_reaches_the_wire(self) -> None:
        # httpx enforces timeouts in its connection pool, which MockTransport
        # bypasses — so assert the wrapper propagates the configured timeout
        # onto outgoing requests rather than simulating a slow endpoint.
        captured: list[object] = []

        class CaptureTransport(httpx2.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
                captured.append(request.extensions.get("timeout"))
                return httpx2.Response(200, content=json.dumps(completion_body("ok")).encode())

        async with httpx2.AsyncClient(transport=CaptureTransport()) as wire:
            client = OpenAiClient(make_settings(openai_timeout_seconds=0.1), http_client=wire)
            await client.complete(system="s", user="u")

        assert captured, "no outgoing request observed"
        timeout = captured[0]
        assert timeout is not None
        assert timeout["connect"] == pytest.approx(0.1)  # type: ignore[index]
        assert timeout["read"] == pytest.approx(0.1)  # type: ignore[index]
