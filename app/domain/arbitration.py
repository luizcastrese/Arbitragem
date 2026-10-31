"""Árbitro pessoa física e assinatura da sentença arbitral.

A lei não admite IA como árbitra: o árbitro é pessoa capaz que tem a confiança
das partes (Lei 9.307/96, art. 13), nomeada no compromisso (art. 10, II), com o
dever de revelar o que comprometa sua imparcialidade (art. 14, §1º), e a
sentença é assinada por ele (art. 26). Este módulo modela esse percurso sem
tocar no mérito:

1. uma parte convida o árbitro (convite com papel ``arbitrator``);
2. o árbitro aceita a nomeação, se qualifica e declara independência,
   revelando o que houver;
3. cada parte confirma *aquele* árbitro, com *aquela* declaração (hash);
4. tudo isso antes da trava, para o manifesto congelar a designação;
5. com a decisão da IA final (auditada, sem recurso pendente, prazo de recurso
   encerrado), o árbitro **adota e assina** a decisão como sentença arbitral ou
   **recusa** adotá-la. Ele não reescreve a decisão aqui dentro.

A designação vive em ``pathway["arbitrator"]``. A assinatura, como a saída para
a Justiça, é lida da trilha de auditoria, que é encadeada por hash.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.canonical import canonical_hash
from app.core.hashing import sha256_text

PARTIES = ("claimant", "respondent")
ARBITRATOR_ROLE = "arbitrator"

# Primeira versão dos termos que prevê a designação e a assinatura eletrônica
# do árbitro na plataforma. A confirmação da parte exige aceite dela.
ARBITRATOR_SIGNATURE_TERMS_SINCE = "2026-11-02"

AWARD_SIGNED_EVENT = "arbitral_award_signed"
AWARD_DECLINED_EVENT = "arbitral_award_declined"


class ArbitrationError(ValueError):
    """Ato inválido no percurso do árbitro. A mensagem vai para o usuário."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def arbitrator_identity_hash(arbitrator: Dict[str, Any]) -> str:
    """O que cada parte confirma: quem é o árbitro e o que ele revelou."""
    return canonical_hash(
        {
            "user_id": arbitrator.get("user_id"),
            "display_name": arbitrator.get("display_name"),
            "tax_id": arbitrator.get("tax_id"),
            "qualification": arbitrator.get("qualification"),
            "disclosure_sha256": arbitrator.get("disclosure_sha256"),
        }
    )


def record_acceptance(
    pathway: Dict[str, Any],
    *,
    user_id: str,
    display_name: str,
    tax_id: str,
    qualification: str,
    disclosure: str,
) -> Dict[str, Any]:
    """O árbitro aceita a nomeação. Aceitar de novo zera as confirmações:
    as partes confirmam a declaração vigente, não uma anterior."""
    updated = dict(pathway)
    arbitrator = {
        "user_id": user_id,
        "display_name": display_name,
        "tax_id": tax_id,
        "qualification": qualification,
        "independence_declared": True,
        "disclosure": disclosure,
        "disclosure_sha256": sha256_text(disclosure or ""),
        "accepted_at": _now(),
        "confirmations": {},
    }
    arbitrator["identity_sha256"] = arbitrator_identity_hash(arbitrator)
    updated["arbitrator"] = arbitrator
    return updated


def record_confirmation(
    pathway: Dict[str, Any], *, party: str, terms_version: str
) -> Dict[str, Any]:
    if party not in PARTIES:
        raise ArbitrationError("Parte desconhecida.")
    arbitrator = dict(pathway.get("arbitrator") or {})
    if not arbitrator.get("accepted_at"):
        raise ArbitrationError("O árbitro ainda não aceitou a nomeação.")
    if (terms_version or "") < ARBITRATOR_SIGNATURE_TERMS_SINCE:
        raise ArbitrationError(
            "Confirmar o árbitro exige o aceite dos termos vigentes, que "
            "preveem a assinatura eletrônica da sentença. Aceite-os de novo."
        )
    confirmations = dict(arbitrator.get("confirmations") or {})
    confirmations[party] = {
        "confirmed_at": _now(),
        "identity_sha256": arbitrator.get("identity_sha256"),
        "terms_version": terms_version,
    }
    arbitrator["confirmations"] = confirmations
    updated = dict(pathway)
    updated["arbitrator"] = arbitrator
    return updated


def arbitrator_designated(pathway: Optional[Dict[str, Any]]) -> bool:
    """Árbitro aceito e confirmado pelas duas partes na mesma declaração."""
    arbitrator = (pathway or {}).get("arbitrator") or {}
    identity = arbitrator.get("identity_sha256")
    if not (arbitrator.get("accepted_at") and identity):
        return False
    confirmations = arbitrator.get("confirmations") or {}
    return all(
        (confirmations.get(party) or {}).get("identity_sha256") == identity
        for party in PARTIES
    )


def public_arbitrator(pathway: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    arbitrator = (pathway or {}).get("arbitrator")
    if not arbitrator:
        return None
    return {
        "user_id": arbitrator.get("user_id"),
        "display_name": arbitrator.get("display_name"),
        "tax_id": arbitrator.get("tax_id"),
        "qualification": arbitrator.get("qualification"),
        "disclosure": arbitrator.get("disclosure"),
        "accepted_at": arbitrator.get("accepted_at"),
        "confirmations": {
            party: (arbitrator.get("confirmations") or {}).get(party, {}).get("confirmed_at")
            for party in PARTIES
        },
        "designated": arbitrator_designated(pathway),
    }


def decision_is_final(
    case_data: Dict[str, Any], now: Optional[datetime] = None
) -> Tuple[bool, Optional[str]]:
    """A decisão só vai ao árbitro quando nada mais pode mudá-la aqui dentro."""
    now = now or datetime.now(timezone.utc)
    if (case_data.get("procedure_conclusion") or "") != "decided":
        return False, "Não há decisão de mérito para o árbitro assinar."
    verification = case_data.get("verification")
    if verification is not None and not verification.get("valid"):
        return False, "A decisão não passou na verificação determinística."
    appeals = case_data.get("appeals") or []
    if any(not item.get("completed_at") for item in appeals):
        return False, "Há recurso automático em andamento."
    attestation = case_data.get("attestation") or {}
    window = attestation.get("contest_window_ends_utc")
    if window and not appeals:
        ends = datetime.fromisoformat(window)
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        if now < ends:
            return False, "O prazo de recurso automático ainda está aberto."
    return True, None


def award_from_audit(audit_log) -> Optional[Dict[str, Any]]:
    """Assinatura ou recusa do árbitro, lida da trilha de auditoria."""
    for event in reversed(audit_log or []):
        kind = event.get("event_type")
        if kind in {AWARD_SIGNED_EVENT, AWARD_DECLINED_EVENT}:
            payload = event.get("payload") or {}
            return {
                **payload,
                "adopted": kind == AWARD_SIGNED_EVENT,
                "recorded_at": event.get("timestamp_utc"),
            }
    return None
