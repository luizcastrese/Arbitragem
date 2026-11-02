"""Pagamento opcional da decisão (Stripe Connect e Checkout)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.common import (
    _case_or_404,
    _require_actor,
    _require_case_view,
    _require_verified_email,
    _session_user_or_401,
)
from app.core import payments as payments_gateway
from app.core.config import get_settings
from app.db.repository import append_audit, case_to_dict, get_case
from app.db.session import get_db
from app.db.settlement_repository import (
    get_payment,
    get_payment_by_session,
    member_user,
    new_payment,
    payment_to_dict,
)
from app.domain.settlement import settlement_offer

logger = logging.getLogger("valinor.request")
router = APIRouter()


# --- Pagamento opcional da decisão (Stripe Connect) ---------------------------
# A decisão não obriga ninguém. Estas rotas só dão à parte devedora um modo de
# pagar, por escolha própria, para encerrar o litígio: 90% chegam à credora e
# 10% ficam com a plataforma.


def _require_payments() -> None:
    if not get_settings().payments_enabled:
        raise HTTPException(
            status_code=503,
            detail="O pagamento opcional não está habilitado nesta instância",
        )


@router.post("/payments/connect/onboarding")
def start_connect_onboarding(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Cadastro da conta que receberá pagamentos. Cada pessoa o faz por si."""
    _require_payments()
    user = _session_user_or_401(db, x_session_token)
    _require_verified_email(user)
    base = get_settings().public_app_url
    try:
        if not user.stripe_account_id:
            user.stripe_account_id = payments_gateway.create_connect_account(
                user.email, user.id
            )
            db.commit()
        url = payments_gateway.create_onboarding_link(
            user.stripe_account_id,
            refresh_url=f"{base}/?connect=refresh",
            return_url=f"{base}/?connect=return",
        )
    except payments_gateway.PaymentsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"onboarding_url": url}


@router.get("/payments/connect/status")
def connect_status(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    user = _session_user_or_401(db, x_session_token)
    enabled = get_settings().payments_enabled
    ready = False
    if enabled and user.stripe_account_id:
        try:
            ready = payments_gateway.account_ready(user.stripe_account_id)
        except payments_gateway.PaymentsError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "payments_enabled": enabled,
        "has_account": bool(user.stripe_account_id),
        "ready": ready,
    }


@router.get("/cases/{case_id}/settlement")
def get_settlement(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    offer = settlement_offer(case_to_dict(case, include_content=False))
    payment = (
        get_payment(db, case.id, offer["attestation_hash"])
        if offer["available"]
        else None
    )
    payee = member_user(db, case.id, "claimant")
    return {
        "payments_enabled": get_settings().payments_enabled,
        "offer": offer,
        "payment": payment_to_dict(payment),
        "payee_onboarded": bool(payee and payee.stripe_account_id),
    }


@router.post("/cases/{case_id}/settlement/checkout")
def create_settlement_checkout(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte reclamada escolhe pagar o valor da decisão. Devolve a URL do
    Checkout; a confirmação chega pelo webhook, nunca pelo navegador."""
    _require_payments()
    case = _case_or_404(db, case_id)
    payer = _require_actor(db, case, x_actor_token, "respondent")
    offer = settlement_offer(case_to_dict(case, include_content=False))
    if not offer["available"]:
        raise HTTPException(status_code=409, detail=offer["reason"])

    payee = member_user(db, case.id, "claimant")
    if payee is None or not payee.stripe_account_id:
        raise HTTPException(status_code=409, detail="payee_not_onboarded")
    if payer is not None and payer.id == payee.id:
        raise HTTPException(status_code=409, detail="payer_is_payee")
    try:
        if not payments_gateway.account_ready(payee.stripe_account_id):
            raise HTTPException(status_code=409, detail="payee_not_onboarded")

        payment = get_payment(db, case.id, offer["attestation_hash"])
        if payment is None:
            try:
                payment = new_payment(
                    db, case_id=case.id, offer=offer, payer=payer, payee=payee
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                payment = get_payment(db, case.id, offer["attestation_hash"])
        if payment.status == "paid":
            raise HTTPException(status_code=409, detail="already_paid")
        if payment.checkout_session_id:
            existing = payments_gateway.retrieve_checkout_session(
                payment.checkout_session_id
            )
            if existing["status"] == "open":
                return {"payment": payment_to_dict(payment), "checkout_url": existing["url"]}
            if existing["status"] == "complete":
                # Pago, mas o webhook ainda não chegou: não abre outra cobrança.
                raise HTTPException(status_code=409, detail="payment_processing")

        base = get_settings().public_app_url
        session_id, url = payments_gateway.create_checkout_session(
            payment_id=payment.id,
            case_id=case.id,
            attestation_hash=payment.attestation_hash,
            title=case.title,
            amount_minor_units=payment.amount_minor_units,
            fee_minor_units=payment.fee_minor_units,
            currency=payment.currency,
            destination_account_id=payee.stripe_account_id,
            customer_email=payer.email if payer is not None else None,
            success_url=f"{base}/?case={case.id}&settlement=success",
            cancel_url=f"{base}/?case={case.id}&settlement=cancelled",
        )
    except payments_gateway.PaymentsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payment.checkout_session_id = session_id
    payment.status = "pending"
    append_audit(
        db,
        case,
        "settlement_checkout_created",
        {
            "payment_id": payment.id,
            "attestation_hash": payment.attestation_hash,
            "amount_minor_units": payment.amount_minor_units,
            "platform_fee_minor_units": payment.fee_minor_units,
            "currency": payment.currency,
        },
    )
    db.commit()
    return {"payment": payment_to_dict(payment), "checkout_url": url}


_WEBHOOK_STATUS = {
    "checkout.session.completed": None,  # depende de payment_status
    "checkout.session.async_payment_succeeded": "paid",
    "checkout.session.async_payment_failed": "failed",
    "checkout.session.expired": "expired",
}


def _apply_payment_event(db: Session, event: Dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type not in _WEBHOOK_STATUS:
        return
    session = (event.get("data") or {}).get("object") or {}
    payment = get_payment_by_session(db, session.get("id") or "")
    if payment is None:
        return
    new_status = _WEBHOOK_STATUS[event_type]
    if event_type == "checkout.session.completed":
        if session.get("payment_status") != "paid":
            return  # pagamento assíncrono: aguarda async_payment_succeeded
        new_status = "paid"
    if payment.status == "paid" or payment.status == new_status:
        return
    if new_status == "paid":
        if (
            session.get("amount_total") != payment.amount_minor_units
            or (session.get("currency") or "").upper() != payment.currency
        ):
            logger.error("settlement_amount_mismatch payment=%s", payment.id)
            return
        payment.paid_at = datetime.now(timezone.utc)
        payment.payment_intent_id = session.get("payment_intent")
    payment.status = new_status
    case = get_case(db, payment.case_id)
    append_audit(
        db,
        case,
        f"settlement_payment_{new_status}",
        {
            "payment_id": payment.id,
            "attestation_hash": payment.attestation_hash,
            "amount_minor_units": payment.amount_minor_units,
            "platform_fee_minor_units": payment.fee_minor_units,
            "currency": payment.currency,
        },
    )
    db.commit()


@router.post(ctx.STRIPE_WEBHOOK_PATH, include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not get_settings().payments_enabled:
        raise HTTPException(status_code=503, detail="Pagamentos não habilitados")
    payload = await request.body()
    try:
        event = payments_gateway.construct_event(
            payload, request.headers.get("stripe-signature", "")
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Assinatura inválida") from exc
    await run_in_threadpool(_apply_payment_event, db, event)
    return {"received": True}
