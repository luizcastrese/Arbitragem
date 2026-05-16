from typing import Dict, List

import numpy as np

from app.core.llm import generate_embedding



def build_embedding(text: str) -> List[float]:
    return generate_embedding(text)



def cosine_similarity(a: List[float], b: List[float]) -> float:
    a_np = np.array(a)
    b_np = np.array(b)

    denominator = np.linalg.norm(a_np) * np.linalg.norm(b_np)

    if denominator == 0:
        return 0.0

    return float(np.dot(a_np, b_np) / denominator)



def retrieve_by_embedding(query: str, chunks: List[Dict], limit: int = 5) -> List[Dict]:
    query_embedding = build_embedding(query)

    scored_chunks = []

    for chunk in chunks:
        embedding = chunk.get("embedding")

        if not embedding:
            continue

        score = cosine_similarity(query_embedding, embedding)

        scored_chunks.append({
            **chunk,
            "score": round(score, 4)
        })

    scored_chunks.sort(key=lambda item: item["score"], reverse=True)

    return scored_chunks[:limit]
