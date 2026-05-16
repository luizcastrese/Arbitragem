import hashlib
from typing import Union


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: Union[bytes, bytearray]) -> str:
    return hashlib.sha256(bytes(value)).hexdigest()
