"""OpenRouter: Chat Completions + JSON schema, validação Pydantic local.

Não usa Responses API. O adapter declara essa incompatibilidade de propósito.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Type

from openai import OpenAI
from pydantic import BaseModel

from app.llm.base import bounded_backoff, is_transient, log_call, parse_structured_json
from app.llm.errors import (
    LLMCallError,
    LLMQuotaExceeded,
    LLMTimeout,
    LLMTransientError,
    LLMUnavailable,
)
from app.llm.schemas import ExecutionPolicy, LLMProvider, StructuredGenerationResult

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_OPENROUTER_BASE_URL,
        timeout_seconds: float = 60.0,
    ):
        if not api_key:
            raise LLMUnavailable("OPENROUTER_API_KEY is not configured")
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_OPENROUTER_BASE_URL).rstrip("/")
        self._timeout = timeout_seconds

    def _client(self, timeout: float) -> OpenAI:
        return OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=timeout,
        )

    def generate_structured(
        self,
        task: str,
        system_prompt: str,
        user_payload: Dict[str, Any],
        response_model: Type[BaseModel],
        execution_policy: ExecutionPolicy,
    ) -> StructuredGenerationResult:
        started = datetime.now(timezone.utc)
        attempts = 0
        last_error: BaseException | None = None
        timeout = execution_policy.timeout_seconds or self._timeout
        max_retries = max(0, execution_policy.max_retries)
        schema = response_model.model_json_schema()

        while attempts <= max_retries:
            attempts += 1
            t0 = time.perf_counter()
            try:
                response = self._client(timeout).chat.completions.create(
                    model=execution_policy.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": json.dumps(user_payload, ensure_ascii=False),
                        },
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": response_model.__name__,
                            "strict": True,
                            "schema": schema,
                        },
                    },
                )
            except Exception as exc:
                latency = (time.perf_counter() - t0) * 1000
                last_error = exc
                if getattr(exc, "code", None) == "insufficient_quota":
                    raise LLMQuotaExceeded("OpenRouter quota exceeded") from exc
                if "timeout" in type(exc).__name__.lower():
                    if attempts <= max_retries:
                        time.sleep(bounded_backoff(attempts))
                        continue
                    raise LLMTimeout("OpenRouter request timed out") from exc
                if is_transient(exc) and attempts <= max_retries:
                    log_call(
                        provider=self.name,
                        model=execution_policy.model,
                        task=task,
                        attempts=attempts,
                        latency_ms=latency,
                        error="transient",
                    )
                    time.sleep(bounded_backoff(attempts))
                    continue
                log_call(
                    provider=self.name,
                    model=execution_policy.model,
                    task=task,
                    attempts=attempts,
                    latency_ms=latency,
                    error=type(exc).__name__,
                )
                raise LLMCallError(f"OpenRouter request failed: {type(exc).__name__}") from exc

            latency = (time.perf_counter() - t0) * 1000
            choice = (response.choices or [None])[0]
            content = ""
            if choice and getattr(choice, "message", None):
                content = choice.message.content or ""
            parsed = parse_structured_json(content, response_model)
            usage = getattr(response, "usage", None)
            log_call(
                provider=self.name,
                model=getattr(response, "model", None) or execution_policy.model,
                task=task,
                attempts=attempts,
                latency_ms=latency,
            )
            return StructuredGenerationResult(
                parsed_output=parsed,
                requested_provider=self.name,
                requested_model=execution_policy.model,
                effective_provider=self.name,
                effective_model=getattr(response, "model", None) or execution_policy.model,
                provider_response_id=getattr(response, "id", None),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                latency_ms=latency,
                attempts=attempts,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
            )

        raise LLMTransientError(
            f"OpenRouter retries exhausted: {type(last_error).__name__}"
        )

    def generate_embedding(self, text: str, model: str) -> list:
        raise LLMCallError("OpenRouter adapter does not provide embeddings")
