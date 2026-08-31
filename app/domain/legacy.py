"""Normalização de registros legados sem alterar o que está persistido.

Funções puras: recebem um dict (decisão, revisão, contestação) e devolvem uma
visão canônica para leitura. O registro original não é mutado.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.domain.enums import (
    ABSTENTION_REASONS,
    AUTOMATIC_REVIEW_OUTCOMES,
    DECISION_OUTCOMES,
    PROCEDURE_CONCLUSIONS,
)


def _copy(value: Mapping[str, Any] | None) -> Dict[str, Any]:
    return dict(value or {})


def _as_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def classify_legacy_human_review(
    payload: Mapping[str, Any],
    *,
    default_reason: str = "insufficient_evidence",
) -> List[str]:
    """Traduz `requires_human_review` antigo para razões de abstenção.

    Não inventa `system_failure`: revisão humana no MVP significava que o
    mérito não era seguro, não que a plataforma tivesse falhado.
    """
    reasons = [
        item
        for item in _as_str_list(payload.get("abstention_reasons"))
        if item in ABSTENTION_REASONS
    ]
    if reasons:
        return reasons
    if payload.get("requires_human_review") or payload.get("human_review_required"):
        outcome = payload.get("outcome")
        execution_mode = (payload.get("execution") or {}).get("mode")
        if execution_mode == "safe_fallback":
            return ["provider_unavailable"]
        if outcome == "inconclusive":
            return [default_reason]
        return [default_reason]
    return []


def infer_procedure_conclusion(decision: Mapping[str, Any]) -> str:
    """Deriva a conclusão autônoma de um registro, novo ou legado."""
    declared = decision.get("procedure_conclusion")
    if declared in PROCEDURE_CONCLUSIONS:
        return str(declared)

    outcome = decision.get("outcome")
    execution_mode = (decision.get("execution") or {}).get("mode")
    reasons = classify_legacy_human_review(decision)

    if execution_mode == "safe_fallback" or "provider_unavailable" in reasons:
        return "system_failure"
    if "procedure_integrity_failure" in reasons or "prompt_injection_detected" in reasons:
        return "invalidated"
    if "out_of_scope" in reasons or "framework_not_applicable" in reasons:
        return "inadmissible"
    if outcome in {"claimant", "respondent", "partial"} and not reasons:
        return "decided"
    return "inconclusive"


def normalize_legacy_decision(decision: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Visão canônica de uma decisão persistida.

    Preserva campos originais (incluindo `requires_human_review` se existir)
    e acrescenta campos autônomos derivados. Não grava de volta.
    """
    data = _copy(decision)
    outcome = data.get("outcome")
    if outcome not in DECISION_OUTCOMES:
        data["outcome"] = "inconclusive"
    data.setdefault("framework_id", _framework_id_from_legacy(data))
    data.setdefault("framework_version", data.get("framework_version") or "1.0")
    data.setdefault("material_findings", data.get("material_findings") or [])
    data.setdefault("rule_applications", data.get("rule_applications") or [])
    data.setdefault("limitations", data.get("limitations") or [])
    data.setdefault("verification_summary", data.get("verification_summary") or {})
    if "evidence_cited" not in data:
        data["evidence_cited"] = _derived_evidence_cited(data)
    reasons = classify_legacy_human_review(data)
    data["abstention_reasons"] = reasons
    data["procedure_conclusion"] = infer_procedure_conclusion(data)
    return data


def normalize_legacy_review(review: Mapping[str, Any] | None) -> Dict[str, Any]:
    data = _copy(review)
    outcome = data.get("outcome")
    if outcome not in AUTOMATIC_REVIEW_OUTCOMES:
        if data.get("approved") is True:
            outcome = "approved"
        elif data.get("approved") is False:
            outcome = "rejected"
        else:
            outcome = "inconclusive"
        data["outcome"] = outcome
    data.setdefault("approved", data.get("outcome") == "approved")
    data.setdefault("issues", data.get("issues") or [])
    data.setdefault("challenged_findings", data.get("challenged_findings") or [])
    data.setdefault("ignored_evidence", data.get("ignored_evidence") or [])
    data.setdefault("unsupported_findings", data.get("unsupported_findings") or [])
    data.setdefault("calculation_issues", data.get("calculation_issues") or [])
    data.setdefault("framework_issues", data.get("framework_issues") or [])
    data.setdefault("recommended_conclusion", data.get("recommended_conclusion"))
    data.setdefault("confidence", data.get("confidence", data.get("confidence_assessment", 0.0)))
    reasons = classify_legacy_human_review(data)
    data["abstention_reasons"] = reasons
    return data


def strip_private_reasoning(decision: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Remove chain-of-thought privado antes de enviar ao revisor ou ao recurso.

    Fundamentos públicos (`material_findings`, `decision`, `rule_applications`)
    permanecem. `reasoning` livre do julgador não é encaminhado.
    """
    data = _copy(decision)
    data.pop("reasoning", None)
    data.pop("private_reasoning", None)
    data.pop("scratchpad", None)
    execution = dict(data.get("execution") or {})
    execution.pop("raw_response", None)
    execution.pop("chain_of_thought", None)
    if execution:
        data["execution"] = execution
    return data


def _framework_id_from_legacy(data: Mapping[str, Any]) -> str:
    if data.get("framework_id"):
        return str(data["framework_id"])
    framework = data.get("framework")
    if isinstance(framework, dict) and framework.get("id"):
        return str(framework["id"])
    if framework in {"Comercial Equilibrado", "commercial_balanced_v1"}:
        return "commercial_balanced_v1"
    if isinstance(framework, str) and framework.startswith("digital_services"):
        return "digital_services_b2b_v1"
    return "commercial_balanced_v1"


def _derived_evidence_cited(data: Mapping[str, Any]) -> List[str]:
    cited: List[str] = []
    for finding in data.get("material_findings") or []:
        if not isinstance(finding, dict):
            continue
        for key in ("evidence", "counterevidence"):
            for ref in finding.get(key) or []:
                if not isinstance(ref, dict):
                    continue
                document_id = ref.get("document_id") or ""
                chunk_id = ref.get("chunk_id") or ""
                if document_id and chunk_id:
                    cited.append(f"{document_id}/{chunk_id}")
                elif document_id:
                    cited.append(str(document_id))
    return cited


def public_decision_view(decision: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Serialização para API/UI: canônica, sem produzir `requires_human_review`."""
    data = normalize_legacy_decision(decision)
    data.pop("requires_human_review", None)
    data.pop("human_review_required", None)
    return data


def public_review_view(review: Mapping[str, Any] | None) -> Dict[str, Any]:
    data = normalize_legacy_review(review)
    data.pop("requires_human_review", None)
    data.pop("human_review_required", None)
    return data
