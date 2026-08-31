"""Compatibilidade temporária com a API anterior de `app.core.llm`.

Os agentes e as evals históricas importam `call_openai_structured`. A
implementação agora delega à camada multi-provider. Não use esta API em
código novo: prefira `app.llm.generate_structured`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from app.llm.errors import LLMCallError, LLMQuotaExceeded, LLMUnavailable
from app.llm.registry import (
    execution_policy_for,
    generate_embedding as _generate_embedding,
    generate_structured,
)
from app.llm.schemas import ExecutionPolicy, StructuredGenerationResult


def openai_configured() -> bool:
    from app.core.config import get_settings

    return get_settings().openai_enabled or get_settings().openrouter_enabled


@dataclass(frozen=True)
class LLMResult:
    """Saída estruturada mais a procedência da chamada.

    `model` é o modelo que a API declara ter respondido, não o que pedimos:
    aliases como `gpt-5-mini` resolvem para uma versão datada, e é essa que
    precisa ficar registrada na decisão.
    """

    data: Dict[str, Any]
    model: str
    response_id: Optional[str] = None
    usage: Dict[str, int] = field(default_factory=dict)
    provider: str = ""
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    attempts: int = 1
    latency_ms: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


def _result_from_structured(result: StructuredGenerationResult) -> LLMResult:
    parsed = result.parsed_output
    data = parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
    usage = {}
    if isinstance(result.prompt_tokens, int):
        usage["input_tokens"] = result.prompt_tokens
    if isinstance(result.completion_tokens, int):
        usage["output_tokens"] = result.completion_tokens
    if isinstance(result.total_tokens, int):
        usage["total_tokens"] = result.total_tokens
    return LLMResult(
        data=data,
        model=result.effective_model,
        response_id=result.provider_response_id,
        usage=usage,
        provider=result.effective_provider,
        fallback_used=result.fallback_used,
        fallback_reason=result.fallback_reason,
        attempts=result.attempts,
        latency_ms=result.latency_ms,
        started_at=result.started_at.isoformat() if result.started_at else None,
        completed_at=result.completed_at.isoformat() if result.completed_at else None,
    )


def call_openai_structured(
    system_prompt: str,
    user_payload: Dict[str, Any],
    response_model: Type[BaseModel],
    model: Optional[str] = None,
    agent: str = "generic",
) -> LLMResult:
    policy = execution_policy_for(agent)
    if model:
        policy = ExecutionPolicy(
            provider=policy.provider,
            model=model,
            timeout_seconds=policy.timeout_seconds,
            max_retries=policy.max_retries,
            fallback=policy.fallback,
            agent=agent,
        )
    result = generate_structured(
        task=agent,
        system_prompt=system_prompt,
        user_payload=user_payload,
        response_model=response_model,
        execution_policy=policy,
    )
    return _result_from_structured(result)


def generate_embedding(text: str, model: Optional[str] = None) -> List[float]:
    return _generate_embedding(text, model=model)
