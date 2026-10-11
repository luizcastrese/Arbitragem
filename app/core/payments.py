"""Cliente Stripe do pagamento opcional da decisão (Connect + Checkout).

O modelo é o de cobrança com destino (destination charge): a parte devedora
paga uma sessão de Checkout, o Stripe repassa o valor à conta Connect da parte
credora e retém a `application_fee_amount` para a plataforma. A plataforma não
custodia o dinheiro.

Toda chamada passa por funções deste módulo, para os testes trocarem a
fronteira de rede sem tocar na regra de negócio.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import stripe

from app.core.config import get_settings

CONNECT_COUNTRY = "BR"
CHECKOUT_TTL_SECONDS = 24 * 3600


class PaymentsUnavailable(RuntimeError):
    """Stripe não configurado nesta instância."""


class PaymentsError(RuntimeError):
    """Falha devolvida pelo Stripe."""


def _client() -> "stripe.StripeClient":
    settings = get_settings()
    if not settings.payments_enabled:
        raise PaymentsUnavailable("pagamentos não configurados")
    return stripe.StripeClient(settings.stripe_secret_key)


def _wrap(call):
    try:
        return call()
    except stripe.StripeError as exc:
        raise PaymentsError(getattr(exc, "user_message", None) or str(exc)) from exc


def create_connect_account(email: str, user_id: str) -> str:
    client = _client()
    account = _wrap(
        lambda: client.accounts.create(
            params={
                "type": "express",
                "country": CONNECT_COUNTRY,
                "email": email,
                "capabilities": {"transfers": {"requested": True}},
                "metadata": {"user_id": user_id},
            },
            options={"idempotency_key": f"connect-account-{user_id}"},
        )
    )
    return account.id


def create_onboarding_link(account_id: str, refresh_url: str, return_url: str) -> str:
    client = _client()
    link = _wrap(
        lambda: client.account_links.create(
            params={
                "account": account_id,
                "refresh_url": refresh_url,
                "return_url": return_url,
                "type": "account_onboarding",
            }
        )
    )
    return link.url


def account_ready(account_id: str) -> bool:
    """A conta pode receber repasses (cadastro concluído e transfers ativo)."""
    client = _client()
    account = _wrap(lambda: client.accounts.retrieve(account_id))
    capabilities = getattr(account, "capabilities", None) or {}
    return bool(
        getattr(account, "details_submitted", False)
        and capabilities.get("transfers") == "active"
    )


def create_checkout_session(
    *,
    payment_id: str,
    case_id: str,
    attestation_hash: str,
    title: str,
    amount_minor_units: int,
    fee_minor_units: int,
    currency: str,
    destination_account_id: str,
    customer_email: Optional[str],
    success_url: str,
    cancel_url: str,
) -> Tuple[str, str]:
    client = _client()
    metadata = {
        "payment_id": payment_id,
        "case_id": case_id,
        "attestation_hash": attestation_hash,
    }
    params: Dict[str, Any] = {
        "mode": "payment",
        "client_reference_id": payment_id,
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": currency.lower(),
                    "unit_amount": amount_minor_units,
                    "product_data": {
                        "name": f"Pagamento voluntário da decisão — {title}"[:250]
                    },
                },
            }
        ],
        "payment_intent_data": {
            "application_fee_amount": fee_minor_units,
            "transfer_data": {"destination": destination_account_id},
            "metadata": metadata,
        },
        "metadata": metadata,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if customer_email:
        params["customer_email"] = customer_email
    session = _wrap(
        lambda: client.checkout.sessions.create(
            params=params,
        )
    )
    return session.id, session.url


def retrieve_checkout_session(session_id: str) -> Dict[str, Any]:
    client = _client()
    session = _wrap(lambda: client.checkout.sessions.retrieve(session_id))
    return {"id": session.id, "status": session.status, "url": session.url}


def construct_event(payload: bytes, signature: str) -> Dict[str, Any]:
    """Valida a assinatura do webhook. Levanta `ValueError` se for inválida."""
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise PaymentsUnavailable("webhook não configurado")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise ValueError("assinatura do webhook inválida") from exc
    return event.to_dict() if hasattr(event, "to_dict") else dict(event)
