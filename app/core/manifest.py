from datetime import datetime, timezone
from typing import Dict, List

from app.core.canonical import canonical_hash
from app.core.config import get_settings
from app.core.signing import attach_signature

PLATFORM_VERSION = "0.4.0"
PROCEDURE_VERSION = "mvp-procedure-0.4"
DEFAULT_FRAMEWORK = "commercial_balanced_v1"



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

    manifest = {
        "platform_version": PLATFORM_VERSION,
        "procedure_version": PROCEDURE_VERSION,
        "case_id": case.get("id"),
        "case_title": case.get("title"),
        "consent": case.get("consent"),
        "contradictory": case.get("contradictory"),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "framework": framework,
        "model_policy": selected_model_policy,
        "allowed_agents": allowed_agents,
        "documents": documents,
        "chunks": chunks,
        "anti_bias_commitments": {
            "initiating_party_cannot_choose_private_prompt": True,
            "initiating_party_cannot_change_framework_after_lock": True,
            "all_documents_are_hashed": True,
            "all_material_must_be_disclosed_to_counterparty": True,
            "decision_uses_only_admitted_material": True,
            "pending_counterparty_response_blocks_lock": True,
            "decision_must_reference_retrieved_evidence": True,
            "consensual_resolution_screening_precedes_adjudication": True,
            "reviewer_agent_checks_framework_alignment": True,
            "counterparty_can_verify_manifest_hash": True,
            "platform_signature_required": True,
            "manifest_becomes_immutable_after_lock": True,
        },
    }

    manifest["manifest_hash"] = canonical_hash(manifest)

    signed_manifest = attach_signature(manifest)
    return signed_manifest



def lock_case_manifest(case: Dict) -> Dict:
    if case.get("locked_manifest"):
        return case["locked_manifest"]

    framework = {
        "id": DEFAULT_FRAMEWORK,
        "name": "Comercial Equilibrado",
        "version": "1.0",
        "principles": [
            "prioridade contratual",
            "proporcionalidade",
            "boa-fé",
            "vedação ao enriquecimento injusto",
            "análise contextual de atrasos",
            "cumprimento parcial pode justificar pagamento proporcional",
            "prioridade à solução consensual quando houver convergência de interesses",
        ],
    }

    settings = get_settings()
    model_policy = {
        "conciliator": settings.openai_model,
        "organizer": settings.openai_model,
        "judge": settings.openai_model,
        "reviewer": settings.openai_model,
        "embedding": settings.embedding_model,
        "openai_enabled_at_lock": settings.openai_enabled,
        "user_configurable_private_instructions": False,
    }

    allowed_agents = [
        "conciliator",
        "organizer",
        "judge",
        "reviewer",
    ]

    manifest = build_process_manifest(
        case=case,
        framework=framework,
        selected_model_policy=model_policy,
        allowed_agents=allowed_agents,
    )

    return manifest
