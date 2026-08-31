"""Contratos da camada LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel


@dataclass(frozen=True)
class FallbackPolicy:
    provider: str
    model: str
    reason: str


@dataclass(frozen=True)
class ExecutionPolicy:
    provider: str
    model: str
    timeout_seconds: float = 60.0
    max_retries: int = 2
    fallback: Optional[FallbackPolicy] = None
    agent: str = ""


@dataclass
class StructuredGenerationResult:
    parsed_output: BaseModel
    requested_provider: str
    requested_model: str
    effective_provider: str
    effective_model: str
    provider_response_id: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    attempts: int = 1
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    raw_json: Optional[Dict[str, Any]] = None


class LLMProvider:
    name: str

    def generate_structured(
        self,
        task: str,
        system_prompt: str,
        user_payload: Dict[str, Any],
        response_model: Type[BaseModel],
        execution_policy: ExecutionPolicy,
    ) -> StructuredGenerationResult:
        raise NotImplementedError

    def generate_embedding(self, text: str, model: str) -> list:
        raise NotImplementedError
