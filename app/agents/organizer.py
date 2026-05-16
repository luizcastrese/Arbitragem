from typing import Dict, List

from app.core.llm import call_openai_json
from app.documents.embeddings import retrieve_by_embedding
from app.documents.retrieval import retrieve_relevant_chunks


ORGANIZATION_QUERIES = [
    "delivery obligations",
    "payment terms",
    "deadline compliance",
    "scope disagreement",
    "partial fulfillment"
]


SYSTEM_PROMPT = """
You are a procedural organizer for an AI-assisted arbitration system.

Your job is NOT to decide the dispute.
Your job is to organize the record.

Return valid JSON only with these fields:
- summary
- factual_overview
- undisputed_facts
- disputed_facts
- claimant_requests
- respondent_arguments
- relevant_evidence
- relevant_clauses
- timeline
- missing_information
- retrieved_context_used

Rules:
- Do not invent facts.
- Cite document_id and chunk_id whenever possible.
- Separate facts from allegations.
- If evidence is weak or missing, say so.
"""



def _safe_retrieve(query: str, chunks: List[Dict], limit: int = 3) -> List[Dict]:
    try:
        return retrieve_by_embedding(query=query, chunks=chunks, limit=limit)
    except Exception:
        return retrieve_relevant_chunks(query=query, chunks=chunks, limit=limit)



def organize_case(documents: List[Dict], chunks: List[Dict]) -> Dict:
    combined_text = "\n".join([
        doc.get("content", "")[:2000] for doc in documents
    ])

    retrieved_context = {}

    for query in ORGANIZATION_QUERIES:
        retrieved_context[query] = _safe_retrieve(
            query=query,
            chunks=chunks,
            limit=3
        )

    payload = {
        "documents": [
            {
                "id": doc.get("id"),
                "name": doc.get("name"),
                "sha256": doc.get("sha256"),
                "content_preview": doc.get("content", "")[:1500]
            }
            for doc in documents
        ],
        "retrieved_context": retrieved_context,
        "combined_preview": combined_text[:4000]
    }

    try:
        return call_openai_json(
            system_prompt=SYSTEM_PROMPT,
            user_payload=payload
        )
    except Exception:
        return {
            "summary": "Potential contractual dispute detected.",
            "factual_overview": combined_text[:1000],
            "undisputed_facts": [],
            "disputed_facts": [
                "delivery status",
                "payment proportionality"
            ],
            "claimant_requests": [],
            "respondent_arguments": [],
            "relevant_evidence": [],
            "relevant_clauses": [],
            "timeline": [],
            "missing_information": [
                "LLM organization failed; fallback organization used."
            ],
            "retrieved_context_used": retrieved_context,
            "documents_analyzed": len(documents)
        }
