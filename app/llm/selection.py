"""Escolha de modelos por etapa: ranking de benchmark + agente seletor.

O ranking determinístico é a base reproduzível. O agente de IA, quando o
LLM está ligado, escolhe a partir da shortlist e justifica. Julgador,
revisor e recurso não podem compartilhar família.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.llm.catalog import CatalogModel, ModelCatalog, load_catalog
from app.llm.models import model_vendor, normalize_openrouter_model
from app.llm.stage_requirements import (
    STAGE_REQUIREMENTS,
    StageRequirement,
    requirement_list,
)

SHORTLIST_SIZE = 6


@dataclass
class RankedCandidate:
    model: CatalogModel
    score: float
    reason: str

    def as_public(self) -> Dict[str, Any]:
        return {
            **self.model.as_public(),
            "score": round(self.score, 4),
            "reason": self.reason,
        }


@dataclass
class StageAssignment:
    agent: str
    provider: str
    model: str
    reason: str
    benchmark: str
    score: Optional[float] = None
    source: str = "catalog_rank"
    pinned: bool = False

    def as_policy(self) -> Dict[str, Any]:
        payload = {
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "benchmark": self.benchmark,
            "source": self.source,
            "pinned": self.pinned,
        }
        if self.score is not None:
            payload["score"] = self.score
        return payload


@dataclass
class SelectionResult:
    assignments: Dict[str, StageAssignment] = field(default_factory=dict)
    shortlists: Dict[str, List[RankedCandidate]] = field(default_factory=dict)
    method: str = "catalog_rank"
    catalog_source: str = "snapshot"
    notes: str = ""
    selector_execution: Optional[Dict[str, Any]] = None

    def as_policy_overlay(self) -> Dict[str, Any]:
        return {agent: item.as_policy() for agent, item in self.assignments.items()}

    def as_record(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "catalog_source": self.catalog_source,
            "notes": self.notes,
            "assignments": {
                agent: item.as_policy() for agent, item in self.assignments.items()
            },
            "shortlists": {
                agent: [row.as_public() for row in rows[:SHORTLIST_SIZE]]
                for agent, rows in self.shortlists.items()
            },
            "selector_execution": self.selector_execution,
        }


def _norm(value: Optional[float], lo: float, hi: float) -> float:
    if value is None or hi <= lo:
        return 0.0
    clamped = min(hi, max(lo, value))
    return (clamped - lo) / (hi - lo)


def score_model(model: CatalogModel, need: StageRequirement, catalog: ModelCatalog) -> float:
    pool = catalog.embedding_models() if need.embedding else catalog.chat_models()
    intelligences = [item.intelligence or 0.0 for item in pool]
    prices = [item.prompt_price or 0.0 for item in pool if item.prompt_price]
    intel = _norm(model.intelligence, min(intelligences or [0.0]), max(intelligences or [1.0]))
    if prices:
        # Preço baixo pontua alto.
        price_norm = 1.0 - _norm(
            model.prompt_price if model.prompt_price is not None else max(prices),
            min(prices),
            max(prices),
        )
    else:
        price_norm = 0.5
    return need.weight_intelligence * intel + need.weight_cost * price_norm


def eligible(model: CatalogModel, need: StageRequirement) -> bool:
    if need.embedding:
        return model.embedding
    if model.embedding:
        return False
    if need.structured_output and not model.structured:
        return False
    if need.min_context and model.context_length and model.context_length < need.min_context:
        return False
    return True


def rank_stage(
    need: StageRequirement,
    catalog: ModelCatalog,
    excluded_vendors: Sequence[str] = (),
) -> List[RankedCandidate]:
    blocked = {vendor.lower() for vendor in excluded_vendors if vendor}
    ranked: List[RankedCandidate] = []
    for model in catalog.models:
        if not eligible(model, need):
            continue
        if model.vendor in blocked:
            continue
        score = score_model(model, need, catalog)
        ranked.append(
            RankedCandidate(
                model=model,
                score=score,
                reason=(
                    f"benchmark {need.primary_benchmark}="
                    f"{model.intelligence if model.intelligence is not None else 'n/d'}"
                    f", custo={model.prompt_price if model.prompt_price is not None else 'n/d'}"
                ),
            )
        )
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def _operator_pins() -> Dict[str, str]:
    import os

    mapping = {
        "conciliator": "CONCILIATOR_MODEL",
        "organizer": "ORGANIZER_MODEL",
        "judge": "JUDGE_MODEL",
        "reviewer": "REVIEWER_MODEL",
        "appeal": "APPEAL_MODEL",
        "embedding": "EMBEDDING_MODEL",
    }
    pins = {}
    for agent, env_name in mapping.items():
        raw = os.getenv(env_name)
        if raw and raw.strip():
            pins[agent] = normalize_openrouter_model(raw.strip())
    return pins


def _assignment_from_candidate(
    agent: str,
    candidate: RankedCandidate,
    need: StageRequirement,
    source: str,
    pinned: bool = False,
) -> StageAssignment:
    from app.core.config import get_settings

    settings = get_settings()
    return StageAssignment(
        agent=agent,
        provider=settings.llm_default_provider or "openrouter",
        model=candidate.model.id,
        reason=candidate.reason,
        benchmark=need.primary_benchmark,
        score=round(candidate.score, 4),
        source=source,
        pinned=pinned,
    )


def _assignment_from_pin(
    agent: str,
    model_id: str,
    catalog: ModelCatalog,
    need: StageRequirement,
) -> StageAssignment:
    from app.core.config import get_settings

    settings = get_settings()
    slug = normalize_openrouter_model(model_id)
    found = catalog.by_id(slug)
    score = score_model(found, need, catalog) if found else None
    return StageAssignment(
        agent=agent,
        provider=settings.llm_default_provider or "openrouter",
        model=slug,
        reason="modelo fixado pelo operador via variável de ambiente",
        benchmark=need.primary_benchmark,
        score=round(score, 4) if score is not None else None,
        source="operator_pin",
        pinned=True,
    )


def pick_from_rank(
    catalog: ModelCatalog,
    pins: Optional[Dict[str, str]] = None,
) -> SelectionResult:
    pins = pins if pins is not None else _operator_pins()
    shortlists: Dict[str, List[RankedCandidate]] = {}
    assignments: Dict[str, StageAssignment] = {}
    chosen_vendor: Dict[str, str] = {}

    for need in requirement_list():
        excluded = []
        for other in need.independent_from:
            vendor = chosen_vendor.get(other)
            if vendor:
                excluded.append(vendor)
        ranked = rank_stage(need, catalog, excluded_vendors=excluded)
        shortlists[need.agent] = ranked[:SHORTLIST_SIZE]
        pin = pins.get(need.agent)
        if pin:
            assignments[need.agent] = _assignment_from_pin(
                need.agent, pin, catalog, need
            )
            chosen_vendor[need.agent] = model_vendor(pin)
            continue
        if not ranked:
            continue
        pick = ranked[0]
        assignments[need.agent] = _assignment_from_candidate(
            need.agent, pick, need, source="catalog_rank"
        )
        chosen_vendor[need.agent] = pick.model.vendor

    return SelectionResult(
        assignments=assignments,
        shortlists=shortlists,
        method="catalog_rank",
        catalog_source=catalog.source,
        notes="ranking determinístico a partir dos índices de benchmark",
    )


def _best_other_family(
    shortlist: Sequence[RankedCandidate],
    forbidden_vendors: Sequence[str],
) -> Optional[RankedCandidate]:
    blocked = {vendor for vendor in forbidden_vendors if vendor and vendor != "unknown"}
    for candidate in shortlist:
        if candidate.model.vendor not in blocked:
            return candidate
    return None


def _replace_if_same_family(
    assignments: Dict[str, StageAssignment],
    shortlists: Dict[str, List[RankedCandidate]],
    agent: str,
    forbidden_vendors: Sequence[str],
    pins: Dict[str, str],
    note: str,
) -> None:
    current = assignments.get(agent)
    if current is None or current.pinned or agent in pins:
        return
    blocked = {vendor for vendor in forbidden_vendors if vendor and vendor != "unknown"}
    if model_vendor(current.model) not in blocked:
        return
    alternative = _best_other_family(shortlists.get(agent) or [], blocked)
    if alternative is None or alternative.model.id == current.model:
        return
    replacement = _assignment_from_candidate(
        agent, alternative, STAGE_REQUIREMENTS[agent], source="catalog_rank"
    )
    replacement.reason = note
    assignments[agent] = replacement


def validate_selection(
    proposed: Dict[str, Any],
    catalog: ModelCatalog,
    shortlists: Dict[str, List[RankedCandidate]],
    pins: Optional[Dict[str, str]] = None,
) -> SelectionResult:
    """Aceita escolhas do agente só se estiverem na shortlist e respeitarem independência.

    `proposed` mapeia agente → slug, ou agente → {"model", "reason"}.
    """
    pins = pins if pins is not None else _operator_pins()
    fallback = pick_from_rank(catalog, pins=pins)
    allowed = {
        agent: {item.model.id for item in rows}
        for agent, rows in fallback.shortlists.items()
    }
    assignments = dict(fallback.assignments)

    for agent, raw in proposed.items():
        if agent not in STAGE_REQUIREMENTS or agent in pins:
            continue
        if isinstance(raw, dict):
            model_id = raw.get("model") or ""
            reason = raw.get("reason") or ""
        else:
            model_id = str(raw or "")
            reason = ""
        slug = normalize_openrouter_model(model_id)
        if slug not in allowed.get(agent, set()):
            continue
        found = next(
            (item for item in fallback.shortlists.get(agent, []) if item.model.id == slug),
            None,
        )
        if found is None:
            continue
        chosen = _assignment_from_candidate(
            agent, found, STAGE_REQUIREMENTS[agent], source="selector_agent"
        )
        if reason:
            chosen.reason = reason
        assignments[agent] = chosen

    judge = assignments.get("judge")
    judge_vendor = model_vendor(judge.model) if judge else ""
    if judge_vendor:
        _replace_if_same_family(
            assignments,
            fallback.shortlists,
            "reviewer",
            (judge_vendor,),
            pins,
            "o seletor repetiu a família do julgador; aplicada outra família da shortlist",
        )
    reviewer = assignments.get("reviewer")
    forbidden = [
        vendor
        for vendor in (
            judge_vendor,
            model_vendor(reviewer.model) if reviewer else "",
        )
        if vendor
    ]
    if forbidden:
        _replace_if_same_family(
            assignments,
            fallback.shortlists,
            "appeal",
            forbidden,
            pins,
            "o seletor repetiu a família do julgador ou do revisor; aplicada outra família da shortlist",
        )

    fallback.assignments = assignments
    fallback.method = "selector_agent"
    fallback.notes = "agente seletor sobre a shortlist de benchmarks"
    return fallback


def select_stage_models(catalog: Optional[ModelCatalog] = None) -> SelectionResult:
    """Ponto único usado na trava do manifesto."""
    from app.core.config import get_settings

    settings = get_settings()
    loaded = catalog or load_catalog()
    pins = _operator_pins()
    ranked = pick_from_rank(loaded, pins=pins)

    if not settings.model_selector_enabled:
        ranked.method = "disabled"
        ranked.notes = "seletor desligado; política de ambiente / ranking"
        return ranked
    if not settings.llm_enabled:
        return ranked

    from app.agents.selector import select_models as selector_agent

    try:
        return selector_agent(loaded, ranked, pins=pins)
    except Exception:
        ranked.notes = "agente seletor indisponível; aplicado o ranking de benchmark"
        return ranked
