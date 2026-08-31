"""Teste automático de estabilidade entre execuções do julgador."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from app.domain.models import StabilityResult


def _finding_key(finding: Mapping[str, Any]) -> str:
    return str(finding.get("finding_id") or finding.get("proposition") or "")


def _finding_signature(finding: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "proposition": finding.get("proposition"),
        "status": finding.get("status"),
        "evidence_count": len(finding.get("evidence") or []),
    }


def _remedy_signature(decision: Mapping[str, Any]) -> Dict[str, Any]:
    calc = decision.get("remedy_calculation") or {}
    return {
        "result_minor_units": calc.get("result_minor_units"),
        "currency": calc.get("currency"),
        "partial_claimant_bps": decision.get("partial_claimant_bps"),
    }


def _rule_ids(decision: Mapping[str, Any]) -> List[str]:
    return sorted(
        str(item.get("rule_id"))
        for item in (decision.get("rule_applications") or [])
        if isinstance(item, Mapping) and item.get("rule_id")
    )


def compare_decisions(
    runs: Sequence[Mapping[str, Any]],
    *,
    threshold: float = 1.0,
    execution_ids: Sequence[str] | None = None,
) -> StabilityResult:
    if not runs:
        return StabilityResult(
            stable=False,
            compared_runs=0,
            outcome_agreement=False,
            material_findings_agreement=False,
            remedy_agreement=False,
            material_disagreements=["no_runs"],
            execution_ids=list(execution_ids or []),
            threshold=threshold,
        )

    primary = runs[0]
    outcome_agreement = all(item.get("outcome") == primary.get("outcome") for item in runs)
    remedy_agreement = all(_remedy_signature(item) == _remedy_signature(primary) for item in runs)
    rule_agreement = all(_rule_ids(item) == _rule_ids(primary) for item in runs)

    disagreements: List[str] = []
    if not outcome_agreement:
        disagreements.append("outcome")
    if not remedy_agreement:
        disagreements.append("remedy")
    if not rule_agreement:
        disagreements.append("rule_applications")

    primary_findings = {
        _finding_key(item): _finding_signature(item)
        for item in (primary.get("material_findings") or [])
        if isinstance(item, Mapping)
    }
    findings_agreement = True
    for run in runs[1:]:
        other = {
            _finding_key(item): _finding_signature(item)
            for item in (run.get("material_findings") or [])
            if isinstance(item, Mapping)
        }
        if other != primary_findings:
            findings_agreement = False
            disagreements.append("material_findings")
            break

    compared = len(runs)
    agreeing_dimensions = sum(
        [outcome_agreement, findings_agreement, remedy_agreement, rule_agreement]
    )
    score = agreeing_dimensions / 4.0
    stable = score + 1e-9 >= threshold and outcome_agreement

    return StabilityResult(
        stable=stable,
        compared_runs=compared,
        outcome_agreement=outcome_agreement,
        material_findings_agreement=findings_agreement,
        remedy_agreement=remedy_agreement,
        material_disagreements=disagreements,
        execution_ids=list(execution_ids or []),
        threshold=threshold,
    )


def neutralize_party_order(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Reordena listas de partes de forma estável, sem alterar o teor da prova.

    Não troca nomes nem documentos: apenas ordena chaves conhecidas para a
    segunda execução não depender da ordem de apresentação.
    """
    data = dict(payload)
    documents = list(data.get("documents") or [])
    data["documents"] = sorted(
        documents,
        key=lambda item: (
            str((item or {}).get("submitted_by") or ""),
            str((item or {}).get("id") or ""),
        ),
    )
    return data
