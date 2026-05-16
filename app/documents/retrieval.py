from typing import Dict, List
import math
import re


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower())


def term_frequency(tokens: List[str]) -> Dict[str, float]:
    counts: Dict[str, float] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1

    total = max(len(tokens), 1)
    return {token: count / total for token, count in counts.items()}


def cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    common = set(a.keys()) & set(b.keys())
    numerator = sum(a[token] * b[token] for token in common)

    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return numerator / (norm_a * norm_b)


def retrieve_relevant_chunks(query: str, chunks: List[Dict], limit: int = 5) -> List[Dict]:
    query_vector = term_frequency(tokenize(query))
    scored_chunks = []

    for chunk in chunks:
        chunk_vector = term_frequency(tokenize(chunk.get("text", "")))
        score = cosine_similarity(query_vector, chunk_vector)
        scored_chunks.append({**chunk, "score": round(score, 4)})

    scored_chunks.sort(key=lambda item: item["score"], reverse=True)
    return scored_chunks[:limit]
