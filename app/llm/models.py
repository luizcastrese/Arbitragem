"""Catálogo OpenRouter: um provedor, várias famílias de modelo.

A plataforma não chama um único laboratório direto. Toda geração estruturada
e todo embedding de produção passam pela API OpenRouter, com slugs
`fornecedor/modelo`. Julgador, revisor e recurso usam famílias distintas
para que a auditoria não seja o mesmo sistema avaliando a si mesmo.
"""

from __future__ import annotations

from typing import Dict

# Slugs estáveis da OpenRouter. Cada etapa decisória aponta para um
# laboratório diferente; conciliação e organização podem ser mais baratas.
DEFAULT_OPENROUTER_MODELS: Dict[str, str] = {
    "default": "openai/gpt-4.1-mini",
    "conciliator": "google/gemini-2.5-flash",
    "organizer": "openai/gpt-4.1-mini",
    "judge": "anthropic/claude-sonnet-4",
    "reviewer": "openai/gpt-4.1",
    "appeal": "google/gemini-2.5-pro",
    "embedding": "openai/text-embedding-3-small",
    "selector": "google/gemini-2.5-flash",
    "steward": "google/gemini-2.5-flash",
}

_OPENAI_PREFIXES = (
    "gpt-",
    "o1",
    "o3",
    "o4",
    "chatgpt",
    "text-embedding",
    "text-davinci",
)


def model_vendor(model: str) -> str:
    """Fornecedor do slug OpenRouter (`anthropic/claude-sonnet-4` → `anthropic`)."""
    slug = (model or "").strip().lower()
    if not slug:
        return "unknown"
    if "/" in slug:
        return slug.split("/", 1)[0]
    if slug.startswith(_OPENAI_PREFIXES):
        return "openai"
    if slug.startswith("claude"):
        return "anthropic"
    if slug.startswith("gemini"):
        return "google"
    if slug.startswith("llama"):
        return "meta-llama"
    if slug.startswith("mistral") or slug.startswith("mixtral"):
        return "mistralai"
    if slug.startswith("qwen"):
        return "qwen"
    if slug.startswith("deepseek"):
        return "deepseek"
    return "unknown"


def normalize_openrouter_model(model: str) -> str:
    """Aceita ids nus (`gpt-4.1-mini`) e devolve o slug OpenRouter."""
    slug = (model or "").strip()
    if not slug or "/" in slug:
        return slug
    vendor = model_vendor(slug)
    if vendor == "unknown":
        return slug
    return f"{vendor}/{slug}"


def families_are_independent(left_model: str, right_model: str) -> bool:
    """Verdadeiro quando os dois slugs apontam para laboratórios distintos."""
    left = model_vendor(left_model)
    right = model_vendor(right_model)
    if left == "unknown" or right == "unknown":
        return (left_model or "").strip() != (right_model or "").strip()
    return left != right
