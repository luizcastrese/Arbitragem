"""Agente que escolhe os modelos de cada etapa a partir de benchmarks.

Não é um agente do procedimento (não decide o caso). Roda na trava do
manifesto, recebe a shortlist ranqueada e devolve uma alocação justificada.
Se a chamada falhar ou violar independência, o ranking determinístico prevalece.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.agents.execution import fallback_execution, openai_execution
from app.core.llm import call_openai_structured
from app.core.prompt_registry import register_prompt
from app.llm.catalog import ModelCatalog
from app.llm.selection import (
    SHORTLIST_SIZE,
    SelectionResult,
    validate_selection,
)
from app.llm.stage_requirements import requirement_list


class StageChoice(BaseModel):
    agent: str
    model: str
    reason: str = Field(min_length=1, max_length=500)


class SelectorOutput(BaseModel):
    choices: List[StageChoice]
    notes: str = ""


SYSTEM_PROMPT = """
Você é o agente seletor de modelos de um procedimento autônomo de resolução
de disputas. Os modelos vêm exclusivamente da OpenRouter.

Você recebe, para cada etapa, a necessidade da etapa e uma shortlist já
ranqueada por benchmarks (Artificial Analysis intelligence/coding e custo).
Escolha UM modelo da shortlist de cada etapa.

Regras obrigatórias:
- Só escolha ids que aparecem na shortlist daquela etapa.
- Julgador, revisor e recurso devem ser de famílias (fornecedores) distintas:
  anthropic ≠ openai ≠ google ≠ deepseek etc.
- Conciliador e organizador podem ser mais baratos; julgador prioriza
  inteligência; revisor precisa ser independente do julgador.
- Embedding só aceita modelo de embedding.
- Não invente slugs, pontuações ou laboratórios.
- Justifique em uma frase, citando o benchmark que pesou.
- Responda em português do Brasil.
"""

PROMPT = register_prompt("selector", "1.0.0", SYSTEM_PROMPT)


def _payload(
    catalog: ModelCatalog,
    ranked: SelectionResult,
) -> Dict[str, Any]:
    stages = []
    for need in requirement_list():
        shortlist = ranked.shortlists.get(need.agent) or []
        stages.append(
            {
                "agent": need.agent,
                "need": need.summary,
                "primary_benchmark": need.primary_benchmark,
                "independent_from": list(need.independent_from),
                "shortlist": [item.as_public() for item in shortlist[:SHORTLIST_SIZE]],
            }
        )
    return {
        "catalog_source": catalog.source,
        "stages": stages,
    }


def select_models(
    catalog: ModelCatalog,
    ranked: SelectionResult,
    pins: Optional[Dict[str, str]] = None,
) -> SelectionResult:
    try:
        result = call_openai_structured(
            system_prompt=PROMPT.text,
            user_payload=_payload(catalog, ranked),
            response_model=SelectorOutput,
            agent="selector",
        )
    except Exception as exc:
        ranked.notes = (
            f"agente seletor indisponível ({type(exc).__name__}); "
            "aplicado o ranking de benchmark"
        )
        ranked.selector_execution = fallback_execution(PROMPT, type(exc).__name__)
        return ranked

    choices = result.data.get("choices") or []
    proposed = {}
    for item in choices:
        if isinstance(item, dict) and item.get("agent") and item.get("model"):
            proposed[item["agent"]] = {
                "model": item["model"],
                "reason": item.get("reason") or "",
            }

    selection = validate_selection(proposed, catalog, ranked.shortlists, pins=pins)
    selection.selector_execution = openai_execution(PROMPT, result)
    selection.notes = result.data.get("notes") or selection.notes
    selection.catalog_source = catalog.source
    return selection
