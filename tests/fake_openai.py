"""Shared fake OpenAI wire for LLM tests: httpx2.MockTransport through the
real OpenAiClient, so tests exercise request/response handling, parsing and
validation without network or database.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2

from app.config import Settings
from app.llm.client import OpenAiClient

TEST_KEY = "test-key"


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, Any] = {
        "openai_api_key": TEST_KEY,
        "openai_model": "gpt-4o-mini",
        "openai_max_retries": 0,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def completion_body(
    text: str,
    *,
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@asynccontextmanager
async def fake_llm_client(
    content: str,
    *,
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
    finish_reason: str = "stop",
) -> AsyncIterator[tuple[OpenAiClient, list[httpx2.Request]]]:
    """One client whose wire always answers with the given completion.

    Yields the client and every request it sent, for callers that assert on
    outgoing messages. Closes the client's wire on exit.
    """
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        body = completion_body(
            content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )
        return httpx2.Response(200, content=json.dumps(body).encode())

    wire = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = OpenAiClient(make_settings(), http_client=wire)
    try:
        yield client, requests
    finally:
        # OpenAiClient.aclose() skips caller-owned wires; close ours here.
        await wire.aclose()


def tool_call_body(
    name: str,
    arguments: dict[str, Any],
    *,
    call_id: str = "call-test",
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
) -> dict[str, Any]:
    """One assistant turn that requests a single tool call."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def stream_body(
    *deltas: str,
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
) -> bytes:
    """SSE wire for a streaming completion: one content chunk per delta, a
    final usage-only chunk (stream_options={"include_usage": True}), then [DONE].
    """
    lines: list[str] = []
    for delta in deltas:
        chunk = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1_700_000_000,
            "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
        }
        lines.append(f"data: {json.dumps(chunk)}\n\n")
    usage_chunk = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1_700_000_000,
        "model": "gpt-4o-mini",
        "choices": [],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    lines.append(f"data: {json.dumps(usage_chunk)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


@asynccontextmanager
async def fake_streaming_llm_client(
    *deltas: str,
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
) -> AsyncIterator[tuple[OpenAiClient, list[httpx2.Request]]]:
    requests: list[httpx2.Request] = []
    payload = stream_body(*deltas, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            content=payload,
            headers={"content-type": "text/event-stream"},
        )

    wire = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = OpenAiClient(make_settings(), http_client=wire)
    try:
        yield client, requests
    finally:
        # OpenAiClient.aclose() skips caller-owned wires; close ours here.
        await wire.aclose()
