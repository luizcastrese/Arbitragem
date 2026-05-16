from typing import Dict, List

from app.documents.retrieval import retrieve_relevant_chunks


ORGANIZATION_QUERIES = [
    "delivery obligations",
    "payment terms",
    "deadline compliance",
    "scope disagreement",
    "partial fulfillment"
]


def organize_case(documents: List[Dict], chunks: List[Dict]) -> Dict:
    combined_text = "\n".join([
        doc.get("content", "") for doc in documents
    ])

    retrieved_context = {}

    for query in ORGANIZATION_QUERIES:
        retrieved_context[query] = retrieve_relevant_chunks(
            query=query,
            chunks=chunks,
            limit=3
        )

    return {
        "summary": "Potential contractual dispute detected.",
        "factual_overview": combined_text[:1000],
        "controversial_points": [
            "delivery status",
            "payment proportionality"
        ],
        "documents_analyzed": len(documents),
        "retrieved_context": retrieved_context
    }
