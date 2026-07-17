"""Rotas de documentos: envio (texto/PDF), ciência, resposta e admissão."""

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import (
    _case_or_404,
    _counterparty,
    _document_or_404,
    _process_document,
    _require_actor,
    get_db,
    settings,
)
from app.db.repository import (
    acknowledge_document as persist_acknowledgement,
    admit_document as persist_admission,
    case_to_dict,
    get_case,
    respond_to_document as persist_response,
)
from app.documents.pdf_parser import extract_text_from_pdf_bytes
from app.schemas import AddDocumentRequest, EvidenceActionRequest

router = APIRouter(prefix="/cases/{case_id}/documents", tags=["documentos"])


@router.post("/text", status_code=201)
def add_text_document(
    case_id: str,
    payload: AddDocumentRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.submitted_by)
    document = _process_document(
        db,
        case,
        payload.name,
        payload.content,
        payload.submitted_by,
        payload.material_type,
        payload.purpose,
    )
    return {"message": "Documento adicionado", "document": document}


@router.post("/pdf", status_code=201)
async def upload_pdf(
    case_id: str,
    file: UploadFile = File(...),
    submitted_by: str = Form(...),
    material_type: str = Form("evidence"),
    purpose: str = Form(""),
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    filename = file.filename or "documento.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas PDFs são aceitos")
    if submitted_by not in {"claimant", "respondent"}:
        raise HTTPException(status_code=422, detail="Parte apresentadora inválida")
    if material_type not in {"evidence", "argument"}:
        raise HTTPException(status_code=422, detail="Tipo de material inválido")
    _require_actor(db, case, x_actor_token, submitted_by)

    file_bytes = await file.read(settings.max_upload_bytes + 1)
    if len(file_bytes) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="PDF excede o limite configurado")

    try:
        extracted_text = extract_text_from_pdf_bytes(file_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Falha ao ler PDF: {type(exc).__name__}",
        ) from exc

    document = _process_document(
        db,
        case,
        filename,
        extracted_text,
        submitted_by,
        material_type,
        purpose,
    )
    return {
        "message": "PDF processado",
        "document": document,
        "text_preview": extracted_text[:1000],
    }


@router.post("/{document_id}/acknowledge")
def acknowledge_evidence(
    case_id: str,
    document_id: str,
    payload: EvidenceActionRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    document = _document_or_404(db, case_id, document_id)
    expected_party = _counterparty(document)
    _require_actor(db, case, x_actor_token, expected_party)
    if payload.party != expected_party:
        raise HTTPException(
            status_code=403,
            detail=f"A ciência deve ser confirmada pela contraparte: {expected_party}",
        )
    if not document.disclosed_at:
        raise HTTPException(status_code=409, detail="Material ainda não disponibilizado")
    persist_acknowledgement(db, case, document, payload.party)
    return case_to_dict(
        get_case(db, case_id),
        include_content=False,
        include_embeddings=False,
    )


@router.post("/{document_id}/respond")
def respond_to_evidence(
    case_id: str,
    document_id: str,
    payload: EvidenceActionRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    document = _document_or_404(db, case_id, document_id)
    expected_party = _counterparty(document)
    _require_actor(db, case, x_actor_token, expected_party)
    if payload.party != expected_party:
        raise HTTPException(
            status_code=403,
            detail=f"A resposta deve ser apresentada pela contraparte: {expected_party}",
        )
    if not document.acknowledged_at:
        raise HTTPException(
            status_code=409,
            detail="Confirme a ciência antes de responder ao material",
        )
    if payload.response_status != "waived" and not payload.response_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Informe a manifestação ou escolha renúncia à resposta",
        )
    persist_response(
        db,
        case,
        document,
        payload.party,
        payload.response_status,
        payload.response_text,
    )
    return case_to_dict(
        get_case(db, case_id),
        include_content=False,
        include_embeddings=False,
    )


@router.post("/{document_id}/admit")
def admit_evidence(
    case_id: str,
    document_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    document = _document_or_404(db, case_id, document_id)
    if not document.acknowledged_at:
        raise HTTPException(status_code=409, detail="A contraparte ainda não confirmou ciência")
    if document.response_status not in {"answered", "waived", "challenged"}:
        raise HTTPException(status_code=409, detail="A oportunidade de resposta ainda está aberta")
    persist_admission(db, case, document)
    return case_to_dict(
        get_case(db, case_id),
        include_content=False,
        include_embeddings=False,
    )
