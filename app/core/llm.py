import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from openai import OpenAI
from pydantic import BaseModel

from app.core.config import get_settings


class LLMUnavailable(RuntimeError):
    pass


class LLMCallError(RuntimeError):
    pass


class LLMQuotaExceeded(LLMCallError):
    pass


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


def openai_configured() -> bool:
    return get_settings().openai_enabled


def _client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_enabled:
        raise LLMUnavailable("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def _usage_to_dict(usage: Any) -> Dict[str, int]:
    if usage is None:
        return {}
    return {
        key: value
        for key, value in (
            ("input_tokens", getattr(usage, "input_tokens", None)),
            ("output_tokens", getattr(usage, "output_tokens", None)),
            ("total_tokens", getattr(usage, "total_tokens", None)),
        )
        if isinstance(value, int)
    }


def call_openai_structured(
    system_prompt: str,
    user_payload: Dict[str, Any],
    response_model: Type[BaseModel],
    model: Optional[str] = None,
) -> LLMResult:
    settings = get_settings()
    try:
        response = _client().responses.parse(
            model=model or settings.openai_model,
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
        if getattr(exc, "code", None) == "insufficient_quota":
            raise LLMQuotaExceeded("OpenAI project has no available quota") from exc
        raise LLMCallError(f"OpenAI request failed: {type(exc).__name__}") from exc

    if response.output_parsed is None:
        raise LLMCallError("OpenAI returned no structured output")

    parsed = response.output_parsed
    data = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()
    return LLMResult(
        data=data,
        model=getattr(response, "model", None) or model or settings.openai_model,
        response_id=getattr(response, "id", None),
        usage=_usage_to_dict(getattr(response, "usage", None)),
    )


def generate_embedding(text: str, model: Optional[str] = None) -> List[float]:
    settings = get_settings()
    try:
        response = _client().embeddings.create(
            model=model or settings.embedding_model,
            input=text,
            encoding_format="float",
        )
    except LLMUnavailable:
        raise
    except Exception as exc:
        if getattr(exc, "code", None) == "insufficient_quota":
            raise LLMQuotaExceeded("OpenAI project has no available quota") from exc
        raise LLMCallError(f"Embedding request failed: {type(exc).__name__}") from exc
    return response.data[0].embedding
