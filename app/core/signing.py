import hmac
from typing import Any, Dict

from app.core.canonical import canonical_json
from app.core.config import get_settings


def get_signing_secret() -> str:
    return get_settings().platform_signing_secret


def sign_payload(payload: Any) -> str:
    serialized = canonical_json(payload)
    secret = get_signing_secret().encode("utf-8")
    return hmac.new(secret, serialized.encode("utf-8"), "sha256").hexdigest()


def attach_signature(payload: Dict) -> Dict:
    signed_payload = dict(payload)
    signed_payload["platform_signature"] = sign_payload(payload)
    signed_payload["signature_algorithm"] = "HMAC-SHA256"
    return signed_payload


def verify_signature(payload: Dict) -> bool:
    if "platform_signature" not in payload:
        return False

    signature = payload.get("platform_signature")
    unsigned_payload = dict(payload)
    unsigned_payload.pop("platform_signature", None)
    unsigned_payload.pop("signature_algorithm", None)

    expected = sign_payload(unsigned_payload)
    return hmac.compare_digest(signature, expected)
