"""Leads do piloto: banco ou escritório que quer testar a Valinor."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.email import deliver_lead_notification
from app.db.models import PilotLead
from app.db.session import get_db
from app.schemas import LeadRequest

router = APIRouter()


@router.post("/leads", status_code=201)
def create_lead(payload: LeadRequest, db: Session = Depends(get_db)):
    # Robô que preenche o campo-isca recebe o mesmo sucesso, sem gravar nada.
    if payload.website:
        return {"received": True}
    lead = PilotLead(
        id=str(uuid.uuid4()),
        name=payload.name,
        company=payload.company,
        email=payload.email.lower(),
        monthly_volume=payload.monthly_volume,
    )
    db.add(lead)
    db.commit()
    delivery = deliver_lead_notification(
        name=lead.name,
        company=lead.company,
        email=lead.email,
        monthly_volume=lead.monthly_volume,
    )
    lead.notification_status = (
        "delivered"
        if delivery.get("delivered")
        else "failed" if delivery.get("error") else "logged"
    )
    if delivery.get("delivered"):
        lead.notified_at = datetime.now(timezone.utc)
    db.commit()
    # Não devolve o estado interno do e-mail: o visitante só precisa saber que
    # o contato foi recebido.
    return {"received": True}
