"""Thin OpenAI wrapper: the only module that touches the OpenAI SDK.

Owns timeout/retry/rate-limit configuration (delegated to the SDK's built-in
jittered backoff), converts SDK failures into layer-local errors, and logs
token usage + cost per call for trace/cost accounting. No framework types in
or out; services consume results as plain dataclasses.
"""

import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, cast

# The SDK vendors its own httpx fork (httpx2); its client/timeout types must
# match, so this module uses httpx2 everywhere it touches the SDK.
import httpx2
from openai import AsyncOpenAI, ContentFilterFinishReasonError, LengthFinishReasonError, OpenAIError
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from openai.types.completion_usage import CompletionUsage
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.cost import cost_usd

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

# Services persist one usage row per call through a sink they hand down to
# the leaf functions that make LLM calls; the client itself stays DB-free.
UsageSink = Callable[["LlmUsage"], Awaitable[None]]

# Tool arguments are logged for audit but truncated: they may carry document
# text or identifiers, and the trace is for debugging, not full content.
_TOOL_ARGS_LOG_LIMIT = 200


def _redact(arguments: dict[str, Any]) -> str:
    rendered = json.dumps(arguments)
    if len(rendered) > _TOOL_ARGS_LOG_LIMIT:
        rendered = rendered[:_TOOL_ARGS_LOG_LIMIT] + "…"
    return rendered


@dataclass(frozen=True)
class LlmUsage:
    """The usage facts of one completed call: what it cost in tokens, USD, and
    wall time. Produced where the call happens so callers can persist it."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


class LlmError(Exception):
    """Base for LLM-layer failures; carries no HTTP semantics."""


class LlmNotConfiguredError(LlmError):
    def __init__(self) -> None:
        super().__init__("LLM client not configured: OPENAI_API_KEY is empty")


class LlmCallError(LlmError):
    """The call failed at the transport/API level after SDK retries."""

    def __init__(self, model: str, cause: Exception) -> None:
        self.model = model
        super().__init__(f"llm call failed model={model}: {cause}")


class LlmOutputError(LlmError):
    """The model replied but the output failed schema validation.

    `usage` carries the call's spend when the reply itself was the problem
    (refusals: the usage arrived with the response) so the caller can still
    account for tokens the model burned on output nothing was done with.
    """

    def __init__(self, message: str, usage: LlmUsage | None = None) -> None:
        self.usage = usage
        super().__init__(message)


@dataclass(frozen=True)
class LlmResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


@dataclass(frozen=True)
class LlmStructuredResult[ModelT]:
    """The parsed structured output of one call, with its usage record."""

    data: ModelT
    usage: LlmUsage


@dataclass(frozen=True)
class LlmEmbeddingResult:
    """One vector per input text (input order), with the call's usage record."""

    vectors: list[list[float]]
    usage: LlmUsage


