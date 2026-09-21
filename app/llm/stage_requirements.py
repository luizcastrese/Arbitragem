"""Necessidades de cada etapa do procedimento.

O seletor não escolhe "o melhor modelo do mundo": escolhe o modelo cujo
perfil de benchmark combina com o trabalho da etapa. Julgador e revisor
não podem cair na mesma família.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


STAGES: Tuple[str, ...] = (
    "conciliator",
    "organizer",
    "judge",
    "reviewer",
    "appeal",
    "embedding",
)


@dataclass(frozen=True)
class StageRequirement:
    agent: str
    summary: str
    primary_benchmark: str
    weight_intelligence: float
    weight_cost: float
    min_context: int
    structured_output: bool = True
    embedding: bool = False
    independent_from: Tuple[str, ...] = ()
    prefer_speed: bool = False


STAGE_REQUIREMENTS: dict[str, StageRequirement] = {
    "conciliator": StageRequirement(
        agent="conciliator",
        summary=(
            "Triagem rápida de convergência: JSON estruturado, baixo custo "
            "e latência, inteligência suficiente para não inventar concessões."
        ),
        primary_benchmark="intelligence",
        weight_intelligence=0.45,
        weight_cost=0.55,
        min_context=32_000,
        prefer_speed=True,
    ),
    "organizer": StageRequirement(
        agent="organizer",
        summary=(
            "Organização do registro admitido: extração fiel, citações por "
            "ID e recusa a inventar fatos. Prioriza JSON estável e custo."
        ),
        primary_benchmark="intelligence",
        weight_intelligence=0.55,
        weight_cost=0.45,
        min_context=64_000,
        prefer_speed=True,
    ),
    "judge": StageRequirement(
        agent="judge",
        summary=(
            "Decisão de mérito lastreada em evidência: máxima inteligência, "
            "contexto longo e saída estruturada verificável."
        ),
        primary_benchmark="intelligence",
        weight_intelligence=0.9,
        weight_cost=0.1,
        min_context=100_000,
    ),
    "reviewer": StageRequirement(
        agent="reviewer",
        summary=(
            "Auditoria independente da decisão: inteligência alta e família "
            "distinta da do julgador, para não ser o mesmo laboratório "
            "avaliando a si mesmo."
        ),
        primary_benchmark="intelligence",
        weight_intelligence=0.85,
        weight_cost=0.15,
        min_context=100_000,
        independent_from=("judge",),
    ),
    "appeal": StageRequirement(
        agent="appeal",
        summary=(
            "Recurso automático: reexame com inteligência alta e família "
            "distinta da do julgador e da do revisor."
        ),
        primary_benchmark="intelligence",
        weight_intelligence=0.85,
        weight_cost=0.15,
        min_context=100_000,
        independent_from=("judge", "reviewer"),
    ),
    "embedding": StageRequirement(
        agent="embedding",
        summary="Indexação vetorial do material admitido; modelo de embedding.",
        primary_benchmark="retrieval",
        weight_intelligence=0.0,
        weight_cost=1.0,
        min_context=0,
        structured_output=False,
        embedding=True,
    ),
}


def requirement_list() -> List[StageRequirement]:
    return [STAGE_REQUIREMENTS[name] for name in STAGES]
