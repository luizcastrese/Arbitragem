"""Criptografia de documentos em repouso (AES-256-GCM).

Cada objeto é cifrado com uma chave simétrica da plataforma e um nonce
aleatório por objeto. O formato gravado é ``MAGIC || nonce(12) || ciphertext``,
onde o ciphertext do AES-GCM já inclui a tag de autenticação — qualquer
adulteração é detectada na decifragem.

Objetos legados gravados em claro (sem o cabeçalho ``MAGIC``) continuam
legíveis, o que permite migração incremental.

A chave vem de ``DOCUMENT_ENCRYPTION_KEY`` (base64 de 32 bytes). Sem chave, a
criptografia fica desabilitada e os objetos são gravados em claro.
"""

import base64
import os
from functools import lru_cache
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"VENC1"
NONCE_BYTES = 12


class DocumentCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("A chave de criptografia deve ter 32 bytes")
        self._aes = AESGCM(key)

    def encrypt(self, data: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._aes.encrypt(nonce, data, None)
        return MAGIC + nonce + ciphertext

    def decrypt(self, blob: bytes) -> bytes:
        if not blob.startswith(MAGIC):
            # Objeto legado gravado em claro.
            return blob
        nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
        ciphertext = blob[len(MAGIC) + NONCE_BYTES :]
        return self._aes.decrypt(nonce, ciphertext, None)

    @staticmethod
    def is_encrypted(blob: bytes) -> bool:
        return blob.startswith(MAGIC)


def load_key() -> Optional[bytes]:
    raw = os.getenv("DOCUMENT_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "DOCUMENT_ENCRYPTION_KEY inválida: use base64 de 32 bytes"
        ) from exc
    if len(key) != 32:
        raise ValueError(
            "DOCUMENT_ENCRYPTION_KEY inválida: são necessários 32 bytes"
        )
    return key


@lru_cache(maxsize=1)
def get_document_cipher() -> Optional[DocumentCipher]:
    key = load_key()
    return DocumentCipher(key) if key else None


def generate_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


if __name__ == "__main__":  # pragma: no cover
    print(generate_key())
