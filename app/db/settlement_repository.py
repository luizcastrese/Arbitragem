"""Persistência do pagamento opcional da decisão."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import CaseMember, SettlementPayment, User


def member_user(db: Session, case_id: str, role: str) -> Optional[User]:
    member = (
        db.query(CaseMember)
        .filter(CaseMember.case_id == case_id, CaseMember.role == role)
        .first()
    )
    return member.user if member else None


def get_payment(
    db: Session, case_id: str, attestation_hash: str
) -> Optional[SettlementPayment]:
    return (
        db.query(SettlementPayment)
        .filter(
            SettlementPayment.case_id == case_id,
            SettlementPayment.attestation_hash == attestation_hash,
        )
        .one_or_none()
    )


def paid_payment(db: Session, case_id: str) -> Optional[SettlementPayment]:
    return (
        db.query(SettlementPayment)
        .filter(SettlementPayment.case_id == case_id, SettlementPayment.status == "paid")
        .order_by(SettlementPayment.paid_at.asc())
        .first()
    )


def get_payment_by_session(db: Session, session_id: str) -> Optional[SettlementPayment]:
    return (
        db.query(SettlementPayment)
        .filter(SettlementPayment.checkout_session_id == session_id)
        .one_or_none()
    )


def new_payment(
    db: Session,
    *,
    case_id: str,
    offer: Dict[str, Any],
    payer: Optional[User],
    payee: User,
) -> SettlementPayment:
    payment = SettlementPayment(
        id=str(uuid.uuid4()),
        case_id=case_id,
        attestation_hash=offer["attestation_hash"],
        payer_role=offer["payer_role"],
        payee_role=offer["payee_role"],
        payer_user_id=payer.id if payer else None,
        payee_user_id=payee.id,
        amount_minor_units=offer["amount_minor_units"],
        fee_minor_units=offer["platform_fee_minor_units"],
        currency=offer["currency"],
        status="pending",
    )
    db.add(payment)
    db.flush()
    return payment


def payment_to_dict(
    payment: Optional[SettlementPayment], detailed: bool = False
) -> Optional[Dict[str, Any]]:
    if payment is None:
        return None

    def iso(value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    extra = {"payment_intent_id": payment.payment_intent_id} if detailed else {}
    return {
        **extra,
        "id": payment.id,
        "status": payment.status,
        "amount_minor_units": payment.amount_minor_units,
        "platform_fee_minor_units": payment.fee_minor_units,
        "currency": payment.currency,
        "attestation_hash": payment.attestation_hash,
        "paid_at": iso(payment.paid_at),
        "created_at": iso(payment.created_at),
    }
