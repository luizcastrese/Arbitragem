"""OpenAI: Responses API com parse estruturado, de forma explícita deste adapter."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Type

from openai import OpenAI
from pydantic import BaseModel

from app.llm.errors import (
    LLMCallError,
    LLMQuotaExceeded,
    LLMTimeout,
    LLMTransientError,
    LLMUnavailable,
)
from app.llm.base import bounded_backoff, is_transient, log_call
from app.llm.schemas import ExecutionPolicy, LLMProvider, StructuredGenerationResult


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, timeout_seconds: float = 60.0):
        if not api_key or api_key == "your_key_here":
            raise LLMUnavailable("OPENAI_API_KEY is not configured")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def _client(self, timeout: float) -> OpenAI:
        return OpenAI(api_key=self._api_key, timeout=timeout)

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

        while attempts <= max_retries:
            attempts += 1
            t0 = time.perf_counter()
            try:
                response = self._client(timeout).responses.parse(
                    model=execution_policy.model,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": json.dumps(user_payload, ensure_ascii=False),
                        },
                    ],
                    text_format=response_model,
                )
            except LLMUnavailable:
                raise
            except Exception as exc:
                latency = (time.perf_counter() - t0) * 1000
                last_error = exc
                if getattr(exc, "code", None) == "insufficient_quota":
                    log_call(
                        provider=self.name,
                        model=execution_policy.model,
                        task=task,
                        attempts=attempts,
                        latency_ms=latency,
                        error="quota",
                    )
                    raise LLMQuotaExceeded("OpenAI project has no available quota") from exc
                if "timeout" in type(exc).__name__.lower():
                    log_call(
                        provider=self.name,
                        model=execution_policy.model,
                        task=task,
                        attempts=attempts,
                        latency_ms=latency,
                        error="timeout",
                    )
                    if attempts <= max_retries:
                        time.sleep(bounded_backoff(attempts))
                        continue
                    raise LLMTimeout("OpenAI request timed out") from exc
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
                raise LLMCallError(f"OpenAI request failed: {type(exc).__name__}") from exc

            latency = (time.perf_counter() - t0) * 1000
            if response.output_parsed is None:
                raise LLMCallError("OpenAI returned no structured output")
            parsed = response.output_parsed
            if not isinstance(parsed, BaseModel):
                parsed = response_model.model_validate(
                    parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
                )
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
                prompt_tokens=getattr(usage, "input_tokens", None),
                completion_tokens=getattr(usage, "output_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                latency_ms=latency,
                attempts=attempts,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
            )

        raise LLMTransientError(f"OpenAI retries exhausted: {type(last_error).__name__}")

    def generate_embedding(self, text: str, model: str) -> list:
        try:
            response = self._client(self._timeout).embeddings.create(
                model=model,
                input=text,
                encoding_format="float",
            )
        except LLMUnavailable:
            raise
        except Exception as exc:
            if getattr(exc, "code", None) == "insufficient_quota":
                raise LLMQuotaExceeded("OpenAI project has no available quota") from exc
            if is_transient(exc):
                raise LLMTransientError(type(exc).__name__) from exc
            raise LLMCallError(f"Embedding request failed: {type(exc).__name__}") from exc
        return response.data[0].embedding
