from datetime import datetime, timezone
from typing import Dict, List

from app.core.canonical import canonical_hash
from app.core.config import get_settings
from app.core.signing import attach_signature
from app.core.terms import current_terms
from app.domain.decision_verifier import VERIFIER_VERSION
from app.domain.frameworks import resolve_framework
from app.domain.provenance import (
    ATTESTATION_SCHEMA_VERSION,
    CANONICALIZATION_VERSION,
    HASH_ALGORITHM,
    response_schema_hash,
)

PLATFORM_VERSION = "0.6.0"
PROCEDURE_VERSION = "autonomous-procedure-0.6"
DEFAULT_FRAMEWORK = "digital_services_b2b_v1"


def _prompt_policy() -> Dict:
    """Versão e hash do prompt de cada agente no momento da trava.

    A importação é local de propósito: registrar um prompt é efeito de importar
    o agente, e o manifesto também é gerado fora da API (testes e avaliações).
    """
    from app.agents import appeal, conciliator, judge, organizer, reviewer  # noqa: F401
    from app.core.prompt_registry import prompt_policy

    return prompt_policy()


def _response_schema_policy() -> Dict:
    from app.agents.conciliator import ConciliationOutput
    from app.agents.judge import DecisionOutput
    from app.agents.organizer import OrganizerOutput
    from app.agents.reviewer import ReviewOutput

    models = {
        "conciliator": ConciliationOutput,
        "organizer": OrganizerOutput,
        "judge": DecisionOutput,
        "reviewer": ReviewOutput,
    }
    return {
        agent: {
            "schema_version": "1.0",
            "schema_hash": response_schema_hash(model),
        }
        for agent, model in models.items()
    }


def _accepted_terms(case: Dict) -> Dict:
    """Versão e hash do texto que cada parte efetivamente aceitou, mais a
    versão vigente no momento da trava. Com isso o manifesto assinado carrega
    a prova do que foi aceito, e não apenas um número de versão."""
    consent = case.get("consent") or {}
    vigente = current_terms()
    return {
        "current_version": vigente.version,
        "current_sha256": vigente.sha256,
        "accepted": {
            party: {
                "version": (consent.get(party) or {}).get("terms_version"),
                "sha256": (consent.get(party) or {}).get("terms_sha256"),
            }
            for party in ("claimant", "respondent")
        },
    }


