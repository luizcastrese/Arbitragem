from typing import List


def chunk_text(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> List[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)

    return chunks
