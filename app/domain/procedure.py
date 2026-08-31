"""Orquestração autônoma: decisão, verificação, revisão, estabilidade e recurso.

Este módulo chama agentes de IA, mas a verificação determinística permanece
em `decision_verifier` e não depende de modelo.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.agents.appeal import SYSTEM_PROMPT as _APPEAL_PROMPT
from app.agents.judge import DecisionOutput, decide_case as judge_decide_case
from app.agents.reviewer import review_decision
from app.core.canonical import canonical_hash
from app.core.config import get_settings
from app.core.prompt_registry import get_prompt
from app.db.models import AutomaticAppeal, Case
from app.db.repository import (
    append_audit,
    complete_appeal,
    persist_appeal,
    persist_attestation_record,
    persist_decision_run,
    persist_llm_execution,
    persist_review_run,
    persist_verification,
)
from app.domain.decision_verifier import verify_decision
from app.domain.frameworks import Framework, resolve_framework
from app.domain.legacy import (
    infer_procedure_conclusion,
    strip_private_reasoning,
)
from app.domain.models import AppealResult
from app.domain.provenance import build_provenance, verification_result_hash
from app.domain.stability import compare_decisions, neutralize_party_order
from app.llm.errors import LLMCallError, LLMUnavailable
from app.llm.registry import execution_policy_for, generate_structured

logger = logging.getLogger("valinor.procedure")


def _framework_from_manifest(manifest: Dict[str, Any]) -> Framework:
    framework_id = (manifest.get("framework") or {}).get("id") or manifest.get(
        "framework_id"
    )
    return resolve_framework(framework_id)


def _admitted(case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        document
        for document in case_data.get("documents") or []
        if document.get("admitted")
    ]


def _safe_log_verification_failure(case_id: str, codes: List[str]) -> None:
    logger.warning(
        "decision_verification_failed case=%s codes=%s",
        case_id,
        ",".join(codes[:20]),
    )


def _conclusion_from_verification_and_decision(
    decision: Dict[str, Any],
    verification_valid: bool,
) -> str:
    if not verification_valid:
        return "invalidated"
    reasons = decision.get("abstention_reasons") or []
    if "out_of_scope" in reasons or "framework_not_applicable" in reasons:
        return "inadmissible"
    if "procedure_integrity_failure" in reasons or "prompt_injection_detected" in reasons:
        return "invalidated"
    if decision.get("execution", {}).get("mode") == "safe_fallback":
        return "system_failure"
    if "provider_unavailable" in reasons:
        return "system_failure"
    return infer_procedure_conclusion(decision)


def _attach_provenance(
    decision: Dict[str, Any],
    case_data: Dict[str, Any],
    decision_input: Dict[str, Any],
    framework: Framework,
    verification: Dict[str, Any],
) -> Dict[str, Any]:
    manifest = case_data.get("locked_manifest") or {}
    documents = [
        {"id": item.get("id"), "sha256": item.get("sha256")}
        for item in (manifest.get("documents") or [])
    ]
    chunks = manifest.get("chunks") or []
    admitted_ids = [
        item.get("id")
        for item in (case_data.get("documents") or [])
        if item.get("admitted")
    ]
    prompt_ref = (decision.get("execution") or {}).get("prompt") or {}
    model_policy = manifest.get("model_policy") or {}
    provenance = build_provenance(
        decision=decision,
        decision_input=decision_input,
        documents=documents,
        chunks=chunks,
        admitted_ids=admitted_ids,
        framework=framework,
        prompt_ref=prompt_ref,
        response_model=DecisionOutput,
        model_policy=model_policy,
        verification=verification,
        manifest_hash=manifest.get("manifest_hash") or "",
        execution_id=(decision.get("execution") or {}).get("execution_id"),
    )
    decision["provenance"] = provenance
    decision["verification_summary"] = {
        "valid": verification.get("valid"),
        "error_codes": [
            item.get("code") if isinstance(item, dict) else getattr(item, "code", None)
            for item in (verification.get("errors") or [])
        ],
        "verified_evidence_count": verification.get("verified_evidence_count"),
        "verifier_version": verification.get("verifier_version"),
    }
    return decision


def generate_and_verify_decision(
    db: Session,
    case: Case,
    case_data: Dict[str, Any],
    decision_input: Dict[str, Any],
    *,
    role: str = "judge",
    agent: str = "judge",
    supersedes_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Gera uma decisão, verifica e persiste o run. Não marca attestation."""
    manifest = case_data.get("locked_manifest") or {}
    framework = _framework_from_manifest(manifest)
    decision = judge_decide_case(decision_input, agent=agent)
    persist_llm_execution(
        db,
        case,
        decision.get("execution") or {},
        agent=agent,
        task=role,
        input_hash=canonical_hash(
            {k: v for k, v in decision_input.items() if k != "organized_case"}
        ),
        output_hash=canonical_hash(
            {k: v for k, v in decision.items() if k != "execution"}
        ),
    )

    verification = verify_decision(
        decision,
        manifest,
        _admitted(case_data),
        case_data.get("chunks") or [],
        framework,
    )
    verification_dump = verification.model_dump()
    result_hash = verification_result_hash(verification_dump)
    decision = _attach_provenance(
        decision, case_data, decision_input, framework, verification_dump
    )
    conclusion = _conclusion_from_verification_and_decision(
        decision, verification.valid
    )
    decision["procedure_conclusion"] = conclusion

    if not verification.valid:
        _safe_log_verification_failure(
            case.id,
            [item.code for item in verification.errors],
        )
        append_audit(
            db,
            case,
            "decision_verification_failed",
            {
                "valid": False,
                "codes": [item.code for item in verification.errors],
                "verifier_version": verification.verifier_version,
            },
        )

    run_status = "verified" if verification.valid else "invalid"
    if conclusion in {"invalidated", "system_failure", "inadmissible", "inconclusive"}:
        run_status = conclusion
    run = persist_decision_run(
        db,
        case,
        decision,
        status=run_status,
        role=role,
        supersedes_id=supersedes_id,
        idempotency_key=idempotency_key,
        provenance=decision.get("provenance"),
        input_hash=decision.get("provenance", {}).get("decision_input_hash"),
        output_hash=decision.get("provenance", {}).get("decision_payload_hash"),
    )
    persist_verification(
        db,
        case,
        verification_dump,
        result_hash=result_hash,
        decision_run_id=run.id,
    )
    return decision, verification_dump, conclusion