@dataclass(frozen=True)
class LlmTool:
    """One callable tool the model may invoke mid-completion.

    Safe-tool-design contract (docs/llm-boundaries.md): handlers must be
    side-effect-free reads. Any tool that writes needs human confirmation in
    the loop before it is ever registered here — the LLM decides *whether*
    to call a tool, never *whether* a side effect happens.
    """

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments object
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class OpenAiClient:
    def __init__(
        self, settings: Settings, *, http_client: httpx2.AsyncClient | None = None
    ) -> None:
        if not settings.openai_api_key:
            raise LlmNotConfiguredError()
        self._model = settings.openai_model
        self._embedding_model = settings.openai_embedding_model
        self._timeout = httpx2.Timeout(settings.openai_timeout_seconds)
        self._owns_client = http_client is None
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=self._timeout,
            max_retries=settings.openai_max_retries,
            http_client=http_client,
        )

    async def aclose(self) -> None:
        # An injected http_client is owned by the caller; only close our own.
        if self._owns_client:
            await self._client.close()

    async def complete(self, *, system: str, user: str) -> LlmResult:
        """One chat completion with the configured model."""
        started = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # Explicit per request: the SDK does not apply its configured
                # timeout to a caller-injected http_client.
                timeout=self._timeout,
            )
        except OpenAIError as exc:
            raise LlmCallError(self._model, exc) from exc
        prompt_tokens, completion_tokens, cost = self._usage_cost(response.usage)
        usage = self._log_usage(self._model, prompt_tokens, completion_tokens, cost, started)
        text = response.choices[0].message.content or ""
        return LlmResult(
            text=text,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
        )

    async def complete_structured(
        self, schema: type[ModelT], *, system: str, user: str
    ) -> LlmStructuredResult[ModelT]:
        """Chat completion constrained to `schema` via structured outputs.

        Returns the parsed data together with the call's usage record. Raises
        LlmOutputError when the model's reply fails validation against the
        schema (including refusals and truncation), LlmCallError when the call
        itself fails.
        """
        started = time.monotonic()
        rejected = f"model output failed schema validation model={self._model}"
        try:
            response = await self._client.beta.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                timeout=self._timeout,
            )
        except (LengthFinishReasonError, ContentFilterFinishReasonError, ValidationError) as exc:
            # Before OpenAIError: these subclass it, and they mean the reply
            # came back but is not usable output. The SDK raises them raw from
            # .parse() without exposing usage, so the tokens spent are lost to
            # accounting here (see docs/llm-boundaries.md trace-hygiene gap).
            logger.warning(
                "llm output rejected model=%s reason=%s usage=unavailable",
                self._model,
                type(exc).__name__,
            )
            raise LlmOutputError(rejected) from exc
        except OpenAIError as exc:
            raise LlmCallError(self._model, exc) from exc
        prompt_tokens, completion_tokens, cost = self._usage_cost(response.usage)
        usage = self._log_usage(self._model, prompt_tokens, completion_tokens, cost, started)
        parsed = response.choices[0].message.parsed
        if parsed is None:
            # Refusal path: usage arrived with the response, so it is logged
            # and attached for the caller to persist.
            raise LlmOutputError(rejected, usage)
        return LlmStructuredResult(data=parsed, usage=usage)

    async def embed(self, texts: Sequence[str]) -> LlmEmbeddingResult:
        """Embed texts with the configured embedding model, one vector per text.

        The wire may return data out of input order; vectors are re-sorted by
        index so result.vectors[i] always corresponds to texts[i]. Raises
        LlmCallError when the call fails.
        """
        started = time.monotonic()
        try:
            response = await self._client.embeddings.create(
                model=self._embedding_model,
                input=list(texts),
                timeout=self._timeout,
            )
        except OpenAIError as exc:
            raise LlmCallError(self._embedding_model, exc) from exc
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        cost = cost_usd(self._embedding_model, prompt_tokens=prompt_tokens, completion_tokens=0)
        usage = self._log_usage(self._embedding_model, prompt_tokens, 0, cost, started)
        by_index = sorted(response.data, key=lambda item: item.index)
        return LlmEmbeddingResult(vectors=[item.embedding for item in by_index], usage=usage)

    async def stream_complete(self, *, system: str, user: str) -> AsyncIterator[str]:
        """Stream one chat completion, yielding text deltas as they arrive.

        Usage is requested via stream_options and logged once when the stream
        ends, so cost accounting matches the non-streaming path exactly.
        Raises LlmCallError when the call fails mid-stream.
        """
        started = time.monotonic()
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                stream=True,
                stream_options={"include_usage": True},
                timeout=self._timeout,
            )
        except OpenAIError as exc:
            raise LlmCallError(self._model, exc) from exc
        # Usage arrives in the final chunk; a consumer that breaks out early
        # never sees it. The tokens are spent either way, so the abort is
        # logged as unaccountable instead of silently dropping the call.
        prompt_tokens = completion_tokens = 0
        logged = False
        try:
            try:
                async for chunk in stream:
                    if chunk.usage is not None:
                        prompt_tokens = chunk.usage.prompt_tokens
                        completion_tokens = chunk.usage.completion_tokens
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            except OpenAIError as exc:
                raise LlmCallError(self._model, exc) from exc
            cost = cost_usd(
                self._model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            self._log_usage(self._model, prompt_tokens, completion_tokens, cost, started)
            logged = True
        finally:
            if not logged:
                logger.warning("llm stream aborted model=%s usage=unavailable", self._model)

    async def complete_with_tools(
        self, *, system: str, user: str, tools: Sequence[LlmTool], max_rounds: int = 3
    ) -> LlmResult:
        """Run one tool-calling loop until the model produces a final answer.

        The model may request tool calls; handlers execute server-side and
        their results are fed back as tool-role data until the model answers
        in plain text. `max_rounds` bounds the loop so a model stuck requesting
        tools fails as LlmOutputError instead of burning tokens forever.
        """
        by_name = {tool.name: tool for tool in tools}
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        wire_tools: list[ChatCompletionToolParam] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]
        started = time.monotonic()
        # Usage is accumulated across all rounds and logged once at the end,
        # matching the one `llm call` line per call contract.
        prompt_tokens = completion_tokens = 0
        for _ in range(max_rounds):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=wire_tools,
                    timeout=self._timeout,
                )
            except OpenAIError as exc:
                raise LlmCallError(self._model, exc) from exc
            if not response.choices:
                raise LlmOutputError(f"model returned no choices model={self._model}")
            message = response.choices[0].message
            if response.usage is not None:
                prompt_tokens += response.usage.prompt_tokens
                completion_tokens += response.usage.completion_tokens
            tool_calls = message.tool_calls
            if not tool_calls:
                cost = cost_usd(
                    self._model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                usage = self._log_usage(
                    self._model, prompt_tokens, completion_tokens, cost, started
                )
                return LlmResult(
                    text=message.content or "",
                    model=usage.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=usage.cost_usd,
                    latency_ms=usage.latency_ms,
                )
            messages.append(cast(ChatCompletionAssistantMessageParam, message.model_dump()))
            for call in tool_calls:
                if call.type != "function":
                    raise LlmOutputError(f"model requested unsupported tool call type {call.type}")
                tool = by_name.get(call.function.name)
                if tool is None:
                    raise LlmOutputError(f"model requested unregistered tool {call.function.name}")
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    # Tool arguments are model output; malformed ones fail the
                    # same gate as any other schema-invalid reply.
                    raise LlmOutputError(
                        f"model tool arguments failed to parse model={self._model}"
                    ) from exc
                logger.info("llm tool call tool=%s arguments=%s", tool.name, _redact(arguments))
                try:
                    result = await tool.handler(arguments)
                except LlmError:
                    raise
                except Exception as exc:
                    raise LlmError(f"tool handler failed tool={tool.name}: {exc}") from exc
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result),
                    }
                )
        raise LlmOutputError(f"model exceeded {max_rounds} tool rounds without a final answer")

    def _usage_cost(self, usage: CompletionUsage | None) -> tuple[int, int, float]:
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return (
            prompt_tokens,
            completion_tokens,
            cost_usd(self._model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )

    def _log_usage(
        self, model: str, prompt_tokens: int, completion_tokens: int, cost: float, started: float
    ) -> LlmUsage:
        """One log line per call, and the record returned so callers persist
        the same facts instead of re-deriving them."""
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "llm call model=%s prompt_tokens=%d completion_tokens=%d cost_usd=%.6f latency_ms=%d",
            model,
            prompt_tokens,
            completion_tokens,
            cost,
            latency_ms,
        )
        return LlmUsage(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )
