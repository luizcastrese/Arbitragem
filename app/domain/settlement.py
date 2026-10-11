"""Oferta de pagamento opcional da decisão.

O pagamento não é execução da decisão: é uma saída que a parte devedora pode
escolher para encerrar o litígio. Este módulo só decide, de forma
determinística, se existe uma oferta, de quanto e entre quem. Não fala com o
Stripe e não grava nada.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.config import get_settings

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


def settlement_offer(
    case_data: Dict[str, Any], now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Calcula a oferta a partir do caso serializado (`case_to_dict`).

    Só há oferta quando a decisão é de mérito, verificada, atestada, favorável
    ao reclamante com valor calculado, e a fase de contestação terminou.
    """
    now = now or datetime.now(timezone.utc)
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
    window_ends = _parse_utc(attestation.get("contest_window_ends_utc"))
    window_open = window_ends is None or now < window_ends
    if window_open and not appeals:
        return _unavailable(
            "contest_window_open",
            opens_at=window_ends.isoformat() if window_ends else None,
        )

    fee = platform_fee(amount)
    return {
        "available": True,
        "reason": None,
        "attestation_hash": records[-1]["attestation_hash"],
        "payer_role": PAYER_ROLE,
        "payee_role": PAYEE_ROLE,
        "amount_minor_units": amount,
        "platform_fee_minor_units": fee,
        "net_to_payee_minor_units": amount - fee,
        "currency": currency,
        "voluntary": True,
    }