def maybe_run_stability(
    db: Session,
    case: Case,
    case_data: Dict[str, Any],
    decision_input: Dict[str, Any],
    first_decision: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    if not settings.decision_stability_enabled:
        return None
    runs = [first_decision]
    execution_ids = [(first_decision.get("execution") or {}).get("execution_id")]
    extra = max(1, settings.decision_stability_runs - 1)
    for _ in range(extra):
        payload = neutralize_party_order(decision_input)
        second = judge_decide_case(payload)
        runs.append(second)
        execution_ids.append((second.get("execution") or {}).get("execution_id"))
        persist_llm_execution(
            db,
            case,
            second.get("execution") or {},
            agent="judge",
            task="stability",
        )
    result = compare_decisions(
        runs,
        threshold=settings.decision_stability_threshold,
        execution_ids=[item for item in execution_ids if item],
    )
    dump = result.model_dump()
    case.stability_json = __import__("json").dumps(dump, ensure_ascii=False)
    append_audit(
        db,
        case,
        "decision_stability_checked",
        {
            "stable": result.stable,
            "compared_runs": result.compared_runs,
            "disagreements": result.material_disagreements,
        },
    )
    return dump


def reviewer_payload(
    case_data: Dict[str, Any],
    decision: Dict[str, Any],
    verification: Dict[str, Any],
) -> Dict[str, Any]:
    manifest = case_data.get("locked_manifest") or {}
    public_decision = strip_private_reasoning(decision)
    return {
        "manifest": manifest,
        "evidence_map": {
            "documents": manifest.get("documents") or [],
            "chunks": manifest.get("chunks") or [],
            "admitted_document_ids": [
                item.get("id")
                for item in (case_data.get("documents") or [])
                if item.get("admitted")
            ],
        },
        "findings": public_decision.get("material_findings") or [],
        "rules": (manifest.get("framework") or {}).get("rule_ids") or [],
        "decision": public_decision,
        "verification": verification,
        "organized_case": case_data.get("organized"),
        "conciliation_rounds": case_data.get("conciliation_rounds") or [],
    }


def alternate_judge_available() -> bool:
    settings = get_settings()
    appeal = (settings.appeal_provider, settings.appeal_model)
    judge = (settings.judge_provider, settings.judge_model)
    return appeal != judge


def run_automatic_review(
    db: Session,
    case: Case,
    case_data: Dict[str, Any],
    decision: Dict[str, Any],
    verification: Dict[str, Any],
) -> Dict[str, Any]:
    payload = reviewer_payload(case_data, decision, verification)
    review = review_decision(payload)
    persist_llm_execution(
        db,
        case,
        review.get("execution") or {},
        agent="reviewer",
        task="review",
        input_hash=canonical_hash({"decision_hash": (decision.get("provenance") or {}).get("decision_payload_hash")}),
        output_hash=canonical_hash({k: v for k, v in review.items() if k != "execution"}),
    )
    persist_review_run(
        db,
        case,
        review,
        status=review.get("outcome") or "completed",
        output_hash=canonical_hash({k: v for k, v in review.items() if k != "execution"}),
    )
    return review


def reconstruct_once(
    db: Session,
    case: Case,
    case_data: Dict[str, Any],
    decision_input: Dict[str, Any],
    original_run_id: Optional[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
    """Uma única reconstrução com política de julgador distinta.

    Usa a política do recurso (`appeal`) quando ela difere da do julgador.
    Sem política independente, não regenera com o mesmo modelo.
    """
    if not alternate_judge_available():
        raise RuntimeError("reconstruction requires an independent judge policy")
    append_audit(
        db,
        case,
        "decision_reconstruction_started",
        {
            "supersedes_id": original_run_id,
            "reason": "automatic_review_rejected",
            "reconstruction_agent": "appeal",
        },
    )
    decision, verification, conclusion = generate_and_verify_decision(
        db,
        case,
        case_data,
        decision_input,
        role="reconstruction",
        agent="appeal",
        supersedes_id=original_run_id,
    )
    stability = maybe_run_stability(db, case, case_data, decision_input, decision)
    if stability and not stability.get("stable"):
        decision["outcome"] = "inconclusive"
        decision["procedure_conclusion"] = "inconclusive"
        decision.setdefault("abstention_reasons", [])
        if "unstable_decision" not in decision["abstention_reasons"]:
            decision["abstention_reasons"].append("unstable_decision")
        if "material_model_disagreement" not in decision["abstention_reasons"]:
            decision["abstention_reasons"].append("material_model_disagreement")
        conclusion = "inconclusive"
    review = run_automatic_review(db, case, case_data, decision, verification)
    append_audit(
        db,
        case,
        "decision_reconstruction_completed",
        {
            "review_outcome": review.get("outcome"),
            "procedure_conclusion": conclusion,
            "stable": None if not stability else stability.get("stable"),
        },
    )
    return decision, verification, conclusion, review


def finalize_review_outcome(
    decision: Dict[str, Any],
    verification: Dict[str, Any],
    review: Dict[str, Any],
    reconstruction_used: bool,
) -> Tuple[str, Dict[str, Any]]:
    """Decide a conclusão autônoma após a auditoria (e eventual reconstrução)."""
    reasons = list(decision.get("abstention_reasons") or [])
    if "unstable_decision" in reasons or "material_model_disagreement" in reasons:
        decision["outcome"] = "inconclusive"
        decision["procedure_conclusion"] = "inconclusive"
        return "inconclusive", decision
    outcome = review.get("outcome")
    if outcome == "approved" and verification.get("valid") and decision.get("outcome") in {
        "claimant",
        "respondent",
        "partial",
    }:
        return "decided", decision
    if outcome == "approved" and decision.get("procedure_conclusion") in {
        "inconclusive",
        "inadmissible",
        "system_failure",
        "invalidated",
    }:
        return decision.get("procedure_conclusion") or "inconclusive", decision
    if outcome == "rejected" and not reconstruction_used:
        return "pending_reconstruction", decision
    # Reprovado após reconstrução, ou inclusive: não há loop.
    if not verification.get("valid"):
        decision["procedure_conclusion"] = "invalidated"
        decision.setdefault("abstention_reasons", [])
        if "procedure_integrity_failure" not in decision["abstention_reasons"]:
            decision["abstention_reasons"].append("procedure_integrity_failure")
        return "invalidated", decision
    decision["procedure_conclusion"] = "inconclusive"
    decision.setdefault("abstention_reasons", [])
    if "insufficient_evidence" not in decision["abstention_reasons"]:
        decision["abstention_reasons"].append("insufficient_evidence")
    return "inconclusive", decision


def run_appeal(
    db: Session,
    case: Case,
    case_data: Dict[str, Any],
    appeal: AutomaticAppeal,
    contest_payload: Dict[str, Any],
) -> Dict[str, Any]:
    from app.domain.models import DecisionOutput

    original = case_data.get("decision") or {}
    verification = case_data.get("verification") or {}
    review = case_data.get("review") or {}
    user_payload = {
        "manifest": case_data.get("locked_manifest"),
        "original_decision": strip_private_reasoning(original),
        "verification": verification,
        "review": strip_private_reasoning(review),
        "contest": contest_payload,
        "findings": original.get("material_findings") or [],
        "rules": (
            ((case_data.get("locked_manifest") or {}).get("framework") or {}).get("rule_ids")
            or []
        ),
    }
    policy = execution_policy_for("appeal")
    try:
        result = generate_structured(
            task="appeal",
            system_prompt=_APPEAL_PROMPT,
            user_payload=user_payload,
            response_model=AppealResult,
            execution_policy=policy,
        )
        appeal_result = result.parsed_output.model_dump()
        appeal_result["execution"] = {
            "mode": result.effective_provider,
            "provider": result.effective_provider,
            "model": result.effective_model,
            "model_requested": result.requested_model,
            "provider_requested": result.requested_provider,
            "response_id": result.provider_response_id,
            "attempts": result.attempts,
            "fallback_used": result.fallback_used,
            "fallback_reason": result.fallback_reason,
            "execution_id": result.provider_response_id,
        }
    except (LLMUnavailable, LLMCallError) as exc:
        appeal_result = {
            "outcome": "inconclusive",
            "explanation": "O recurso automático não pôde ser julgado por indisponibilidade do modelo.",
            "issues": [{"code": "appeal_unavailable", "message": type(exc).__name__}],
            "confidence": 0.0,
            "execution": {
                "mode": "safe_fallback",
                "reason": type(exc).__name__,
                "provider": policy.provider,
                "model_requested": policy.model,
            },
        }

    persist_llm_execution(
        db,
        case,
        appeal_result.get("execution") or {},
        agent="appeal",
        task="appeal",
    )

    outcome = appeal_result.get("outcome") or "inconclusive"
    if outcome == "corrected" and appeal_result.get("corrected_decision"):
        corrected = appeal_result["corrected_decision"]
        if isinstance(corrected, dict):
            framework = _framework_from_manifest(case_data.get("locked_manifest") or {})
            verification_obj = verify_decision(
                corrected,
                case_data.get("locked_manifest") or {},
                _admitted(case_data),
                case_data.get("chunks") or [],
                framework,
            )
            verification_dump = verification_obj.model_dump()
            if not verification_obj.valid:
                appeal_result["outcome"] = "inconclusive"
                outcome = "inconclusive"
                append_audit(
                    db,
                    case,
                    "appeal_correction_verification_failed",
                    {"codes": [item.code for item in verification_obj.errors]},
                )
            else:
                review = run_automatic_review(
                    db, case, case_data, corrected, verification_dump
                )
                if review.get("outcome") != "approved":
                    appeal_result["outcome"] = "inconclusive"
                    outcome = "inconclusive"
                    append_audit(
                        db,
                        case,
                        "appeal_correction_review_rejected",
                        {"review_outcome": review.get("outcome")},
                    )
                else:
                    original_run_id = case.current_decision_run_id
                    persist_decision_run(
                        db,
                        case,
                        corrected,
                        status="corrected",
                        role="appeal",
                        supersedes_id=original_run_id,
                        provenance=corrected.get("provenance"),
                    )
                    persist_verification(
                        db,
                        case,
                        verification_dump,
                        result_hash=verification_result_hash(verification_dump),
                    )
                    # A decisão corrente aponta para a correção; a original
                    # permanece no DecisionRun v1 e em original_decision.
                    case.decision_json = __import__("json").dumps(
                        corrected, ensure_ascii=False
                    )
                    case.review_json = __import__("json").dumps(
                        review, ensure_ascii=False
                    )
                    case.procedure_conclusion = "decided"
                    previous_attestation = {}
                    if case.attestation_json:
                        previous_attestation = __import__("json").loads(
                            case.attestation_json
                        )
                    persist_attestation_record(
                        db,
                        case,
                        {
                            "attestation_hash": canonical_hash(
                                {
                                    "supersedes_attestation_hash": previous_attestation.get(
                                        "attestation_hash"
                                    ),
                                    "appeal_id": appeal.id,
                                    "outcome": "corrected",
                                    "decision": corrected,
                                }
                            ),
                            "supersedes_attestation_hash": previous_attestation.get(
                                "attestation_hash"
                            ),
                            "appeal_id": appeal.id,
                            "outcome": "corrected",
                        },
                        appeal_id=appeal.id,
                    )

    result_hash = canonical_hash(
        {k: v for k, v in appeal_result.items() if k != "execution"}
    )
    complete_appeal(
        db,
        appeal,
        appeal_result,
        result_hash=result_hash,
        provider=(appeal_result.get("execution") or {}).get("provider"),
        model=(appeal_result.get("execution") or {}).get("model"),
        status=outcome,
    )

    append_audit(
        db,
        case,
        "appeal_completed",
        {
            "appeal_id": appeal.id,
            "outcome": outcome,
            "result_hash": result_hash,
        },
    )
    return appeal_result
