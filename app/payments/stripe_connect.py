"""Stripe Connect destination charge para cumprimento voluntário da decisão."""

from typing import Any, Dict


class PaymentProviderError(RuntimeError):
    pass


def create_checkout_session(
    *, attestation: Dict[str, Any], connected_account_id: str,
    success_url: str, cancel_url: str, idempotency_key: str, stripe_client=None,
) -> Dict[str, str]:
    payment = attestation.get("payment") or {}
    required = ("total_charge_minor_units", "platform_fee_minor_units", "currency")
    if any(not payment.get(field) for field in required):
        raise PaymentProviderError("Attestation sem instrução de pagamento válida")
    if not connected_account_id.startswith("acct_"):
        raise PaymentProviderError("Conta Stripe Connect inválida")
    if stripe_client is None:
        import stripe
        stripe_client = stripe
    session = stripe_client.checkout.Session.create(
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=attestation.get("case_id"),
        line_items=[{"price_data": {
            "currency": payment["currency"].lower(),
            "unit_amount": payment["total_charge_minor_units"],
            "product_data": {"name": "Cumprimento de decisão Valinor"},
        }, "quantity": 1}],
        payment_intent_data={
            "application_fee_amount": payment["platform_fee_minor_units"],
            "transfer_data": {"destination": connected_account_id},
            "metadata": {"attestation_hash": attestation["attestation_hash"]},
        },
        metadata={"case_id": attestation.get("case_id"), "attestation_hash": attestation["attestation_hash"]},
        idempotency_key=idempotency_key,
    )
    return {"provider": "stripe_connect", "session_id": session.id, "checkout_url": session.url}
