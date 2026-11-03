"""Oferta de pagamento opcional da decisão ou do acordo.

O pagamento não é execução da decisão: é uma saída que a parte devedora pode
escolher para encerrar o litígio. Este módulo só decide, de forma
determinística, se existe uma oferta, de quanto e entre quem. Não fala com o
Stripe e não grava nada.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.domain.acceptance import acceptance_status

# Decisões que reconhecem valor a favor do reclamante. Quando o reclamado
# vence, nada é devido: o sistema não modela pedido contraposto.
PAYABLE_OUTCOMES = {"claimant", "partial"}
PAYER_ROLE = "respondent"
PAYEE_ROLE = "claimant"

# Estados que impedem uma nova cobrança do mesmo valor.
SETTLED_STATUSES = {"paid"}


def platform_fee(amount_minor_units: int, fee_bps: Optional[int] = None) -> int:
    """Taxa da plataforma em minor units, arredondada para baixo.

    A taxa incide sobre o valor pago (application fee do Stripe Connect): a
    parte credora recebe `amount - fee`, descontadas as tarifas do Stripe,
    que a plataforma absorve.
    """
    bps = get_settings().platform_fee_bps if fee_bps is None else fee_bps
    return (int(amount_minor_units) * int(bps)) // 10000


def _parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _unavailable(reason: str, **extra: Any) -> Dict[str, Any]:
    return {"available": False, "reason": reason, **extra}


def _agreement_offer(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Oferta de pagamento de um acordo bilateral que tem memória de cálculo.

    O valor é o da proposta que as duas partes aceitaram (o `scenario` da
    memória, calculado pelo módulo determinístico, nunca um texto da IA). Quem
    paga é a parte que não é a consumidora; quem recebe, a consumidora. A chave
    da cobrança é o hash da proposta aceita, que faz as vezes da attestation.
    """
    agreed = next(
        (
            item
            for item in case_data.get("conciliation_rounds") or []
            if (item.get("agreement") or {}).get("complete")
        ),
        None,
    )
    if agreed is None:
        return _unavailable("no_agreement")
    calculation = agreed.get("calculation") or {}
    scenario = calculation.get("scenario") or {}
    amount = scenario.get("amount_minor")
    if (
        calculation.get("status") != "ready"
        or isinstance(amount, bool)
        or not isinstance(amount, int)
        or amount <= 0
    ):
        return _unavailable("no_verified_amount")
    consumer = (case_data.get("pathway") or {}).get("consumer_party") or PAYEE_ROLE
    payee = consumer if consumer in ("claimant", "respondent") else PAYEE_ROLE
    payer = "respondent" if payee == "claimant" else "claimant"
    fee = platform_fee(amount)
    return {
        "available": True,
        "reason": None,
        "kind": "agreement",
        "attestation_hash": agreed["agreement"]["proposal_sha256"],
        "calculation_sha256": calculation.get("sha256"),
        "payer_role": payer,
        "payee_role": payee,
        "amount_minor_units": amount,
        "platform_fee_minor_units": fee,
        "net_to_payee_minor_units": amount - fee,
        "currency": "BRL",
        "voluntary": True,
        "accepted_by_both_parties": True,
    }


def settlement_offer(
    case_data: Dict[str, Any], now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Calcula a oferta a partir do caso serializado (`case_to_dict`).

    Acordo bilateral com memória de cálculo gera a oferta do valor acordado;
    sem acordo, vale o caminho da decisão abaixo.

    Só há oferta quando a decisão é de mérito, verificada, atestada, favorável
    ao reclamante com valor calculado, e a fase de contestação terminou. Se as
    duas partes acataram a decisão como acordo, a fase de contestação não é
    esperada: ninguém mais vai recorrer.
    """
    now = now or datetime.now(timezone.utc)
    if (
        case_data.get("status") == "agreement"
        or case_data.get("procedure_conclusion") == "agreement"
    ):
        return _agreement_offer(case_data)
    decision = case_data.get("decision") or {}
    attestation = case_data.get("attestation") or {}
    records = case_data.get("attestation_records") or []

    if not attestation or not records:
        return _unavailable("attestation_not_issued")
    if case_data.get("procedure_conclusion") != "decided":
        return _unavailable("no_merit_decision")
    verification = case_data.get("verification")
    if verification is not None and not verification.get("valid"):
        return _unavailable("decision_not_verified")
    if decision.get("outcome") not in PAYABLE_OUTCOMES:
        return _unavailable("no_amount_owed")

    calculation = decision.get("remedy_calculation") or {}
    amount = calculation.get("result_minor_units")
    currency = (calculation.get("currency") or "").upper()
    if (
        isinstance(amount, bool)
        or not isinstance(amount, int)
        or amount <= 0
        or not currency
    ):
        return _unavailable("no_verified_amount")

    appeals = case_data.get("appeals") or []
    if any(not item.get("completed_at") for item in appeals):
        return _unavailable("appeal_pending")
    accepted = acceptance_status(case_data)["complete"]
    window_ends = _parse_utc(attestation.get("contest_window_ends_utc"))
    window_open = window_ends is None or now < window_ends
    if window_open and not appeals and not accepted:
        return _unavailable(
            "contest_window_open",
            opens_at=window_ends.isoformat() if window_ends else None,
        )

    fee = platform_fee(amount)
    return {
        "available": True,
        "reason": None,
        "kind": "decision",
        "attestation_hash": records[-1]["attestation_hash"],
        "payer_role": PAYER_ROLE,
        "payee_role": PAYEE_ROLE,
        "amount_minor_units": amount,
        "platform_fee_minor_units": fee,
        "net_to_payee_minor_units": amount - fee,
        "currency": currency,
        "voluntary": True,
        "accepted_by_both_parties": accepted,
    }
