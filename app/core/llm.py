import json
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


def openai_configured() -> bool:
    return get_settings().openai_enabled


def _client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_enabled:
        raise LLMUnavailable("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def call_openai_structured(
    system_prompt: str,
    user_payload: Dict[str, Any],
    response_model: Type[BaseModel],
    model: Optional[str] = None,
) -> Dict[str, Any]:
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
    if hasattr(parsed, "model_dump"):
        return parsed.model_dump()
    return parsed.dict()


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
