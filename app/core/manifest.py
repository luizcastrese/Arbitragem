import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.hashing import sha256_text
from app.core.signing import attach_signature

PLATFORM_VERSION = "0.1.0"
PROCEDURE_VERSION = "mvp-procedure-0.1"
DEFAULT_FRAMEWORK = "commercial_balanced_v1"



def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))



def canonical_hash(data: Any) -> str:
    return sha256_text(canonical_json(data))



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
            "decision_must_reference_retrieved_evidence": True,
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
        ],
    }

    model_policy = {
        "organizer": "configured_by_platform",
        "judge": "configured_by_platform",
        "reviewer": "configured_by_platform",
        "temperature": 0,
        "user_configurable_private_instructions": False,
    }

    allowed_agents = [
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

    case["locked_manifest"] = manifest
    case["manifest_locked"] = True
    return manifest
