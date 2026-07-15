"""Decision Attestation: artefato assinado (Ed25519) que executores externos
(instituição de pagamento ou contrato inteligente) consomem para liberar o
escrow conforme a decisão do procedimento.

A attestation referencia o manifest_hash, o topo da cadeia de auditoria e os
hashes da decisão e da revisão, tornando-a verificável offline com a chave
pública da plataforma.
"""

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.canonical import canonical_hash, canonical_json
from app.core.config import get_settings

ATTESTATION_VERSION = "1.0"
SIGNATURE_ALGORITHM = "Ed25519"

_SIGNATURE_FIELDS = ("signature", "signature_algorithm")


class AttestationError(RuntimeError):
    """Erro de configuração ou de pré-condição na emissão da attestation."""


def load_private_key(raw: Optional[str] = None) -> Ed25519PrivateKey:
    """Carrega a chave privada Ed25519 a partir da configuração.

    Formato aceito: base64 da seed de 32 bytes (gerar com
    `python -m app.core.attestation`).
    """
    value = raw if raw is not None else get_settings().platform_ed25519_private_key
    if not value:
        raise AttestationError(
            "PLATFORM_ED25519_PRIVATE_KEY não está configurada; "
            "a emissão de attestations está desabilitada"
        )
    try:
        seed = base64.b64decode(value, validate=True)
        return Ed25519PrivateKey.from_private_bytes(seed)
    except Exception as exc:  # pragma: no cover - mensagem única
        raise AttestationError(
            "PLATFORM_ED25519_PRIVATE_KEY inválida: esperada seed de 32 bytes "
            f"em base64 ({type(exc).__name__})"
        ) from exc


def public_key_info(private_key: Optional[Ed25519PrivateKey] = None) -> Dict[str, str]:
    """Retorna a chave pública (base64) e o key_id derivado dela."""
    key = private_key or load_private_key()
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_bytes).decode("ascii")
    key_id = canonical_hash({"ed25519_public_key": public_b64})[:16]
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "public_key_b64": public_b64,
        "key_id": key_id,
    }


def _sign(payload: Dict[str, Any], private_key: Ed25519PrivateKey) -> Dict[str, Any]:
    body = dict(payload)
    body["attestation_hash"] = canonical_hash(body)
    signature = private_key.sign(canonical_json(body).encode("utf-8"))
    return {
        **body,
        "signature": base64.b64encode(signature).decode("ascii"),
        "signature_algorithm": SIGNATURE_ALGORITHM,
    }


def verify_attestation(
    attestation: Dict[str, Any],
    public_key_b64: Optional[str] = None,
) -> Tuple[bool, Dict[str, bool]]:
    """Verificação stateless: hash interno + assinatura Ed25519.

    Retorna (valid, {"hash_valid": ..., "signature_valid": ...}).
    """
    unsigned = {
        key: value
        for key, value in attestation.items()
        if key not in _SIGNATURE_FIELDS
    }
    declared_hash = unsigned.pop("attestation_hash", None)
    hash_valid = declared_hash == canonical_hash(unsigned)

    signature_valid = False
    try:
        if public_key_b64:
            public_bytes = base64.b64decode(public_key_b64, validate=True)
            public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        else:
            public_key = load_private_key().public_key()
        signed_body = {**unsigned, "attestation_hash": declared_hash}
        signature = base64.b64decode(attestation.get("signature", ""), validate=True)
        public_key.verify(signature, canonical_json(signed_body).encode("utf-8"))
        signature_valid = True
    except Exception:
        signature_valid = False

    return hash_valid and signature_valid, {
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
    }


