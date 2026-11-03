"""Une a memória de cálculo à proposta de acordo e à decisão.

A IA escolhe palavras e, no máximo, um percentual de concessão; o valor, as
parcelas e os percentuais vêm de ``app.domain.calculation``. Tudo que a IA
escrever com número que a memória não contém é removido e fica registrado em
``number_guard``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.domain.calculation import format_brl, guard_terms, proposal_term, scenario

# Campos de texto da rodada em que a IA poderia citar números.
_TEXT_LIST_FIELDS = (
    "common_interests",
    "negotiable_issues",
    "non_negotiable_issues",
    "possible_terms",
    "reasoning",
)

REMOVED_SUMMARY = (
    "Resumo omitido: citava valores que não constam da memória de cálculo."
)


def calculation_status(state: Optional[Dict[str, Any]]) -> str:
    """unavailable | abstained | needs_inputs | ready."""
    if not state:
        return "unavailable"
    return state.get("status") or "unavailable"


def memory_for_model(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """O que a IA enxerga: situação e memória pronta, nunca entradas cruas."""
    status = calculation_status(state)
    context: Dict[str, Any] = {"status": status}
    if status == "abstained":
        context["abstention_reason"] = (state.get("assessment") or {}).get("abstention_reason")
    if status == "ready":
        calc = state["calculation"]
        context["sha256"] = calc["sha256"]
        context["lines"] = [
            {"label": line["label"], "formula": line["formula"], "value": line["display"]}
            for line in calc["lines"]
        ]
        context["questionable_charges"] = [
            {"name": fee["name"], "reason": fee.get("reason")}
            for fee in calc["inputs"]["fees"]
            if fee["questionable"]
        ]
    return context


def attach_calculation_to_round(
    conciliation: Dict[str, Any],
    state: Optional[Dict[str, Any]],
    consumer_name: str,
    round_number: int,
) -> Dict[str, Any]:
    """Reescreve a rodada para que os números venham só do módulo de cálculo."""
    result = dict(conciliation)
    status = calculation_status(state)
    chosen_percent = result.pop("proposal_adjustment_percent", None)
    calc = state["calculation"] if status == "ready" else None

    # A primeira rodada propõe o valor integral apurado; a concessão é negociada
    # nas seguintes e só dentro do piso do módulo.
    percent = scenario(calc, chosen_percent if round_number > 1 else None) if calc else None
    allowed = [percent["percent"]] if percent else []

    removed: List[Dict[str, str]] = []
    for field in _TEXT_LIST_FIELDS:
        items = result.get(field)
        if isinstance(items, list):
            kept, violations = guard_terms(items, calc, allowed)
            result[field] = kept
            removed.extend(violations)
    summary = result.get("neutral_summary")
    if isinstance(summary, str):
        kept, violations = guard_terms([summary], calc, allowed)
        if violations:
            result["neutral_summary"] = REMOVED_SUMMARY
            removed.extend(violations)

    if calc and percent:
        terms = [proposal_term(calc, percent, consumer_name), *result.get("possible_terms", [])]
        result["possible_terms"] = terms
        result["calculation"] = {
            "status": "ready",
            "sha256": calc["sha256"],
            "scenario": percent,
            "result": calc["result"],
            "lines": calc["lines"],
            "average_rate_source": calc["inputs"]["average_rate_source"],
            "number_guard": {"removed": removed},
        }
    else:
        result["calculation"] = {
            "status": status,
            "number_guard": {"removed": removed},
        }
        if status == "abstained":
            result["calculation"]["abstention_reason"] = (
                (state.get("assessment") or {}).get("abstention_reason")
            )
    return result


def attach_calculation_to_decision(
    decision: Dict[str, Any], state: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Anexa a memória à decisão e confere o valor do remédio contra ela."""
    if calculation_status(state) != "ready":
        return decision
    calc = state["calculation"]
    total = calc["result"]["total_proposed_minor"]
    decided = decision.get("remedy_calculation") or {}
    value = decided.get("result_minor_units")
    matches = value is None or value == total
    decision["calculation"] = {
        "status": "ready",
        "sha256": calc["sha256"],
        "result": calc["result"],
        "lines": calc["lines"],
        "average_rate_source": calc["inputs"]["average_rate_source"],
        "remedy_matches_calculation": matches,
    }
    if not matches:
        decision.setdefault("limitations", [])
        decision["limitations"].append(
            f"O valor da decisão ({format_brl(value)}) difere da memória de cálculo "
            f"({format_brl(total)}); prevalece a memória, que é determinística."
        )
    return decision
