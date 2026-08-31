"""Interface de provedor e utilitários compartilhados."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Type

from pydantic import BaseModel, ValidationError

from app.llm.errors import LLMSchemaError, LLMTransientError
from app.llm.schemas import ExecutionPolicy, LLMProvider, StructuredGenerationResult

logger = logging.getLogger("valinor.llm")

TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504}


def parse_structured_json(
    raw: str,
    response_model: Type[BaseModel],
) -> BaseModel:
    """Valida JSON localmente. Recusa extração por regex e coerções perigosas."""
    text = (raw or "").strip()
    if not text:
        raise LLMSchemaError("resposta vazia")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMSchemaError("resposta não é JSON") from exc
    if not isinstance(payload, dict):
        raise LLMSchemaError("resposta JSON não é um objeto")
    try:
        return response_model.model_validate(payload)
    except ValidationError as exc:
        raise LLMSchemaError("schema inválido") from exc


def log_call(
    *,
    provider: str,
    model: str,
    task: str,
    attempts: int,
    latency_ms: float,
    error: str | None = None,
) -> None:
    logger.info(
        "llm_call provider=%s model=%s task=%s attempts=%s latency_ms=%.1f error=%s",
        provider,
        model,
        task,
        attempts,
        latency_ms,
        error or "-",
    )


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, LLMTransientError):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in TRANSIENT_STATUS:
        return True
    code = getattr(exc, "code", None)
    if code in {"rate_limit_exceeded", "timeout", "overloaded_error"}:
        return True
    name = type(exc).__name__.lower()
    return "timeout" in name or "temporarily" in name or "unavailable" in name


def bounded_backoff(attempt: int) -> float:
    return min(8.0, 0.4 * (2 ** attempt))


__all__ = [
    "LLMProvider",
    "ExecutionPolicy",
    "StructuredGenerationResult",
    "parse_structured_json",
    "log_call",
    "is_transient",
    "bounded_backoff",
]
