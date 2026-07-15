from __future__ import annotations

from app.core.config import get_settings


PREFIX = "enc:v1:"


def _fernet():
    key = get_settings().data_encryption_key
    if not key:
        return None
    from cryptography.fernet import Fernet

    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("DATA_ENCRYPTION_KEY não é uma chave Fernet válida") from exc


def encrypt_text(value: str | None) -> str | None:
    if value is None or value.startswith(PREFIX):
        return value
    cipher = _fernet()
    if cipher is None:
        return value
    encrypted = cipher.encrypt(value.encode("utf-8")).decode("ascii")
    return PREFIX + encrypted


def decrypt_text(value: str | None) -> str | None:
    if value is None or not value.startswith(PREFIX):
        return value
    cipher = _fernet()
    if cipher is None:
        raise RuntimeError("DATA_ENCRYPTION_KEY é necessária para ler os dados")
    from cryptography.fernet import InvalidToken

    try:
        return cipher.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Não foi possível descriptografar o dado armazenado") from exc
