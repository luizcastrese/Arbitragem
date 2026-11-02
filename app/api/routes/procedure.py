"""Andamento do procedimento: apresentação encerrada, manifesto, auditoria,
verificação e recursos.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.common import (
    _assert_procedure_open,
    _case_or_404,
    _model_stages_enabled,
    _require_actor,
    _require_case_view,
    _require_steward_actuator,
)
from app.api.steward import _conduct_steward, _lock_manifest_now, _take_steward_chain
from app.core.audit import verify_audit_chain
from app.core.canonical import canonical_hash
from app.core.signing import verify_signature
from app.db.repository import case_to_dict, get_case, record_submission_ready
from app.db.session import get_db
from app.schemas import SubmissionReadyRequest

router = APIRouter()


@router.post("/cases/{case_id}/submission-ready")
def declare_submission_ready(
    case_id: str,
    payload: SubmissionReadyRequest,
    wait: float = Query(0, ge=0, le=ctx.MAX_STAGE_WAIT_SECONDS),
    x_actor_token: str = Header(default=""),
    x_steward_run_models: str = Header(default="1"),
    db: Session = Depends(get_db),
):
    """A parte encerra ou reabre a própria apresentação. O gestor conduz."""
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    _assert_procedure_open(case)
    if case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="A apresentação não pode ser reaberta depois da trava",
        )
    record_submission_ready(db, case, payload.party, payload.ready)
    _conduct_steward(
        db,
        get_case(db, case_id),
        wait=wait,
        run_model_stages=_model_stages_enabled(x_steward_run_models),
    )
    db.expire_all()
    return case_to_dict(
        get_case(db, case_id),
        include_content=False,
        include_embeddings=False,
    )


@router.post("/cases/{case_id}/lock")
def lock_manifest(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Atuador do gestor. A parte não trava o caso; declara a apresentação."""
    case = _case_or_404(db, case_id)
    _assert_procedure_open(case)
    _require_steward_actuator(x_actor_token)
    if case.manifest_locked:
        _take_steward_chain(db, case_id)
        return {
            "message": "Manifesto já estava travado",
            "manifest": case_to_dict(case)["locked_manifest"],
        }
    manifest = _lock_manifest_now(db, case)
    return {"message": "Manifesto travado", "manifest": manifest}


@router.get("/cases/{case_id}/manifest")
def get_manifest(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    manifest = case_to_dict(case, include_content=False)["locked_manifest"]
    if not manifest:
        raise HTTPException(status_code=400, detail="Manifesto ainda não foi travado")
    return manifest


@router.get("/cases/{case_id}/manifest/verify")
def verify_manifest(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    manifest = get_manifest(case_id, x_session_token, db)
    unsigned = dict(manifest)
    manifest_hash = unsigned.pop("manifest_hash", None)
    unsigned.pop("platform_signature", None)
    unsigned.pop("signature_algorithm", None)
    hash_valid = manifest_hash == canonical_hash(unsigned)
    signature_valid = verify_signature(manifest)
    return {
        "valid": hash_valid and signature_valid,
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
    }


@router.get("/cases/{case_id}/audit")
def get_audit(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    events = case_to_dict(case, include_content=False)["audit_log"]
    valid, errors = verify_audit_chain(events)
    return {"valid": valid, "errors": errors, "events": events}


@router.get("/cases/{case_id}/verification")
def get_verification(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    verification = case_to_dict(case, include_content=False).get("verification")
    if not verification:
        raise HTTPException(status_code=404, detail="Verificação ainda não executada")
    return verification


@router.get("/cases/{case_id}/appeals")
def get_appeals(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_content=False).get("appeals") or []
