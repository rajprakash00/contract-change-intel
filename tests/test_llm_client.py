"""Unit tests for the OpenAI wrapper at its public seam.

The wire is faked with an httpx2.MockTransport injected through the SDK's
http_client hook, so tests exercise real request/response handling, retry
behavior, usage accounting and logging — no network, no database.
"""

import json
from typing import Any

import httpx2
import pytest
from openai import APIStatusError
from pydantic import BaseModel

from app.llm.client import (
    LlmCallError,
    LlmError,
    LlmNotConfiguredError,
    LlmOutputError,
    OpenAiClient,
)
from tests.fake_openai import (
    TEST_KEY,
    completion_body,
    fake_embedding_client,
    fake_llm_client,
    fake_streaming_llm_client,
    make_settings,
    tool_call_body,
)


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


class TestStreaming:
    async def test_yields_deltas_in_order(self) -> None:
        async with fake_streaming_llm_client("Hel", "lo w", "orld") as (client, _):
            deltas = [delta async for delta in client.stream_complete(system="s", user="u")]

        assert deltas == ["Hel", "lo w", "orld"]
        assert "".join(deltas) == "Hello world"

    async def test_logs_tokens_and_cost_once_after_the_stream(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async with fake_streaming_llm_client("a", "b", prompt_tokens=100, completion_tokens=20) as (
            client,
            _,
        ):
            with caplog.at_level(20, logger="app.llm.client"):
                async for _ in client.stream_complete(system="s", user="u"):
                    pass

        lines = [line for line in caplog.text.splitlines() if "llm call" in line]
        assert len(lines) == 1, "one usage line per streamed call, at the end"
        assert "prompt_tokens=100" in lines[0]
        assert "completion_tokens=20" in lines[0]
        assert "cost_usd=0.000027" in lines[0]
        assert TEST_KEY not in caplog.text

    async def test_wire_error_surfaces_as_llm_call_error(self) -> None:
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda request: httpx2.Response(500, content=b"boom"))
        ) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            with pytest.raises(LlmCallError):
                async for _ in client.stream_complete(system="s", user="u"):
                    pass


class TestCompleteWithTools:
    def _tool(self, calls: list[dict]) -> Any:
        from app.llm.client import LlmTool

        async def handler(arguments: dict) -> dict:
            calls.append(arguments)
            return {"balance": "42.00"}

        return LlmTool(
            name="get_balance",
            description="Look up an account balance",
            parameters={"type": "object", "properties": {"account": {"type": "string"}}},
            handler=handler,
        )

    async def test_executes_tool_and_returns_final_text(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[dict] = []
        tool = self._tool(calls)
        bodies = [
            tool_call_body("get_balance", {"account": "acc-1"}),
            completion_body("The balance is 42.00", prompt_tokens=30, completion_tokens=5),
        ]

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=json.dumps(bodies.pop(0)).encode())

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            with caplog.at_level(20, logger="app.llm.client"):
                result = await client.complete_with_tools(system="s", user="u", tools=[tool])

        assert result.text == "The balance is 42.00"
        assert calls == [{"account": "acc-1"}]
        assert "llm tool call" in caplog.text
        assert "tool=get_balance" in caplog.text
        assert TEST_KEY not in caplog.text

    async def test_tool_result_fed_back_as_tool_message(self) -> None:
        calls: list[dict] = []
        tool = self._tool(calls)
        bodies = [
            tool_call_body("get_balance", {"account": "acc-1"}, call_id="call-9"),
            completion_body("done"),
        ]
        seen: list[dict] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(json.loads(request.content))
            return httpx2.Response(200, content=json.dumps(bodies.pop(0)).encode())

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            await client.complete_with_tools(system="s", user="u", tools=[tool])

        second = seen[1]["messages"]
        tool_message = next(m for m in second if m["role"] == "tool")
        # The result travels as tool-role data, keyed to the call id.
        assert tool_message["tool_call_id"] == "call-9"
        assert json.loads(tool_message["content"]) == {"balance": "42.00"}
        # The assistant's tool-call turn is preserved in the conversation.
        assert any(m.get("tool_calls") and m["tool_calls"][0]["id"] == "call-9" for m in second)

    async def test_declared_tools_reach_the_wire_as_functions(self) -> None:
        calls: list[dict] = []
        tool = self._tool(calls)
        bodies = [completion_body("no tools needed")]
        seen: list[dict] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(json.loads(request.content))
            return httpx2.Response(200, content=json.dumps(bodies.pop(0)).encode())

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            await client.complete_with_tools(system="s", user="u", tools=[tool])

        assert seen[0]["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "get_balance",
                    "description": "Look up an account balance",
                    "parameters": {
                        "type": "object",
                        "properties": {"account": {"type": "string"}},
                    },
                },
            }
        ]

    async def test_endless_tool_loop_is_bounded(self) -> None:
        calls: list[dict] = []
        tool = self._tool(calls)

        def handler(request: httpx2.Request) -> httpx2.Response:
            body = tool_call_body("get_balance", {"account": "acc-1"})
            return httpx2.Response(200, content=json.dumps(body).encode())

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            with pytest.raises(LlmOutputError):
                await client.complete_with_tools(system="s", user="u", tools=[tool], max_rounds=3)

        assert len(calls) == 3

    async def test_usage_across_tool_rounds_is_summed_in_one_log_line(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[dict] = []
        tool = self._tool(calls)
        bodies = [
            tool_call_body(
                "get_balance", {"account": "acc-1"}, prompt_tokens=10, completion_tokens=5
            ),
            completion_body("done", prompt_tokens=20, completion_tokens=8),
        ]

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=json.dumps(bodies.pop(0)).encode())

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            with caplog.at_level(20, logger="app.llm.client"):
                await client.complete_with_tools(system="s", user="u", tools=[tool])

        lines = [line for line in caplog.text.splitlines() if "llm call" in line]
        assert len(lines) == 1, "one usage line per call, covering every round"
        assert "prompt_tokens=30" in lines[0]
        assert "completion_tokens=13" in lines[0]

    async def test_malformed_tool_arguments_fail_as_llm_output_error(self) -> None:
        calls: list[dict] = []
        tool = self._tool(calls)
        body = tool_call_body("get_balance", {})
        body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "not json"

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=json.dumps(body).encode())

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            with pytest.raises(LlmOutputError):
                await client.complete_with_tools(system="s", user="u", tools=[tool])

        assert calls == [], "a handler must never run on unparseable arguments"

    async def test_failing_tool_handler_surfaces_as_llm_error(self) -> None:
        from app.llm.client import LlmTool

        async def broken_handler(arguments: dict) -> dict:
            raise RuntimeError("database down")

        tool = LlmTool(
            name="get_balance",
            description="d",
            parameters={"type": "object", "properties": {}},
            handler=broken_handler,
        )

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200, content=json.dumps(tool_call_body("get_balance", {})).encode()
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            with pytest.raises(LlmError) as excinfo:
                await client.complete_with_tools(system="s", user="u", tools=[tool])

        assert "tool handler failed" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, RuntimeError)


