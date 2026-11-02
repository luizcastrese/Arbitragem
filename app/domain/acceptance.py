"""Acatamento bilateral da decisão da IA como acordo.

A decisão da IA não obriga ninguém. Sem árbitro humano ela é decisão
fundamentada não vinculante, mas as partes podem **adotá-la como seu acordo**:
cada uma acata, por ato próprio, aquela decisão (aquela attestation). Quando as
duas acatam, o que a IA formulou passa a valer como transação entre elas
(Código Civil, art. 840), nos exatos termos da decisão, sem sentença arbitral e
sem árbitro. Este módulo modela esse percurso sem tocar no mérito:

1. depois do aviso da decisão (attestation) e de um **prazo de reflexão**, cada
   parte acata individualmente, declarando ter lido a decisão e ciente de que o
   ato é irrevogável;
2. o acatamento fica preso ao hash da attestation. Se um recurso corrigir a
   decisão, a attestation muda e os acatamentos anteriores deixam de valer;
3. com as duas partes, a decisão vale como acordo: o auto é reemitido com esse
   efeito e o pagamento opcional não espera mais o prazo de recurso;
4. acatamento e sentença arbitral são desfechos excludentes: vale o que se
   completar primeiro, e quem acatou não recorre.

O acatamento vive na trilha de auditoria (evento ``decision_accepted``),
encadeada por hash, como a assinatura do árbitro e a saída para a Justiça.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.hashing import sha256_text

PARTIES = ("claimant", "respondent")

ACCEPTED_EVENT = "decision_accepted"

STATEMENT_VERSION = "1"

# O que a parte lê e confirma. O hash deste texto entra no evento de auditoria:
# prova depois o que foi exibido quando ela acatou. Texto publicado não se
# edita; uma mudança é uma versão nova, com ``STATEMENT_VERSION`` novo.
STATEMENT = (
    "Li a decisão proferida neste procedimento, com o raciocínio e os cálculos "
    "que a fundamentam, e a adoto, por livre vontade, como proposta de acordo "
    "que aceito nos seus exatos termos. Estou ciente de que: "
    "(1) a decisão foi elaborada por inteligência artificial e, sem a "
    "assinatura de um árbitro, não é sentença arbitral nem judicial; "
    "(2) se a outra parte também a acatar, a decisão passa a valer como acordo "
    "entre nós (transação, Código Civil, art. 840), que encerra o conflito nos "
    "termos nela fixados; "
    "(3) este ato é irrevogável e, depois dele, não poderei recorrer da "
    "decisão; "
    "(4) eu poderia, sem qualquer prejuízo, não acatar e seguir pela via "
    "judicial ou aguardar o fim do prazo de recurso."
)
STATEMENT_SHA256 = sha256_text(STATEMENT)

DEFAULT_REFLECTION_HOURS = 24


class AcceptanceError(ValueError):
    """Acatamento inválido. A mensagem vai para o usuário."""


def _parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def current_attestation_hash(case_data: Dict[str, Any]) -> Optional[str]:
    """Hash da attestation vigente, a decisão que as partes acatam."""
    attestation = case_data.get("attestation") or {}
    if attestation.get("attestation_hash"):
        return attestation["attestation_hash"]
    records = case_data.get("attestation_records") or []
    return records[-1].get("attestation_hash") if records else None


def acceptances_from_audit(audit_log: Any) -> List[Dict[str, Any]]:
    """Acatamentos lidos da trilha, do mais antigo para o mais novo."""
    found: List[Dict[str, Any]] = []
    for event in audit_log or []:
        if event.get("event_type") != ACCEPTED_EVENT:
            continue
        found.append({**(event.get("payload") or {}), "recorded_at": event.get("timestamp_utc")})
    return found


def acceptance_status(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Quem acatou a decisão vigente. Acatamento de decisão superada não conta."""
    attestation_hash = current_attestation_hash(case_data)
    parties: Dict[str, Optional[Dict[str, Any]]] = {party: None for party in PARTIES}
    if attestation_hash:
        for item in case_data.get("decision_acceptances") or []:
            party = item.get("party")
            if (
                party in parties
                and parties[party] is None
                and item.get("attestation_hash") == attestation_hash
            ):
                parties[party] = item
    return {
        "attestation_hash": attestation_hash,
        "parties": parties,
        "complete": all(parties.values()),
        "any": any(parties.values()),
        "statement_version": STATEMENT_VERSION,
    }


def reflection_ends_at(
    case_data: Dict[str, Any], reflection_hours: int = DEFAULT_REFLECTION_HOURS
) -> Optional[datetime]:
    issued = _parse_utc((case_data.get("attestation") or {}).get("issued_at_utc"))
    if issued is None:
        return None
    return issued + timedelta(hours=reflection_hours)


def eligibility(
    case_data: Dict[str, Any],
    *,
    reflection_hours: int = DEFAULT_REFLECTION_HOURS,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Se a decisão vigente pode ser acatada agora: (pode, código, motivo)."""
    now = now or datetime.now(timezone.utc)
    status = str(case_data.get("status") or "")
    if status == "withdrawn":
        return False, "withdrawn", "O caso foi encerrado pela opção pela via judicial."
    if status.startswith("processing"):
        return False, "stage_running", "Há uma etapa em andamento. Aguarde a conclusão dela."
    if not current_attestation_hash(case_data):
        return False, "attestation_not_issued", "A decisão ainda não foi atestada."
    decision = case_data.get("decision") or {}
    if (
        (case_data.get("procedure_conclusion") or "") != "decided"
        or decision.get("outcome") == "inconclusive"
    ):
        return False, "no_merit_decision", "Não há decisão de mérito para acatar."
    verification = case_data.get("verification")
    if verification is not None and not verification.get("valid"):
        return False, "decision_not_verified", "A decisão não passou na verificação determinística."
    appeals = case_data.get("appeals") or []
    contested = (case_data.get("contest") or {}).get("contested")
    if any(not item.get("completed_at") for item in appeals) or (
        contested and not appeals
    ):
        return False, "appeal_pending", "Há recurso automático em andamento."
    award = case_data.get("arbitral_award") or {}
    if award.get("adopted"):
        return (
            False,
            "arbitral_award_signed",
            "O árbitro já adotou e assinou a decisão como sentença arbitral.",
        )
    ends = reflection_ends_at(case_data, reflection_hours)
    if ends is None:
        return False, "attestation_without_date", "A attestation não informa a data de emissão."
    if now < ends:
        return (
            False,
            "reflection_period",
            "O acatamento só é possível depois do prazo de reflexão, que termina "
            f"em {ends.isoformat()}.",
        )
    return True, None, None


def public_state(
    case_data: Dict[str, Any],
    *,
    reflection_hours: int = DEFAULT_REFLECTION_HOURS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Estado do acatamento para as partes: o que já foi feito e o que falta."""
    status = acceptance_status(case_data)
    can, code, reason = eligibility(case_data, reflection_hours=reflection_hours, now=now)
    ends = reflection_ends_at(case_data, reflection_hours)
    return {
        "attestation_hash": status["attestation_hash"],
        "can_accept": can,
        "blocked_code": code,
        "blocked_reason": reason,
        "reflection_ends_utc": ends.isoformat() if ends else None,
        "parties": {
            party: (
                {
                    "accepted_at": item.get("recorded_at"),
                    "statement_sha256": item.get("statement_sha256"),
                }
                if item
                else None
            )
            for party, item in status["parties"].items()
        },
        "complete": status["complete"],
        "statement": {
            "version": STATEMENT_VERSION,
            "text": STATEMENT,
            "sha256": STATEMENT_SHA256,
        },
    }
