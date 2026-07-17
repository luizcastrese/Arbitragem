"""Rotas de manifesto e registro: trava, verificação, auditoria e recuperação."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import (
    _case_or_404,
    _require_actor,
    _require_case_view,
    _retrieve,
    get_db,
)
from app.core.audit import verify_audit_chain
from app.core.canonical import canonical_hash
from app.core.manifest import lock_case_manifest
from app.core.signing import verify_signature
from app.db.repository import case_to_dict, lock_manifest as persist_manifest

router = APIRouter(prefix="/cases/{case_id}", tags=["manifesto"])


@router.post("/lock")
def lock_manifest(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    if case.manifest_locked:
        return {
            "message": "Manifesto já estava travado",
            "manifest": case_to_dict(case)["locked_manifest"],
        }
    if not case.documents:
        raise HTTPException(
            status_code=400,
            detail="Adicione ao menos um documento antes de travar o manifesto",
        )
    case_data = case_to_dict(case)
    if not case_data["consent"]["complete"]:
        raise HTTPException(
            status_code=409,
            detail="Cliente e empresa precisam aceitar o procedimento antes da trava",
        )
    if not case_data["contradictory"]["complete"]:
        pending = ", ".join(case_data["contradictory"]["pending_document_ids"])
        raise HTTPException(
            status_code=409,
            detail=f"Contraditório pendente nos materiais: {pending}",
        )

    manifest = lock_case_manifest(case_data)
    persist_manifest(db, case, manifest)
    return {"message": "Manifesto travado", "manifest": manifest}


@router.get("/manifest")
def get_manifest(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    manifest = case_to_dict(case)["locked_manifest"]
    if not manifest:
        raise HTTPException(status_code=400, detail="Manifesto ainda não foi travado")
    return manifest


@router.get("/manifest/verify")
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


@router.get("/audit")
def get_audit(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    events = case_to_dict(case)["audit_log"]
    valid, errors = verify_audit_chain(events)
    return {"valid": valid, "errors": errors, "events": events}


@router.get("/chunks")
def list_chunks(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_embeddings=False)["chunks"]


@router.get("/retrieve")
def retrieve_chunks(
    case_id: str,
    query: str,
    method: str = "embedding",
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Consulta não pode ser vazia")
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return _retrieve(case_to_dict(case), query, method)
