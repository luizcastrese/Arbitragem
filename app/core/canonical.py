import json
from typing import Any

from app.core.hashing import sha256_text


def canonical_json(data: Any) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_hash(data: Any) -> str:
    return sha256_text(canonical_json(data))
