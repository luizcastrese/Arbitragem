"""Materiais do caso: envio, contraditório, admissão, conteúdo, originais e
busca.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Dict

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.common import (
    _assert_evidence_mutable,
    _assert_not_purged,
    _assert_procedure_open,
    _case_or_404,
    _counterparty,
    _document_or_404,
    _require_actor,
    _require_case_view,
    _require_steward_actuator,
    _retrieve,
)
from app.api.steward import _conduct_steward
from app.core.hashing import sha256_text
from app.core.signed_url import (
    SignedUrlError,
    sign_download_token,
    verify_download_token,
)
from app.db.access_repository import create_notification
from app.db.repository import (
    acknowledge_document as persist_acknowledgement,
    add_document as persist_document,
    admit_document as persist_admission,
    case_to_dict,
    document_to_dict,
    get_case,
    load_document_original,
    record_submission_ready,
    respond_to_document as persist_response,
)
from app.db.session import get_db
from app.documents.chunker import chunk_text
from app.documents.embeddings import build_embedding
from app.documents.pdf_parser import extract_text_from_pdf_bytes
from app.documents.storage import StorageError, get_document_storage
from app.schemas import AddDocumentRequest, EvidenceActionRequest

router = APIRouter()


def _process_document(
    db: Session,
    case,
    name: str,
    content: str,
    submitted_by: str,
    material_type: str,
    purpose: str,
    original_bytes: bytes | None = None,
    original_filename: str | None = None,
    original_media_type: str | None = None,
) -> Dict:
    if case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="Documentos não podem mudar após o manifesto ser travado",
        )

    chunks = chunk_text(content)
    if not chunks:
        raise HTTPException(status_code=400, detail="Documento sem texto legível")

    chunk_records = []
    for chunk in chunks:
        record = {
            "text": chunk,
            "sha256": sha256_text(chunk),
            "embedding": None,
            "embedding_error": False,
        }
        if ctx.settings.embeddings_enabled:
            try:
                record["embedding"] = build_embedding(chunk)
            except Exception:
                record["embedding_error"] = True
        chunk_records.append(record)

    document = persist_document(
        db=db,
        case=case,
        name=name.strip() or "documento",
        content=content,
        document_hash=sha256_text(content),
        chunk_records=chunk_records,
        submitted_by=submitted_by,
        material_type=material_type,
        purpose=purpose,
        original_bytes=original_bytes,
        original_filename=original_filename,
        original_media_type=original_media_type,
    )
    counterparty = "respondent" if submitted_by == "claimant" else "claimant"
    create_notification(
        db,
        case.id,
        counterparty,
        "evidence_disclosed",
        "Novo material disponível para manifestação",
        f"{name} foi apresentado. Confirme a ciência e registre sua resposta.",
    )
    return document_to_dict(document, include_content=False)


@router.post("/cases/{case_id}/documents/text", status_code=201)
def add_text_document(
    case_id: str,
    payload: AddDocumentRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.submitted_by)
    _assert_procedure_open(case)
    document = _process_document(
        db,
        case,
        payload.name,
        payload.content,
        payload.submitted_by,
        payload.material_type,
        payload.purpose,
    )
    _reopen_submission_if_ready(db, case_id, payload.submitted_by)
    return {"message": "Documento adicionado", "document": document}


@router.post("/cases/{case_id}/documents/pdf", status_code=201)
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
    _assert_procedure_open(case)

    file_bytes = await file.read(ctx.settings.max_upload_bytes + 1)
    if len(file_bytes) > ctx.settings.max_upload_bytes:
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
        original_bytes=file_bytes,
        original_filename=filename,
        original_media_type="application/pdf",
    )
    _reopen_submission_if_ready(db, case_id, submitted_by)
    return {
        "message": "PDF processado",
        "document": document,
        "text_preview": extracted_text[:1000],
    }


def _reopen_submission_if_ready(db: Session, case_id: str, party: str) -> None:
    """Material novo reabre a apresentação de quem o enviou."""
    case = get_case(db, case_id)
    if case is None or case.manifest_locked:
        return
    if getattr(case, f"{party}_submission_ready", False):
        record_submission_ready(db, case, party, False)


@router.post("/cases/{case_id}/documents/{document_id}/acknowledge")
def acknowledge_evidence(
    case_id: str,
    document_id: str,
    payload: EvidenceActionRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _assert_evidence_mutable(case)
    document = _document_or_404(db, case_id, document_id)
    expected_party = _counterparty(document)
    _require_actor(db, case, x_actor_token, expected_party)
    _assert_procedure_open(case)
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


@router.post("/cases/{case_id}/documents/{document_id}/respond")
def respond_to_evidence(
    case_id: str,
    document_id: str,
    payload: EvidenceActionRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _assert_evidence_mutable(case)
    document = _document_or_404(db, case_id, document_id)
    expected_party = _counterparty(document)
    _require_actor(db, case, x_actor_token, expected_party)
    _assert_procedure_open(case)
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
    _conduct_steward(db, get_case(db, case_id), wait=0, run_model_stages=True)
    db.expire_all()
    return case_to_dict(
        get_case(db, case_id),
        include_content=False,
        include_embeddings=False,
    )


@router.post("/cases/{case_id}/documents/{document_id}/admit")
def admit_evidence(
    case_id: str,
    document_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _assert_procedure_open(case)
    _assert_evidence_mutable(case)
    _require_steward_actuator(x_actor_token)
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


@router.get("/cases/{case_id}/documents/{document_id}/content")
def get_document_content(
    case_id: str,
    document_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Devolve o teor do material para quem participa do caso.

    O detalhe do caso omite o conteúdo para manter a listagem leve; sem este
    endpoint a contraparte confirmaria ciência e responderia sem conseguir
    ler o que foi apresentado.
    """
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    document = _document_or_404(db, case_id, document_id)
    _assert_not_purged(document)
    payload = document_to_dict(document, include_content=True)
    return {
        "id": payload["id"],
        "name": payload["name"],
        "content": payload.get("content") or "",
        "sha256": payload["sha256"],
        "submitted_by": payload["submitted_by"],
        "purpose": payload["purpose"],
        "has_original": payload["has_original"],
        "material_type": payload["material_type"],
    }


