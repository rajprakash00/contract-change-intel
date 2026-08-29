# ADR-003: Direct OpenAI SDK behind a thin wrapper (no LLM framework)

## Context

Week 2 introduces LLM calls (extraction, later diffing and impact mapping).
PLAN.md names OpenAI as primary provider with the Anthropic SDK as a
week-2 comparison, and bars LangChain/LangGraph from core pipelines. The
wrapper must own timeouts, retries, rate-limit handling, and per-call token +
cost accounting.

## Decision

Call the OpenAI SDK directly through one thin wrapper, `app/llm/client.py` —
the only module that imports the SDK. The wrapper:

- builds `AsyncOpenAI` from `app/config.py` settings (`openai_api_key`,
  `openai_base_url`, `openai_model`, `openai_timeout_seconds`,
  `openai_max_retries`); an empty key fails fast with `LlmNotConfiguredError`.
- delegates retry-with-jittered-backoff and 429 rate-limit handling to the
  SDK's built-in machinery instead of reimplementing it.
- translates every SDK failure into layer-local errors (`LlmCallError`,
  `LlmOutputError`, `LlmNotConfiguredError`) so callers never see SDK types.
- logs one structured `llm call` line per call: model, prompt/completion
  tokens, cost (USD, from `app/llm/cost.py`), latency — the trace/cost record
  PLAN.md requires. The API key is never logged.

Structured outputs use the SDK's schema-driven `.parse` with Pydantic models;
services own the schemas (see `app/services/extraction.py`).

Consequences:

- Provider swap or comparison benchmark touches one module.
- Cost math is pure (`app/llm/cost.py`) with a hand-maintained pricing table;
  prices drift from OpenAI list prices unless updated — locked by unit tests
  with known-good literals.

## Rejected alternative

LangChain/LangGraph. Rejected because the framework's abstraction surface
(ret chains, prompt templates, agent loops) hides exactly the failure modes
this product must audit — retries, token spend, schema violations — and adds
a dependency for what is, so far, two SDK calls.