class TestEmbed:
    async def test_returns_vectors_matched_to_input_texts(self) -> None:
        # The wire deliberately returns data out of input order; the client
        # must sort by index so vectors align with the texts that produced them.
        vectors = [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]
        async with fake_embedding_client(vectors, prompt_tokens=9, data_order=[2, 0, 1]) as (
            client,
            requests,
        ):
            result = await client.embed(["a", "b", "c"])

        assert result.vectors == vectors
        sent = json.loads(requests[0].content)
        assert sent["model"] == "text-embedding-3-small"
        assert sent["input"] == ["a", "b", "c"]

    async def test_logs_embedding_usage_and_cost(self, caplog: pytest.LogCaptureFixture) -> None:
        async with fake_embedding_client([[1.0]], prompt_tokens=1_000_000) as (client, _):
            with caplog.at_level(20, logger="app.llm.client"):
                await client.embed(["text"])

        # Independent worked example: 1M input tokens at $0.02 / 1M.
        line = next(line for line in caplog.text.splitlines() if "llm call" in line)
        assert "model=text-embedding-3-small" in line
        assert "prompt_tokens=1000000" in line
        assert "cost_usd=0.020000" in line
        assert TEST_KEY not in caplog.text

    async def test_wire_error_surfaces_as_llm_call_error(self) -> None:
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda request: httpx2.Response(500, content=b"boom"))
        ) as wire:
            client = OpenAiClient(make_settings(), http_client=wire)
            with pytest.raises(LlmCallError):
                await client.embed(["text"])


class TestUsageRecords:
    """Every call path hands its per-call usage facts back to the caller, so
    services can persist them (issue #30): latency is measured where the call
    happens and travels with the result instead of dying in the log line."""

    async def test_complete_result_carries_latency_ms(self) -> None:
        async with fake_llm_client("ok") as (client, _):
            result = await client.complete(system="s", user="u")

        assert isinstance(result.latency_ms, int)
        assert result.latency_ms >= 0

    async def test_complete_structured_returns_data_with_usage_record(self) -> None:
        class Answer(BaseModel):
            value: int

        async with fake_llm_client(
            json.dumps({"value": 2}), prompt_tokens=100, completion_tokens=20
        ) as (client, _):
            result = await client.complete_structured(Answer, system="s", user="u")

        assert result.data == Answer(value=2)
        assert result.usage.model == "gpt-4o-mini"
        assert result.usage.prompt_tokens == 100
        assert result.usage.completion_tokens == 20
        # Independent worked example: 100/1M * $0.15 + 20/1M * $0.60.
        assert result.usage.cost_usd == pytest.approx(0.000027)
        assert isinstance(result.usage.latency_ms, int)
        assert result.usage.latency_ms >= 0

    async def test_embed_returns_vectors_with_usage_record(self) -> None:
        async with fake_embedding_client([[1.0]], prompt_tokens=1_000_000) as (client, _):
            result = await client.embed(["text"])

        assert result.vectors == [[1.0]]
        assert result.usage.model == "text-embedding-3-small"
        assert result.usage.prompt_tokens == 1_000_000
        assert result.usage.completion_tokens == 0
        # Independent worked example: 1M input tokens at $0.02 / 1M.
        assert result.usage.cost_usd == pytest.approx(0.02)
        assert result.usage.latency_ms >= 0


class TestStreamAbortAccounting:
    async def test_aborted_stream_is_logged_as_unaccountable(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async with fake_streaming_llm_client("a", "b") as (client, _):
            with caplog.at_level(30, logger="app.llm.client"):
                stream = client.stream_complete(system="s", user="u")
                async for _ in stream:
                    break
                # async-for on break leaves the generator suspended; closing it
                # here makes the abort (and its warning) deterministic.
                await stream.aclose()

        assert "usage=unavailable" in caplog.text
        assert TEST_KEY not in caplog.text
