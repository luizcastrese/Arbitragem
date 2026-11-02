"""Atestado assinado da decisão e sua âncora pública."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.background import _issue_decision_record_safely
from app.api.common import _case_or_404, _require_case_view, _require_steward_actuator
from app.core.attestation import (
    AttestationError,
    build_decision_attestation,
    verify_attestation,
)
from app.core.audit import verify_audit_chain
from app.core.config import get_settings
from app.core.nostr_anchor import publish_attestation_anchor
from app.db.repository import (
    case_to_dict,
    get_case,
    persist_attestation_record,
    save_nostr_anchor,
    save_stage,
)
from app.db.session import get_db
from app.domain.concurrency import StageBusy, claim_case_stage
from app.schemas import AttestationVerifyRequest

router = APIRouter()


@router.post("/cases/{case_id}/attestation")
def issue_attestation(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_steward_actuator(x_actor_token)
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
    if settings_now.demo_non_decisional:
        raise HTTPException(
            status_code=409,
            detail=(
                "Julgador e revisor não têm políticas independentes nesta "
                "instância; o modo de demonstração não emite attestation de mérito."
            ),
        )
    verification = case_data.get("verification")
    if verification is not None and not verification.get("valid"):
        raise HTTPException(
            status_code=409,
            detail="A verificação determinística não validou a decisão",
        )
    if (case_data.get("procedure_conclusion") or "") in {
        "invalidated",
        "inadmissible",
        "inconclusive",
        "system_failure",
    }:
        raise HTTPException(
            status_code=409,
            detail="A conclusão do procedimento não admite attestation executável",
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
        claimed = claim_case_stage(
            db,
            case,
            "attestation",
            extra_from_statuses=("reviewed",),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        existing = case_to_dict(case).get("attestation")
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Attestation já em emissão")

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
            "supersedes_attestation_hash": attestation.get("supersedes_attestation_hash"),
        },
    )
    persist_attestation_record(db, case, attestation)
    db.commit()

    # Âncora pública em Nostr (hash + assinatura, nunca o teor da decisão).
    # Melhor esforço: falha de rede/relay não afeta a attestation já emitida.
    anchor = publish_attestation_anchor(attestation)
    if anchor:
        save_nostr_anchor(db, case, anchor)

    # O auto passa a registrar a attestation e o prazo de recurso.
    _issue_decision_record_safely(db, case_id)
    return attestation


@router.get("/cases/{case_id}/attestation")
def get_attestation(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    attestation = case_to_dict(case, include_content=False)["attestation"]
    if not attestation:
        raise HTTPException(status_code=404, detail="Attestation ainda não emitida")
    return attestation


@router.get("/cases/{case_id}/attestation/nostr-anchor")
def get_attestation_nostr_anchor(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    anchor = case_to_dict(case, include_content=False)["nostr_anchor"]
    if not anchor:
        raise HTTPException(
            status_code=404, detail="Attestation ainda não ancorada em Nostr"
        )
    return anchor


@router.post("/attestations/verify")
def verify_attestation_endpoint(payload: AttestationVerifyRequest):
    """Verificação stateless: qualquer terceiro pode validar uma attestation
    contra a chave pública da plataforma (ou uma chave informada)."""
    valid, checks = verify_attestation(
        payload.attestation,
        public_key_b64=payload.public_key_b64 or None,
    )
    return {"valid": valid, **checks}
