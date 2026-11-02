"""Acatamento da decisão da IA como acordo entre as partes, sem árbitro."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.background import _issue_decision_record
from app.api.common import (
    _assert_procedure_open,
    _case_or_404,
    _require_actor,
    _require_case_view,
)
from app.core.canonical import canonical_hash
from app.db.repository import case_to_dict, get_case, save_decision_acceptance
from app.db.session import get_db
from app.domain.acceptance import (
    STATEMENT_SHA256,
    STATEMENT_VERSION,
    acceptance_status,
    eligibility,
    public_state,
)
from app.reports.decision_record import outcome_kind
from app.schemas import AcceptDecisionRequest

router = APIRouter()


def _reflection_hours() -> int:
    return ctx.settings.acceptance_reflection_hours


def _state(db: Session, case_id: str):
    case = get_case(db, case_id)
    case_data = case_to_dict(case, include_content=False, include_embeddings=False)
    return case_data, public_state(case_data, reflection_hours=_reflection_hours())


@router.get("/cases/{case_id}/decision-acceptance")
def get_decision_acceptance(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Declaração que a parte lê antes de acatar e o estado do acatamento."""
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return _state(db, case_id)[1]


@router.post("/cases/{case_id}/accept-decision")
def accept_decision(
    case_id: str,
    payload: AcceptDecisionRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte acata a decisão vigente e a adota como seu acordo.

    O ato é individual e irrevogável, e fica preso à attestation que a parte
    leu: se um recurso corrigir a decisão, é preciso acatar de novo. Quando as
    duas partes acatam, a decisão passa a valer como acordo (Código Civil, art.
    840), o auto é reemitido com esse efeito e o pagamento opcional deixa de
    esperar o prazo de recurso. Não depende de árbitro.
    """
    case = _case_or_404(db, case_id)
    user = _require_actor(db, case, x_actor_token, payload.party)
    _assert_procedure_open(case)
    case_data = case_to_dict(case, include_content=False, include_embeddings=False)
    if outcome_kind(case_data) != "decision":
        raise HTTPException(status_code=409, detail="Não há decisão de mérito para acatar.")

    status = acceptance_status(case_data)
    if status["parties"][payload.party]:
        # Idempotente: o segundo clique não grava outro evento.
        return {**public_state(case_data, reflection_hours=_reflection_hours())}

    can, code, reason = eligibility(case_data, reflection_hours=_reflection_hours())
    if not can:
        raise HTTPException(status_code=409, detail={"code": code, "message": reason})

    case = save_decision_acceptance(
        db,
        case,
        payload={
            "party": payload.party,
            "user_id": getattr(user, "id", None),
            "attestation_hash": status["attestation_hash"],
            "decision_hash": canonical_hash(case_data.get("decision") or {}),
            "statement_version": STATEMENT_VERSION,
            "statement_sha256": STATEMENT_SHA256,
        },
    )
    db.expire_all()
    fresh, state = _state(db, case_id)
    record = _issue_decision_record(db, case_id) if state["complete"] else None
    return {**state, "decision_record": record}
