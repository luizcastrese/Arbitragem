"""Procedência de cada etapa executada por IA.

Todo agente devolve, junto do resultado, um bloco `execution` que responde a
uma pergunta simples: com qual prompt e com qual modelo isso foi produzido?
Sem essa resposta, uma decisão não é reproduzível — e reprodutibilidade é o
que o procedimento promete.
"""

from __future__ import annotations

from typing import Dict, Optional
from uuid import uuid4

from app.core.config import get_settings
from app.core.llm import LLMResult
from app.core.prompt_registry import PromptVersion
from app.llm.schemas import StructuredGenerationResult


def openai_execution(prompt: PromptVersion, result: LLMResult) -> Dict:
    settings = get_settings()
    execution = {
        "mode": result.provider or "openai",
        "model": result.model,
        "model_requested": getattr(result, "provider", None) and None,
        "provider": result.provider or "openai",
        "provider_requested": result.provider or settings.llm_default_provider,
        "response_id": result.response_id,
        "prompt": prompt.as_reference(),
        "reason": None,
        "attempts": result.attempts,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "execution_id": uuid4().hex,
    }
    execution["model_requested"] = _requested_model_for(prompt.agent)
    if result.usage:
        execution["usage"] = result.usage
    if result.latency_ms is not None:
        execution["latency_ms"] = result.latency_ms
    if result.started_at:
        execution["started_at"] = result.started_at
    if result.completed_at:
        execution["completed_at"] = result.completed_at
    return execution


def structured_execution(
    prompt: PromptVersion,
    result: StructuredGenerationResult,
) -> Dict:
    execution = {
        "mode": result.effective_provider,
        "model": result.effective_model,
        "model_requested": result.requested_model,
        "provider": result.effective_provider,
        "provider_requested": result.requested_provider,
        "response_id": result.provider_response_id,
        "prompt": prompt.as_reference(),
        "reason": None,
        "attempts": result.attempts,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "execution_id": uuid4().hex,
        "latency_ms": result.latency_ms,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
    }
    usage = {}
    if isinstance(result.prompt_tokens, int):
        usage["input_tokens"] = result.prompt_tokens
    if isinstance(result.completion_tokens, int):
        usage["output_tokens"] = result.completion_tokens
    if isinstance(result.total_tokens, int):
        usage["total_tokens"] = result.total_tokens
    if usage:
        execution["usage"] = usage
    return execution


def fallback_execution(prompt: PromptVersion, reason: str) -> Dict:
    settings = get_settings()
    return {
        "mode": "safe_fallback",
        "model": None,
        "model_requested": _requested_model_for(prompt.agent),
        "provider": None,
        "provider_requested": _requested_provider_for(prompt.agent),
        "response_id": None,
        "prompt": prompt.as_reference(),
        "reason": reason,
        "attempts": 0,
        "fallback_used": False,
        "fallback_reason": None,
        "execution_id": uuid4().hex,
    }


def with_drift(execution: Dict, drift: Optional[Dict]) -> Dict:
    """Anexa a divergência entre o prompt travado no manifesto e o que rodou.

    `None` mantém o bloco intacto: ausência da chave significa "sem
    divergência detectada".
    """
    if drift:
        execution = {**execution, "prompt_drift": drift}
    return execution


def _requested_model_for(agent: str) -> str:
    settings = get_settings()
    return {
        "conciliator": settings.conciliator_model,
        "organizer": settings.organizer_model,
        "judge": settings.judge_model,
        "reviewer": settings.reviewer_model,
        "appeal": settings.appeal_model,
    }.get(agent, settings.openai_model)


def _requested_provider_for(agent: str) -> str:
    settings = get_settings()
    return {
        "conciliator": settings.conciliator_provider,
        "organizer": settings.organizer_provider,
        "judge": settings.judge_provider,
        "reviewer": settings.reviewer_provider,
        "appeal": settings.appeal_provider,
    }.get(agent, settings.llm_default_provider)
