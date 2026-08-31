"""Erros normalizados da camada LLM. Nunca incluem chaves nem conteúdo."""

from __future__ import annotations


class LLMError(RuntimeError):
    """Erro de provedor, sem payload sensível."""


class LLMUnavailable(LLMError):
    """Provedor não configurado ou chave ausente."""


class LLMCallError(LLMError):
    """Falha permanente da chamada (schema, 4xx, recusa)."""


class LLMQuotaExceeded(LLMCallError):
    pass


class LLMTimeout(LLMError):
    """Timeout explícito."""


class LLMTransientError(LLMError):
    """Erro transitório que admite retry limitado."""


class LLMSchemaError(LLMCallError):
    """JSON inválido ou incompatível com o response_model."""


class LLMPolicyError(LLMCallError):
    """Provider ou modelo fora da allowlist; fallback silencioso recusado."""
