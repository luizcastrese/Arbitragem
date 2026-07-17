"""Rotas de relatório: versão JSON e exportação em DOCX."""

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import _case_or_404, _require_case_view, get_db
from app.db.repository import case_to_dict
from app.reports.docx_generator import build_docx_report
from app.reports.report_generator import build_report

router = APIRouter(prefix="/cases/{case_id}", tags=["relatórios"])


@router.get("/report")
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


@router.get("/report.docx")
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
