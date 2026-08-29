"""Thin OpenAI wrapper: the only module that touches the OpenAI SDK.

Owns timeout/retry/rate-limit configuration (delegated to the SDK's built-in
jittered backoff), converts SDK failures into layer-local errors, and logs
token usage + cost per call for trace/cost accounting. No framework types in
or out; services consume results as plain dataclasses.
"""

import logging
import time
from dataclasses import dataclass
from typing import TypeVar

# The SDK vendors its own httpx fork (httpx2); its client/timeout types must
# match, so this module uses httpx2 everywhere it touches the SDK.
import httpx2
from openai import AsyncOpenAI, ContentFilterFinishReasonError, LengthFinishReasonError, OpenAIError
from openai.types.completion_usage import CompletionUsage
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.cost import cost_usd

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


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
    """The model replied but the output failed schema validation."""


@dataclass(frozen=True)
class LlmResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class OpenAiClient:
    def __init__(
        self, settings: Settings, *, http_client: httpx2.AsyncClient | None = None
    ) -> None:
        if not settings.openai_api_key:
            raise LlmNotConfiguredError()
        self._model = settings.openai_model
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
        self._log_usage(prompt_tokens, completion_tokens, cost, started)
        text = response.choices[0].message.content or ""
        return LlmResult(
            text=text,
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )

    async def complete_structured(self, schema: type[ModelT], *, system: str, user: str) -> ModelT:
        """Chat completion constrained to `schema` via structured outputs.

        Raises LlmOutputError when the model's reply fails validation against
        the schema (including refusals and truncation), LlmCallError when the
        call itself fails.
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
        self._log_usage(prompt_tokens, completion_tokens, cost, started)
        parsed = response.choices[0].message.parsed
        if parsed is None:
            # Refusal path: usage arrived with the response, so it is logged.
            raise LlmOutputError(rejected)
        return parsed

    def _usage_cost(self, usage: CompletionUsage | None) -> tuple[int, int, float]:
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return (
            prompt_tokens,
            completion_tokens,
            cost_usd(self._model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )

    def _log_usage(
        self, prompt_tokens: int, completion_tokens: int, cost: float, started: float
    ) -> None:
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "llm call model=%s prompt_tokens=%d completion_tokens=%d cost_usd=%.6f latency_ms=%d",
            self._model,
            prompt_tokens,
            completion_tokens,
            cost,
            latency_ms,
        )