def _outcome_split(decision: Dict[str, Any]) -> Dict[str, int]:
    outcome = decision.get("outcome")
    if outcome == "claimant":
        return {"claimant_bps": 10000, "respondent_bps": 0}
    if outcome == "respondent":
        return {"claimant_bps": 0, "respondent_bps": 10000}
    if outcome == "partial":
        claimant_bps = decision.get("partial_claimant_bps")
        if claimant_bps is None or not 0 <= int(claimant_bps) <= 10000:
            raise AttestationError(
                "Decisão parcial sem partial_claimant_bps válido: "
                "a attestation executável não pode ser emitida"
            )
        claimant_bps = int(claimant_bps)
        return {
            "claimant_bps": claimant_bps,
            "respondent_bps": 10000 - claimant_bps,
        }
    raise AttestationError(
        f"Outcome '{outcome}' não é executável; attestation não emitida"
    )


def assert_executable(decision: Dict[str, Any], review: Dict[str, Any]) -> None:
    """Pré-condições de mérito para uma attestation executável."""
    if not decision:
        raise AttestationError("O caso ainda não tem decisão")
    if not review:
        raise AttestationError("A decisão ainda não passou pela auditoria independente")
    if decision.get("execution", {}).get("mode") == "safe_fallback":
        raise AttestationError(
            "Decisão produzida em modo seguro não gera attestation executável"
        )
    if review.get("execution", {}).get("mode") == "safe_fallback":
        raise AttestationError(
            "Auditoria em modo seguro não valida a decisão para execução"
        )
    if decision.get("outcome") == "inconclusive":
        raise AttestationError("Decisão inconclusiva não gera attestation executável")
    if not review.get("approved"):
        raise AttestationError(
            "A auditoria independente não aprovou a decisão; execução bloqueada"
        )
    if decision.get("requires_human_review") or review.get("requires_human_review"):
        raise AttestationError(
            "O caso requer revisão humana antes de qualquer execução automática"
        )


def build_decision_attestation(
    case_data: Dict[str, Any],
    audit_chain_head: str,
    audit_chain_length: int,
    private_key: Optional[Ed25519PrivateKey] = None,
) -> Dict[str, Any]:
    """Monta e assina a attestation de execução para um caso decidido,
    auditado e aprovado. Levanta AttestationError se as pré-condições
    não forem atendidas.
    """
    settings = get_settings()
    decision = case_data.get("decision") or {}
    review = case_data.get("review") or {}
    manifest = case_data.get("locked_manifest") or {}

    if not manifest:
        raise AttestationError("O manifesto ainda não foi travado")
    assert_executable(decision, review)
    split = _outcome_split(decision)

    key = private_key or load_private_key()
    key_info = public_key_info(key)

    issued_at = datetime.now(timezone.utc)
    contest_window_ends = issued_at + timedelta(days=settings.contest_window_days)

    payload = {
        "attestation_version": ATTESTATION_VERSION,
        "attestation_type": "decision_execution",
        "case_id": case_data.get("id"),
        "escrow_id": case_data.get("escrow_id"),
        "manifest_hash": manifest.get("manifest_hash"),
        "audit_chain_head": audit_chain_head,
        "audit_chain_length": audit_chain_length,
        "decision": {
            "outcome": decision.get("outcome"),
            "split": split,
            "decision_hash": canonical_hash(decision),
            "confidence": decision.get("confidence"),
        },
        "review": {
            "approved": review.get("approved"),
            "requires_human_review": review.get("requires_human_review"),
            "review_hash": canonical_hash(review),
        },
        "issued_at_utc": issued_at.isoformat(),
        "contest_window_ends_utc": contest_window_ends.isoformat(),
        "platform": {
            "name": "Valinor",
            "platform_version": manifest.get("platform_version"),
            "procedure_version": manifest.get("procedure_version"),
            "key_id": key_info["key_id"],
        },
    }
    return _sign(payload, key)


def generate_private_key_b64() -> str:
    """Gera uma nova seed Ed25519 em base64 para PLATFORM_ED25519_PRIVATE_KEY."""
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(seed).decode("ascii")


if __name__ == "__main__":
    print(generate_private_key_b64())