def build_process_manifest(
    case: Dict,
    framework: Dict,
    selected_model_policy: Dict,
    allowed_agents: List[str],
) -> Dict:
    documents = [
        {
            "id": document.get("id"),
            "name": document.get("name"),
            "sha256": document.get("sha256"),
            "submitted_by": document.get("submitted_by"),
            "material_type": document.get("material_type"),
            "purpose": document.get("purpose"),
            "disclosed_at": document.get("disclosed_at"),
            "acknowledged_at": document.get("acknowledged_at"),
            "acknowledged_by": document.get("acknowledged_by"),
            "response_status": document.get("response_status"),
            "response_sha256": (
                canonical_hash({"response": document.get("response_text")})
                if document.get("response_text")
                else None
            ),
            "admitted": document.get("admitted"),
            "chunks_count": document.get("chunks_count"),
        }
        for document in case.get("documents", [])
    ]

    chunks = [
        {
            "id": chunk.get("id"),
            "document_id": chunk.get("document_id"),
            "sha256": chunk.get("sha256"),
        }
        for chunk in case.get("chunks", [])
    ]

    settings = get_settings()
    prompt_policy = selected_model_policy.get("prompts") or _prompt_policy()
    manifest = {
        "platform_version": PLATFORM_VERSION,
        "procedure_version": PROCEDURE_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "attestation_schema_version": ATTESTATION_SCHEMA_VERSION,
        "deterministic_verification_version": VERIFIER_VERSION,
        "case_id": case.get("id"),
        "case_title": case.get("title"),
        "consent": case.get("consent"),
        "terms": _accepted_terms(case),
        "terms_version": (_accepted_terms(case).get("current_version")),
        "terms_hash": (_accepted_terms(case).get("current_sha256")),
        "contradictory": case.get("contradictory"),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "framework": framework,
        "framework_id": framework.get("id"),
        "framework_version": framework.get("version"),
        "framework_hash": framework.get("hash"),
        "model_policy": selected_model_policy,
        "prompt_bundle": {
            "id": f"valinor-prompts-{PROCEDURE_VERSION}",
            "version": PROCEDURE_VERSION,
            "hashes": {
                agent: ref.get("sha256")
                for agent, ref in prompt_policy.items()
                if isinstance(ref, dict)
            },
        },
        "response_schemas": _response_schema_policy(),
        "admissibility_profile": {
            "framework_id": framework.get("id"),
            "exclusions": framework.get("exclusions") or [],
            "case_value_limit_minor_units": (
                framework.get("case_value_limit_minor_units")
                or settings.case_value_limit_minor_units
            ),
            "case_value_currency": framework.get("case_value_currency") or "BRL",
        },
        "case_value_limits": {
            "minor_units": settings.case_value_limit_minor_units,
            "currency": "BRL",
        },
        "allowed_agents": allowed_agents,
        "documents": documents,
        "chunks": chunks,
        "anti_bias_commitments": {
            "initiating_party_cannot_choose_private_prompt": True,
            "initiating_party_cannot_change_framework_after_lock": True,
            "parties_cannot_choose_model_after_decision": True,
            "parties_cannot_add_document_after_lock": True,
            "parties_cannot_repeat_decision_indefinitely": True,
            "parties_cannot_select_favorable_reviewer": True,
            "all_documents_are_hashed": True,
            "all_material_must_be_disclosed_to_counterparty": True,
            "decision_uses_only_admitted_material": True,
            "pending_counterparty_response_blocks_lock": True,
            "decision_must_reference_retrieved_evidence": True,
            "consensual_resolution_screening_precedes_adjudication": True,
            "reviewer_agent_checks_framework_alignment": True,
            "judge_and_reviewer_policies_are_independent": bool(
                selected_model_policy.get("model_independence_satisfied")
            ),
            "counterparty_can_verify_manifest_hash": True,
            "platform_signature_required": True,
            "manifest_becomes_immutable_after_lock": True,
            "procedure_is_autonomous_without_internal_human_adjudicator": True,
        },
    }

    manifest["manifest_hash"] = canonical_hash(manifest)

    signed_manifest = attach_signature(manifest)
    return signed_manifest


def assert_manifest_invariants(manifest: Dict, case: Dict, action: str) -> List[str]:
    """Invariantes verificadas, não apenas texto. Devolve códigos de violação."""
    violations: List[str] = []
    commitments = manifest.get("anti_bias_commitments") or {}
    if action == "add_document" and manifest:
        violations.append("document_after_lock")
    if action == "change_framework" and manifest:
        violations.append("framework_after_lock")
    if action == "choose_private_prompt":
        violations.append("private_prompt_forbidden")
    if action == "choose_reviewer":
        violations.append("reviewer_selection_forbidden")
    if action == "choose_model_after_decision" and case.get("decision"):
        violations.append("model_after_decision")
    if action == "repeat_decision" and case.get("decision"):
        current_runs = case.get("decision_runs") or []
        finals = [
            item
            for item in current_runs
            if isinstance(item, dict) and item.get("status") in {"final", "completed"}
        ]
        if len(finals) >= 1 and not case.get("allow_reconstruction"):
            violations.append("repeat_decision_forbidden")
    if not commitments.get("decision_uses_only_admitted_material", True):
        violations.append("admitted_material_invariant_missing")
    return violations


def lock_case_manifest(case: Dict) -> Dict:
    if case.get("locked_manifest"):
        return case["locked_manifest"]

    settings = get_settings()
    framework_id = (
        (case.get("framework_id") if isinstance(case.get("framework_id"), str) else None)
        or settings.framework_id
        or DEFAULT_FRAMEWORK
    )
    try:
        framework_obj = resolve_framework(framework_id)
    except LookupError as exc:
        raise ValueError(f"Framework desconhecido: {framework_id}") from exc
    framework = framework_obj.lock_summary()

    model_policy = {
        **settings.agent_model_policy(),
        "prompts": _prompt_policy(),
    }

    allowed_agents = [
        "conciliator",
        "organizer",
        "judge",
        "reviewer",
        "appeal",
    ]

    manifest = build_process_manifest(
        case=case,
        framework=framework,
        selected_model_policy=model_policy,
        allowed_agents=allowed_agents,
    )

    return manifest
