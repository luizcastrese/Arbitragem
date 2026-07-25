"""URLs de download assinadas e temporárias.

Como os documentos são cifrados em repouso, o download precisa passar pela
aplicação para ser decifrado. Em vez de exigir sessão autenticada a cada
acesso, emitimos um token assinado (HMAC-SHA256) com validade curta: quem
tiver o link consegue baixar até a expiração, sem outra credencial.

O token carrega a chave do objeto, o nome do arquivo e o media type, tudo
protegido pela assinatura — nada disso pode ser forjado ou alterado sem o
segredo da plataforma.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Dict, Tuple

from app.core.config import get_settings


class SignedUrlError(Exception):
    pass


def _secret() -> bytes:
    return get_settings().platform_signing_secret.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_download_token(
    key: str,
    filename: str,
    media_type: str,
    expires_in: int,
) -> Tuple[str, int]:
    expires_at = int(time.time()) + int(expires_in)
    payload = _b64encode(
        json.dumps(
            {"k": key, "n": filename, "m": media_type, "e": expires_at},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = hmac.new(
        _secret(), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}", expires_at


def verify_download_token(token: str) -> Dict[str, str]:
    try:
        payload, signature = token.rsplit(".", 1)
    except ValueError as exc:
        raise SignedUrlError("Token malformado") from exc

    expected = hmac.new(
        _secret(), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise SignedUrlError("Assinatura inválida")

    try:
        data = json.loads(_b64decode(payload))
    except Exception as exc:  # noqa: BLE001
        raise SignedUrlError("Conteúdo do token inválido") from exc

    if int(time.time()) > int(data.get("e", 0)):
        raise SignedUrlError("Link expirado")

    return data
