"""Procedência de cada etapa executada por IA.

Todo agente devolve, junto do resultado, um bloco `execution` que responde a
uma pergunta simples: com qual prompt e com qual modelo isso foi produzido?
Sem essa resposta, uma decisão não é reproduzível — e reprodutibilidade é o
que o procedimento promete.
"""

from __future__ import annotations

from typing import Dict, Optional

from app.core.config import get_settings
from app.core.llm import LLMResult
from app.core.prompt_registry import PromptVersion


def openai_execution(prompt: PromptVersion, result: LLMResult) -> Dict:
    settings = get_settings()
    execution = {
        "mode": "openai",
        # `model` é o que a API declarou ter respondido; `model_requested` é o
        # alias configurado, que pode apontar para outra versão amanhã.
        "model": result.model,
        "model_requested": settings.openai_model,
        "response_id": result.response_id,
        "prompt": prompt.as_reference(),
        "reason": None,
    }
    if result.usage:
        execution["usage"] = result.usage
    return execution


def fallback_execution(prompt: PromptVersion, reason: str) -> Dict:
    return {
        "mode": "safe_fallback",
        "model": None,
        "model_requested": get_settings().openai_model,
        "response_id": None,
        "prompt": prompt.as_reference(),
        "reason": reason,
    }


def with_drift(execution: Dict, drift: Optional[Dict]) -> Dict:
    """Anexa a divergência entre o prompt travado no manifesto e o que rodou.

    `None` mantém o bloco intacto: ausência da chave significa "sem
    divergência detectada".
    """
    if drift:
        execution = {**execution, "prompt_drift": drift}
    return execution
