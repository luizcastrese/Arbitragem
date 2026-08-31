"""Provedor de contrato para testes. Nenhuma chamada de rede."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel

from app.llm.errors import LLMSchemaError, LLMUnavailable
from app.llm.schemas import ExecutionPolicy, LLMProvider, StructuredGenerationResult

Scripted = Union[BaseModel, Dict[str, Any], BaseException, Callable[..., Any]]


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(
        self,
        responses: Optional[Dict[str, Scripted]] = None,
        embeddings: Optional[List[float]] = None,
    ):
        self.responses = dict(responses or {})
        self.embeddings = embeddings or [0.0, 1.0, 0.0]
        self.calls: List[Dict[str, Any]] = []

    def script(self, task: str, response: Scripted) -> None:
        self.responses[task] = response

    def generate_structured(
        self,
        task: str,
        system_prompt: str,
        user_payload: Dict[str, Any],
        response_model: Type[BaseModel],
        execution_policy: ExecutionPolicy,
    ) -> StructuredGenerationResult:
        self.calls.append(
            {
                "task": task,
                "model": execution_policy.model,
                "provider": execution_policy.provider,
                "payload_keys": sorted(user_payload.keys()),
            }
        )
        scripted = self.responses.get(task)
        if scripted is None:
            raise LLMUnavailable("FakeProvider has no scripted response for this task")
        if callable(scripted) and not isinstance(scripted, BaseModel):
            scripted = scripted(
                task=task,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_model=response_model,
                execution_policy=execution_policy,
            )
        if isinstance(scripted, BaseException):
            raise scripted
        if isinstance(scripted, BaseModel):
            parsed = scripted
        elif isinstance(scripted, dict):
            parsed = response_model.model_validate(scripted)
        else:
            raise LLMSchemaError("FakeProvider scripted output is not structured")
        now = datetime.now(timezone.utc)
        return StructuredGenerationResult(
            parsed_output=parsed,
            requested_provider=execution_policy.provider,
            requested_model=execution_policy.model,
            effective_provider=self.name,
            effective_model=execution_policy.model,
            provider_response_id=f"fake-{uuid4().hex[:12]}",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1.0,
            attempts=1,
            started_at=now,
            completed_at=now,
        )

    def generate_embedding(self, text: str, model: str) -> list:
        self.calls.append({"task": "embedding", "model": model, "chars": len(text)})
        return list(self.embeddings)
