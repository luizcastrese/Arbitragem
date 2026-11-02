"""Auto da decisão e relatórios."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.background import _issue_decision_record
from app.api.common import (
    _case_or_404,
    _require_case_view,
    _require_procedure_party,
    _require_steward_actuator,
)
from app.db.repository import case_to_dict
from app.db.session import get_db
from app.reports.decision_record import DecisionRecordNotReady, verify_record
from app.reports.decision_record_docx import build_decision_record_docx
from app.reports.docx_generator import build_docx_report
from app.reports.report_generator import build_report
from app.schemas import DecisionRecordVerifyRequest

router = APIRouter()


@router.post("/cases/{case_id}/decision-record")
def issue_decision_record(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Emite (ou devolve) o auto vigente. Qualquer parte ou o gestor pode
    pedir: a emissão é determinística a partir do registro do caso."""
    case = _case_or_404(db, case_id)
    try:
        _require_steward_actuator(x_actor_token)
    except HTTPException:
        _require_procedure_party(db, case, x_actor_token)
    try:
        record = _issue_decision_record(db, case_id)
    except DecisionRecordNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "O procedimento ainda não terminou: o auto só é emitido depois "
                "do acordo ou da auditoria da decisão"
            ),
        )
    return record


@router.get("/cases/{case_id}/decision-record")
def get_decision_record(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    record = case_to_dict(case, include_content=False, include_embeddings=False)[
        "decision_record"
    ]
    if not record:
        raise HTTPException(status_code=404, detail="Auto da decisão ainda não emitido")
    return record


@router.get("/cases/{case_id}/decision-record.docx")
def get_decision_record_docx(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    record = case_to_dict(case, include_content=False, include_embeddings=False)[
        "decision_record"
    ]
    if not record:
        raise HTTPException(status_code=404, detail="Auto da decisão ainda não emitido")
    output = build_decision_record_docx(record)
    filename = f"auto-valinor-{case.id[:8]}-{record.get('record_number')}.docx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/decision-records/verify")
def verify_decision_record_endpoint(payload: DecisionRecordVerifyRequest):
    """Qualquer pessoa confere se um auto é íntegro e foi assinado pela
    plataforma. Autos Ed25519 também podem ser conferidos offline com a chave
    publicada em /.well-known/valinor-signing-key."""
    valid, checks = verify_record(
        payload.record, public_key_b64=payload.public_key_b64 or None
    )
    return {"valid": valid, **checks}


@router.get("/cases/{case_id}/report")
def report(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return build_report(
        case_to_dict(case, include_content=False, include_embeddings=False)
    )


@router.get("/cases/{case_id}/report.docx")
def report_docx(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    case_data = case_to_dict(case, include_content=False, include_embeddings=False)
    output = build_docx_report(case_data)
    filename = f"relatorio-valinor-{case.id[:8]}.docx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
