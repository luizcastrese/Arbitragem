"""Rotas de attestation: chave pública, emissão, consulta, verificação e contestação."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import _case_or_404, _require_actor, _require_case_view, get_db
from app.core.attestation import (
    AttestationError,
    build_decision_attestation,
    public_key_info,
    verify_attestation,
)
from app.core.audit import verify_audit_chain
from app.core.config import get_settings
from app.db.repository import case_to_dict, register_contest, save_stage
from app.schemas import AttestationVerifyRequest, ContestRequest

router = APIRouter(tags=["attestation"])


@router.get("/.well-known/valinor-signing-key")
def signing_key():
    settings_now = get_settings()
    if not settings_now.attestation_enabled:
        raise HTTPException(
            status_code=404,
            detail="A emissão de attestations não está habilitada nesta instância",
        )
    return public_key_info()


@router.post("/cases/{case_id}/attestation")
def issue_attestation(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    settings_now = get_settings()
    if not settings_now.attestation_enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "PLATFORM_ED25519_PRIVATE_KEY não está configurada; "
                "a emissão de attestations está desabilitada"
            ),
        )

    case_data = case_to_dict(case)
    if case_data["attestation"]:
        return case_data["attestation"]
    if case_data["contest"]["contested"]:
        raise HTTPException(
            status_code=409,
            detail="Caso contestado: nenhuma attestation pode ser emitida",
        )

    # A cadeia de auditoria íntegra é pré-condição criptográfica da emissão.
    audit_events = case_data["audit_log"]
    chain_valid, chain_errors = verify_audit_chain(audit_events)
    if not chain_valid:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A cadeia de auditoria está inválida; "
                    "a attestation não pode ser emitida"
                ),
                "errors": chain_errors,
            },
        )
    audit_chain_head = audit_events[-1]["event_hash"] if audit_events else ""

    try:
        attestation = build_decision_attestation(
            case_data=case_data,
            audit_chain_head=audit_chain_head,
            audit_chain_length=len(audit_events),
        )
    except AttestationError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    save_stage(
        db,
        case,
        field="attestation_json",
        value=attestation,
        status="attested",
        event_type="attestation_issued",
        event_payload={
            "attestation_hash": attestation["attestation_hash"],
            "audit_chain_head": audit_chain_head,
            "outcome": attestation["decision"]["outcome"],
            "split": attestation["decision"]["split"],
            "contest_window_ends_utc": attestation["contest_window_ends_utc"],
            "key_id": attestation["platform"]["key_id"],
        },
    )
    return attestation


@router.get("/cases/{case_id}/attestation")
def get_attestation(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    attestation = case_to_dict(case)["attestation"]
    if not attestation:
        raise HTTPException(status_code=404, detail="Attestation ainda não emitida")
    return attestation


@router.post("/attestations/verify")
def verify_attestation_endpoint(payload: AttestationVerifyRequest):
    """Verificação stateless: qualquer terceiro pode validar uma attestation
    contra a chave pública da plataforma (ou uma chave informada)."""
    valid, checks = verify_attestation(
        payload.attestation,
        public_key_b64=payload.public_key_b64 or None,
    )
    return {"valid": valid, **checks}


@router.post("/cases/{case_id}/contest")
def contest_case(
    case_id: str,
    payload: ContestRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    actor_role = None
    for role in ("claimant", "respondent"):
        try:
            _require_actor(db, case, x_actor_token, role)
            actor_role = role
            break
        except HTTPException:
            continue
    if actor_role is None:
        raise HTTPException(
            status_code=403,
            detail="Apenas o reclamante ou a empresa reclamada podem contestar",
        )

    case_data = case_to_dict(case)
    attestation = case_data["attestation"]
    if not attestation:
        raise HTTPException(
            status_code=409,
            detail="Não há attestation emitida para contestar",
        )
    if case_data["contest"]["contested"]:
        return case_data["contest"]

    window_ends = datetime.fromisoformat(attestation["contest_window_ends_utc"])
    if datetime.now(window_ends.tzinfo) > window_ends:
        raise HTTPException(
            status_code=409,
            detail="A janela de contestação já se encerrou",
        )

    updated = register_contest(db, case, actor_role, payload.reason)
    return case_to_dict(updated)["contest"]
