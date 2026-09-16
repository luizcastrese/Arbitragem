"""Decision Attestation: artefato assinado (Ed25519) que executores externos
(instituição de pagamento ou contrato inteligente) consomem para liberar o
escrow conforme a decisão do procedimento.

A attestation referencia o manifest_hash, o topo da cadeia de auditoria e os
hashes da decisão e da revisão, tornando-a verificável offline com a chave
pública da plataforma.
"""

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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


def key_id_for(public_b64: str) -> str:
    """key_id determinístico derivado da chave pública."""
    return canonical_hash({"ed25519_public_key": public_b64})[:16]


def public_key_info(private_key: Optional[Ed25519PrivateKey] = None) -> Dict[str, str]:
    """Retorna a chave pública (base64) e o key_id derivado dela."""
    key = private_key or load_private_key()
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_bytes).decode("ascii")
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "public_key_b64": public_b64,
        "key_id": key_id_for(public_b64),
    }


def retired_public_keys() -> List[Dict[str, str]]:
    """Chaves públicas aposentadas, ainda aceitas na verificação.

    Rotacionar a chave de assinatura não pode invalidar as attestations já
    emitidas: elas continuam sendo verificadas contra a chave que as assinou.
    A chave privada correspondente não fica mais no ambiente — só a pública,
    em ``PLATFORM_ED25519_RETIRED_PUBLIC_KEYS``.
    """
    entries: List[Dict[str, str]] = []
    seen = set()
    for raw in get_settings().platform_ed25519_retired_public_keys:
        public_b64 = raw.strip()
        if not public_b64 or public_b64 in seen:
            continue
        try:
            decoded = base64.b64decode(public_b64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise AttestationError(
                "PLATFORM_ED25519_RETIRED_PUBLIC_KEYS contém um valor que não "
                f"é base64: {public_b64[:12]}..."
            ) from exc
        if len(decoded) != 32:
            raise AttestationError(
                "PLATFORM_ED25519_RETIRED_PUBLIC_KEYS espera chaves públicas "
                f"Ed25519 de 32 bytes; recebi {len(decoded)}."
            )
        seen.add(public_b64)
        entries.append(
            {
                "algorithm": SIGNATURE_ALGORITHM,
                "public_key_b64": public_b64,
                "key_id": key_id_for(public_b64),
                "status": "retired",
            }
        )
    return entries


def key_set() -> Dict[str, Any]:
    """Conjunto de chaves publicado: a ativa mais as aposentadas."""
    active = None
    if get_settings().attestation_enabled:
        active = {**public_key_info(), "status": "active"}
    retired = retired_public_keys()
    keys = ([active] if active else []) + retired
    return {"active": active, "retired": retired, "keys": keys}


def _verification_candidates() -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    try:
        candidates.append({**public_key_info(), "status": "active"})
    except AttestationError:
        pass
    try:
        candidates.extend(retired_public_keys())
    except AttestationError:
        pass
    return candidates


def _sign(payload: Dict[str, Any], private_key: Ed25519PrivateKey) -> Dict[str, Any]:
    body = dict(payload)
    body["attestation_hash"] = canonical_hash(body)
    signature = private_key.sign(canonical_json(body).encode("utf-8"))
    return {
        **body,
        "signature": base64.b64encode(signature).decode("ascii"),
        "signature_algorithm": SIGNATURE_ALGORITHM,
    }


def _signature_matches(
    public_b64: str,
    signed_body: Dict[str, Any],
    signature_b64: str,
) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_b64, validate=True)
        )
        public_key.verify(
            base64.b64decode(signature_b64, validate=True),
            canonical_json(signed_body).encode("utf-8"),
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def verify_attestation(
    attestation: Dict[str, Any],
    public_key_b64: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Verificação stateless: hash interno + assinatura Ed25519.

    Sem chave informada, a assinatura é conferida contra o conjunto de chaves
    da plataforma — a ativa e as aposentadas. É isso que mantém verificável
    uma attestation emitida antes de uma rotação. O `key_id` que fechou a
    verificação volta no resultado.

    Retorna (valid, {"hash_valid", "signature_valid", "key_id", "key_status"}).
    """
    unsigned = {
        key: value
        for key, value in attestation.items()
        if key not in _SIGNATURE_FIELDS
    }
    declared_hash = unsigned.pop("attestation_hash", None)
    hash_valid = declared_hash == canonical_hash(unsigned)

    signed_body = {**unsigned, "attestation_hash": declared_hash}
    signature_b64 = attestation.get("signature", "") or ""

    if public_key_b64:
        candidates = [
            {
                "public_key_b64": public_key_b64,
                "key_id": key_id_for(public_key_b64),
                "status": "provided",
            }
        ]
    else:
        candidates = _verification_candidates()

    matched: Optional[Dict[str, str]] = None
    for candidate in candidates:
        if _signature_matches(
            candidate["public_key_b64"], signed_body, signature_b64
        ):
            matched = candidate
            break

    signature_valid = matched is not None
    return hash_valid and signature_valid, {
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
        "key_id": matched["key_id"] if matched else None,
        "key_status": matched["status"] if matched else None,
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


def assert_executable(
    decision: Dict[str, Any],
    review: Dict[str, Any],
    verification: Optional[Dict[str, Any]] = None,
    stability: Optional[Dict[str, Any]] = None,
    procedure_conclusion: Optional[str] = None,
) -> None:
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
    approved = review.get("approved")
    if approved is None:
        approved = review.get("outcome") == "approved"
    if not approved:
        raise AttestationError(
            "A auditoria independente não aprovou a decisão; execução bloqueada"
        )
    # Compatibilidade de leitura: registros antigos com este campo continuam
    # bloqueados. Novas decisões não o produzem.
    if decision.get("requires_human_review") or review.get("requires_human_review"):
        raise AttestationError(
            "O caso requer revisão humana antes de qualquer execução automática"
        )
    if procedure_conclusion and procedure_conclusion != "decided":
        raise AttestationError(
            f"Conclusão '{procedure_conclusion}' não gera attestation executável"
        )
    if verification is not None and not verification.get("valid"):
        raise AttestationError(
            "A verificação determinística não validou a decisão; attestation bloqueada"
        )
    if stability is not None and stability.get("stable") is False:
        raise AttestationError(
            "A decisão não passou no teste de estabilidade; attestation bloqueada"
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
    verification = case_data.get("verification")
    stability = case_data.get("stability")
    procedure_conclusion = case_data.get("procedure_conclusion") or decision.get(
        "procedure_conclusion"
    )
    assert_executable(
        decision,
        review,
        verification=verification,
        stability=stability,
        procedure_conclusion=procedure_conclusion,
    )
    split = _outcome_split(decision)

    key = private_key or load_private_key()
    key_info = public_key_info(key)

    issued_at = datetime.now(timezone.utc)
    contest_window_ends = issued_at + timedelta(days=settings.contest_window_days)
    provenance = decision.get("provenance") or {}
    previous = case_data.get("previous_attestation") or {}

    payload = {
        "attestation_version": ATTESTATION_VERSION,
        "attestation_schema_version": "2.0",
        "hash_algorithm": "sha256",
        "canonicalization_version": "1.0",
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
            "decision_payload_hash": provenance.get("decision_payload_hash"),
            "decision_input_hash": provenance.get("decision_input_hash"),
            "confidence": decision.get("confidence"),
            "execution_id": (decision.get("execution") or {}).get("execution_id"),
        },
        "review": {
            "approved": bool(review.get("approved") or review.get("outcome") == "approved"),
            "outcome": review.get("outcome") or (
                "approved" if review.get("approved") else "rejected"
            ),
            "review_hash": canonical_hash(review),
        },
        "verification": {
            "valid": None if verification is None else bool(verification.get("valid")),
            "verification_result_hash": provenance.get("verification_result_hash")
            or (verification or {}).get("result_hash"),
        },
        "stability": {
            "required": bool((manifest.get("model_policy") or {}).get("stability", {}).get("enabled")),
            "stable": None if stability is None else bool(stability.get("stable")),
        },
        "appeal": {
            "id": (case_data.get("current_appeal") or {}).get("id"),
            "outcome": (case_data.get("current_appeal") or {}).get("outcome"),
            "result_hash": (case_data.get("current_appeal") or {}).get("result_hash"),
        },
        "supersedes_attestation_hash": previous.get("attestation_hash"),
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


def _rotation_plan() -> str:
    """Texto de apoio à rotação: a chave nova e o que fazer com a atual."""
    new_private = generate_private_key_b64()
    new_public = public_key_info(load_private_key(new_private))["public_key_b64"]
    lines = [
        "# Nova chave de assinatura",
        f"PLATFORM_ED25519_PRIVATE_KEY={new_private}",
        "",
        "# Guarde a chave privada no cofre ANTES de trocar o ambiente.",
        f"# Chave pública correspondente (key_id {key_id_for(new_public)}):",
        f"#   {new_public}",
    ]
    try:
        current = public_key_info()
    except AttestationError:
        lines += [
            "",
            "# Não há chave ativa configurada: nada a aposentar.",
        ]
        return "\n".join(lines)

    retired = [item["public_key_b64"] for item in retired_public_keys()]
    retired_value = ",".join([current["public_key_b64"], *retired])
    lines += [
        "",
        "# Acrescente a chave atual às aposentadas para que as attestations",
        f"# já emitidas (key_id {current['key_id']}) continuem verificáveis:",
        f"PLATFORM_ED25519_RETIRED_PUBLIC_KEYS={retired_value}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if "--rotate" in sys.argv:
        print(_rotation_plan())
    else:
        print(generate_private_key_b64())
