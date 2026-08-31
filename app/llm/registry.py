"""Registro de provedores, allowlist e geração estruturada com fallback explícito."""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

from app.llm.errors import (
    LLMCallError,
    LLMPolicyError,
    LLMUnavailable,
)
from app.llm.fake_provider import FakeProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.openrouter_provider import OpenRouterProvider
from app.llm.schemas import ExecutionPolicy, LLMProvider, StructuredGenerationResult

_OVERRIDE: Optional[LLMProvider] = None


def set_provider_override(provider: Optional[LLMProvider]) -> None:
    """Injeta um provedor de contrato (testes). None restaura o registro real."""
    global _OVERRIDE
    _OVERRIDE = provider


def get_provider_override() -> Optional[LLMProvider]:
    return _OVERRIDE


def _settings():
    from app.core.config import get_settings

    return get_settings()


def allowed_providers() -> list:
    return list(_settings().llm_allowed_providers)


def allowed_models() -> list:
    return list(_settings().llm_allowed_models)


def provider_allowed(name: str) -> bool:
    allowed = allowed_providers()
    if not allowed:
        return name in {"openai", "openrouter", "fake"}
    return name in allowed


def model_allowed(model: str) -> bool:
    allowed = allowed_models()
    if not allowed:
        return True
    return model in allowed


def build_provider(name: str) -> LLMProvider:
    if _OVERRIDE is not None:
        return _OVERRIDE
    settings = _settings()
    if name == "fake":
        return FakeProvider()
    if name == "openai":
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            timeout_seconds=settings.llm_request_timeout_seconds,
        )
    if name == "openrouter":
        return OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        )
    raise LLMPolicyError(f"provider não suportado: {name}")


def execution_policy_for(agent: str) -> ExecutionPolicy:
    settings = _settings()
    mapping = {
        "conciliator": (settings.conciliator_provider, settings.conciliator_model),
        "organizer": (settings.organizer_provider, settings.organizer_model),
        "judge": (settings.judge_provider, settings.judge_model),
        "reviewer": (settings.reviewer_provider, settings.reviewer_model),
        "appeal": (settings.appeal_provider, settings.appeal_model),
        "embedding": (settings.embedding_provider, settings.embedding_model),
    }
    provider, model = mapping.get(
        agent,
        (settings.llm_default_provider, settings.openai_model),
    )
    fallback = None
    explicit = settings.llm_explicit_fallback
    if explicit:
        from app.llm.schemas import FallbackPolicy

        fallback = FallbackPolicy(
            provider=explicit["provider"],
            model=explicit["model"],
            reason=explicit.get("reason") or "configured_fallback",
        )
    return ExecutionPolicy(
        provider=provider,
        model=model,
        timeout_seconds=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_max_retries,
        fallback=fallback,
        agent=agent,
    )


def generate_structured(
    task: str,
    system_prompt: str,
    user_payload: Dict[str, Any],
    response_model: Type[BaseModel],
    execution_policy: Optional[ExecutionPolicy] = None,
) -> StructuredGenerationResult:
    policy = execution_policy or execution_policy_for(task)
    if not provider_allowed(policy.provider):
        raise LLMPolicyError("provider não permitido")
    if not model_allowed(policy.model):
        raise LLMPolicyError("modelo não permitido")

    try:
        provider = build_provider(policy.provider)
        result = provider.generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_model=response_model,
            execution_policy=policy,
        )
        return result
    except (LLMUnavailable, LLMCallError, LLMPolicyError):
        if policy.fallback is None:
            raise
    except Exception:
        if policy.fallback is None:
            raise
        # Fallback só ocorre se a política o declarou explicitamente.
        pass

    fallback = policy.fallback
    if fallback is None:
        raise LLMUnavailable("provider unavailable")
    if not provider_allowed(fallback.provider):
        raise LLMPolicyError("provider de fallback não permitido")
    if not model_allowed(fallback.model):
        raise LLMPolicyError("modelo de fallback não permitido")
    fallback_policy = ExecutionPolicy(
        provider=fallback.provider,
        model=fallback.model,
        timeout_seconds=policy.timeout_seconds,
        max_retries=policy.max_retries,
        fallback=None,
        agent=policy.agent,
    )
    provider = build_provider(fallback.provider)
    result = provider.generate_structured(
        task=task,
        system_prompt=system_prompt,
        user_payload=user_payload,
        response_model=response_model,
        execution_policy=fallback_policy,
    )
    result.fallback_used = True
    result.fallback_reason = fallback.reason
    result.requested_provider = policy.provider
    result.requested_model = policy.model
    return result


def generate_embedding(text: str, model: Optional[str] = None) -> list:
    policy = execution_policy_for("embedding")
    provider = build_provider(policy.provider)
    return provider.generate_embedding(text, model or policy.model)
