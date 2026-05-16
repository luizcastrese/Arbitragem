from typing import Dict, List


def organize_case(documents: List[Dict]) -> Dict:
    combined_text = "\n".join([
        doc.get("content", "") for doc in documents
    ])

    return {
        "summary": "Potential contractual dispute detected.",
        "factual_overview": combined_text[:1000],
        "controversial_points": [
            "delivery status",
            "payment proportionality"
        ],
        "documents_analyzed": len(documents)
    }