@router.get("/cases/{case_id}/documents/{document_id}/original")
def download_document_original(
    case_id: str,
    document_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    document = _document_or_404(db, case_id, document_id)
    _assert_not_purged(document)
    original = load_document_original(document)
    if original is None:
        raise HTTPException(
            status_code=404,
            detail="Este documento não possui arquivo original armazenado",
        )
    return StreamingResponse(
        BytesIO(original),
        media_type=document.original_media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{document.name}"'
        },
    )


@router.post("/cases/{case_id}/documents/{document_id}/original-url")
def issue_original_download_url(
    case_id: str,
    document_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Emite um link temporário e assinado para o arquivo original. O link
    expira em `DOWNLOAD_URL_TTL_SECONDS` e dispensa nova autenticação."""
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    document = _document_or_404(db, case_id, document_id)
    _assert_not_purged(document)
    if not document.original_key:
        raise HTTPException(
            status_code=404,
            detail="Este documento não possui arquivo original armazenado",
        )
    ttl = ctx.settings.download_url_ttl_seconds
    token, expires_at = sign_download_token(
        key=document.original_key,
        filename=document.name,
        media_type=document.original_media_type or "application/octet-stream",
        expires_in=ttl,
    )
    return {
        "url": f"{ctx.settings.public_base_url}/documents/download?token={token}",
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "expires_in": ttl,
    }


@router.get("/documents/download")
def download_via_signed_url(token: str):
    """Endpoint público: valida o token assinado e devolve o objeto (decifrado
    pela camada de storage). Sem token válido e não expirado, nega o acesso."""
    try:
        claims = verify_download_token(token)
    except SignedUrlError as exc:
        raise HTTPException(status_code=403, detail=f"Link inválido: {exc}") from exc
    try:
        data = get_document_storage().get(claims["k"])
    except StorageError as exc:
        raise HTTPException(status_code=404, detail="Objeto não encontrado") from exc
    filename = claims.get("n") or "documento"
    return StreamingResponse(
        BytesIO(data),
        media_type=claims.get("m") or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}/chunks")
def list_chunks(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(
        case, include_content=False, include_embeddings=False
    )["chunks"]


@router.get("/cases/{case_id}/retrieve")
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
    return _retrieve(case_to_dict(case, include_content=False), query, method)
