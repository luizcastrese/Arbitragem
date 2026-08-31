from typing import Dict, List

from pydantic import BaseModel

from app.agents.execution import fallback_execution, openai_execution
from app.core.llm import call_openai_structured
from app.core.prompt_registry import register_prompt
from app.documents.embeddings import retrieve_by_embedding
from app.documents.retrieval import retrieve_relevant_chunks


ORGANIZATION_QUERIES = [
    "obrigações de entrega",
    "condições de pagamento",
    "cumprimento de prazos",
    "divergência sobre o escopo",
    "cumprimento parcial",
]


class OrganizerOutput(BaseModel):
    summary: str
    factual_overview: str
    undisputed_facts: List[str]
    disputed_facts: List[str]
    claimant_requests: List[str]
    respondent_arguments: List[str]
    relevant_evidence: List[str]
    relevant_clauses: List[str]
    timeline: List[str]
    missing_information: List[str]


SYSTEM_PROMPT = """
Você é o agente organizador de um sistema de auditoria decisória por IA.
Não decida a disputa. Organize somente o registro fornecido.

Regras:
- Não invente fatos, cláusulas, datas ou pedidos.
- Separe fatos comprovados de alegações.
- Use referências no formato document_id/chunk_id sempre que possível.
- Aponte evidência fraca, contraditória ou ausente.
- Responda em português do Brasil.
"""

PROMPT = register_prompt("organizer", "1.0.0", SYSTEM_PROMPT)


def _safe_retrieve(query: str, chunks: List[Dict], limit: int = 3) -> List[Dict]:
    try:
        embedded = retrieve_by_embedding(query=query, chunks=chunks, limit=limit)
        if embedded:
            return embedded
    except Exception:
        pass
    return retrieve_relevant_chunks(query=query, chunks=chunks, limit=limit)


def _fallback_organization(
    documents: List[Dict],
    retrieved_context: Dict[str, List[Dict]],
    reason: str,
) -> Dict:
    evidence = []
    for results in retrieved_context.values():
        for chunk in results:
            reference = f"{chunk.get('document_id')}/{chunk.get('id')}"
            if reference not in evidence:
                evidence.append(reference)

    return {
        "summary": "Documentos recebidos e indexados; análise semântica indisponível.",
        "factual_overview": " ".join(
            document.get("content", "")[:500] for document in documents
        )[:2000],
        "undisputed_facts": [],
        "disputed_facts": [],
        "claimant_requests": [],
        "respondent_arguments": [],
        "relevant_evidence": evidence[:10],
        "relevant_clauses": [],
        "timeline": [],
        "missing_information": [
            "A organização por IA não foi executada.",
            "O registro documental permanece disponível para as etapas seguintes.",
        ],
        "retrieved_context_used": retrieved_context,
        "execution": fallback_execution(PROMPT, reason),
    }


def organize_case(documents: List[Dict], chunks: List[Dict]) -> Dict:
    retrieved_context = {
        query: _safe_retrieve(query=query, chunks=chunks, limit=3)
        for query in ORGANIZATION_QUERIES
    }
    payload = {
        "documents": [
            {
                "id": document.get("id"),
                "name": document.get("name"),
                "sha256": document.get("sha256"),
                "submitted_by": document.get("submitted_by"),
                "material_type": document.get("material_type"),
                "purpose": document.get("purpose"),
                "counterparty_response_status": document.get("response_status"),
                "counterparty_response": document.get("response_text"),
                "admitted": document.get("admitted"),
                "content": document.get("content", "")[:8000],
            }
            for document in documents
        ],
        "retrieved_context": retrieved_context,
    }

    try:
        result = call_openai_structured(
            system_prompt=PROMPT.text,
            user_payload=payload,
            response_model=OrganizerOutput,
            agent="organizer",
        )
    except Exception as exc:
        return _fallback_organization(
            documents,
            retrieved_context,
            type(exc).__name__,
        )

    organized = dict(result.data)
    organized["retrieved_context_used"] = retrieved_context
    organized["execution"] = openai_execution(PROMPT, result)
    return organized
