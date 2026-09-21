"""Catálogo OpenRouter: modelos + índices de benchmark.

Sem chave ou sem rede, usa um snapshot local. Com `OPENROUTER_API_KEY`,
consulta `/models` e `/benchmarks` e sobrepõe os índices oficiais.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from app.llm.models import model_vendor, normalize_openrouter_model

SNAPSHOT_MODELS: List[Dict[str, Any]] = [
    {
        "id": "anthropic/claude-sonnet-4",
        "intelligence": 72.0,
        "coding": 61.0,
        "prompt_price": 3.0,
        "context_length": 200_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "openai/gpt-4.1",
        "intelligence": 68.0,
        "coding": 60.0,
        "prompt_price": 2.0,
        "context_length": 1_000_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "google/gemini-2.5-pro",
        "intelligence": 70.0,
        "coding": 63.0,
        "prompt_price": 1.25,
        "context_length": 1_000_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "google/gemini-2.5-flash",
        "intelligence": 58.0,
        "coding": 52.0,
        "prompt_price": 0.15,
        "context_length": 1_000_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "openai/gpt-4.1-mini",
        "intelligence": 55.0,
        "coding": 50.0,
        "prompt_price": 0.4,
        "context_length": 1_000_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "deepseek/deepseek-chat-v3.1",
        "intelligence": 64.0,
        "coding": 66.0,
        "prompt_price": 0.27,
        "context_length": 128_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "qwen/qwen3-235b-a22b",
        "intelligence": 62.0,
        "coding": 64.0,
        "prompt_price": 0.22,
        "context_length": 128_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "meta-llama/llama-3.3-70b-instruct",
        "intelligence": 50.0,
        "coding": 48.0,
        "prompt_price": 0.12,
        "context_length": 128_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "mistralai/mistral-large-2411",
        "intelligence": 56.0,
        "coding": 54.0,
        "prompt_price": 2.0,
        "context_length": 128_000,
        "embedding": False,
        "structured": True,
    },
    {
        "id": "openai/text-embedding-3-small",
        "intelligence": 0.0,
        "coding": 0.0,
        "prompt_price": 0.02,
        "context_length": 8_191,
        "embedding": True,
        "structured": False,
    },
    {
        "id": "openai/text-embedding-3-large",
        "intelligence": 0.0,
        "coding": 0.0,
        "prompt_price": 0.13,
        "context_length": 8_191,
        "embedding": True,
        "structured": False,
    },
]


@dataclass(frozen=True)
class CatalogModel:
    id: str
    vendor: str
    intelligence: Optional[float] = None
    coding: Optional[float] = None
    prompt_price: Optional[float] = None
    context_length: int = 0
    embedding: bool = False
    structured: bool = True
    source: str = "snapshot"

    def as_public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "vendor": self.vendor,
            "intelligence": self.intelligence,
            "coding": self.coding,
            "prompt_price": self.prompt_price,
            "context_length": self.context_length,
            "embedding": self.embedding,
            "structured": self.structured,
            "source": self.source,
        }


@dataclass
class ModelCatalog:
    models: List[CatalogModel] = field(default_factory=list)
    source: str = "snapshot"
    fetched: bool = False

    def by_id(self, model_id: str) -> Optional[CatalogModel]:
        slug = normalize_openrouter_model(model_id)
        for item in self.models:
            if item.id == slug or item.id == model_id:
                return item
        return None

    def chat_models(self) -> List[CatalogModel]:
        return [item for item in self.models if not item.embedding]

    def embedding_models(self) -> List[CatalogModel]:
        return [item for item in self.models if item.embedding]


def snapshot_catalog() -> ModelCatalog:
    models = []
    for raw in SNAPSHOT_MODELS:
        slug = normalize_openrouter_model(raw["id"])
        models.append(
            CatalogModel(
                id=slug,
                vendor=model_vendor(slug),
                intelligence=raw.get("intelligence"),
                coding=raw.get("coding"),
                prompt_price=raw.get("prompt_price"),
                context_length=int(raw.get("context_length") or 0),
                embedding=bool(raw.get("embedding")),
                structured=bool(raw.get("structured", True)),
                source="snapshot",
            )
        )
    return ModelCatalog(models=models, source="snapshot", fetched=False)


def _parse_price(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    # OpenRouter às vezes devolve USD por token; índices do snapshot estão
    # em USD / milhão. Normaliza os dois para USD / milhão.
    if 0 < amount < 0.01:
        return amount * 1_000_000
    return amount


def _from_openrouter_model(raw: Dict[str, Any]) -> Optional[CatalogModel]:
    model_id = raw.get("id") or raw.get("canonical_slug")
    if not model_id:
        return None
    slug = normalize_openrouter_model(str(model_id))
    architecture = raw.get("architecture") or {}
    outputs = architecture.get("output_modalities") or architecture.get("modality") or []
    if isinstance(outputs, str):
        outputs = [outputs]
    embedding = "embeddings" in outputs or "embedding" in slug
    params = raw.get("supported_parameters") or []
    structured = (not embedding) and (
        not params
        or "response_format" in params
        or "structured_outputs" in params
        or "json" in params
    )
    benchmarks = raw.get("benchmarks") or {}
    aa = benchmarks.get("artificial_analysis") or benchmarks.get("artificialAnalysis") or {}
    pricing = raw.get("pricing") or {}
    return CatalogModel(
        id=slug,
        vendor=model_vendor(slug),
        intelligence=_as_float(aa.get("intelligence_index")),
        coding=_as_float(aa.get("coding_index")),
        prompt_price=_parse_price(pricing.get("prompt")),
        context_length=int(raw.get("context_length") or 0),
        embedding=embedding,
        structured=structured,
        source="openrouter",
    )


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_benchmark_row(catalog: ModelCatalog, row: Dict[str, Any]) -> None:
    slug = row.get("model_permaslug") or row.get("id") or row.get("model")
    if not slug:
        return
    slug = normalize_openrouter_model(str(slug))
    intelligence = _as_float(row.get("intelligence_index") or row.get("score"))
    coding = _as_float(row.get("coding_index"))
    existing = catalog.by_id(slug)
    if existing is None:
        catalog.models.append(
            CatalogModel(
                id=slug,
                vendor=model_vendor(slug),
                intelligence=intelligence,
                coding=coding,
                source="openrouter",
            )
        )
        return
    catalog.models = [
        replace(
            item,
            intelligence=intelligence if intelligence is not None else item.intelligence,
            coding=coding if coding is not None else item.coding,
            source="openrouter",
        )
        if item.id == existing.id
        else item
        for item in catalog.models
    ]


def _http_get_json(url: str, api_key: str, timeout: float) -> Dict[str, Any]:
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = httpx.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"data": payload}


def fetch_live_catalog(timeout: float = 8.0) -> ModelCatalog:
    from app.core.config import get_settings

    settings = get_settings()
    base = settings.openrouter_base_url.rstrip("/")
    catalog = snapshot_catalog()
    try:
        models_payload = _http_get_json(
            f"{base}/models?sort=intelligence-high-to-low&limit=80",
            settings.openrouter_api_key,
            timeout,
        )
    except Exception:
        return catalog

    live: List[CatalogModel] = []
    for raw in models_payload.get("data") or []:
        if not isinstance(raw, dict):
            continue
        parsed = _from_openrouter_model(raw)
        if parsed is not None:
            live.append(parsed)
    if live:
        by_id = {item.id: item for item in catalog.models}
        by_id.update({item.id: item for item in live})
        catalog = ModelCatalog(
            models=list(by_id.values()),
            source="openrouter",
            fetched=True,
        )

    if not settings.openrouter_api_key:
        return catalog
    try:
        bench_payload = _http_get_json(
            f"{base}/benchmarks?source=artificial-analysis&task_type=intelligence&max_results=50",
            settings.openrouter_api_key,
            timeout,
        )
        for row in bench_payload.get("data") or bench_payload.get("items") or []:
            if isinstance(row, dict):
                _merge_benchmark_row(catalog, row)
    except Exception:
        return catalog
    catalog.fetched = True
    catalog.source = "openrouter"
    return catalog


def load_catalog() -> ModelCatalog:
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.openrouter_enabled:
        return snapshot_catalog()
    return fetch_live_catalog(timeout=min(8.0, settings.llm_request_timeout_seconds))
