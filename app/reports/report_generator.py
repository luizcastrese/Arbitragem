from typing import Dict


def build_report(case: Dict) -> Dict:
    return {
        "case_id": case.get("id"),
        "title": case.get("title"),
        "parties": {
            "claimant": case.get("claimant"),
            "respondent": case.get("respondent"),
        },
        "status": case.get("status"),
        "manifest": case.get("locked_manifest"),
        "documents": [
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
                "response_text": document.get("response_text"),
                "responded_at": document.get("responded_at"),
                "admitted": document.get("admitted"),
                "admitted_at": document.get("admitted_at"),
                "chunks_count": document.get("chunks_count"),
            }
            for document in case.get("documents", [])
        ],
        "consent": case.get("consent"),
        "contradictory": case.get("contradictory"),
        "conciliation": case.get("conciliation"),
        "conciliation_rounds": case.get("conciliation_rounds", []),
        "organized": case.get("organized"),
        "decision": case.get("decision"),
        "review": case.get("review"),
        "finalization": case.get("finalization"),
        "audit_log": case.get("audit_log", []),
        "disclaimer": (
            "O sistema profere uma decisão computacional conforme o procedimento "
            "configurado. Essa saída não constitui, por si só, sentença arbitral "
            "ou decisão estatal; eventual eficácia jurídica depende da estrutura "
            "contratual adotada e da legislação aplicável."
        ),
    }
