from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
from io import BytesIO
from pathlib import Path
import secrets
from typing import Dict, List

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.conciliator import assess_conciliation
from app.agents.judge import decide_case as judge_decide_case
from app.agents.organizer import organize_case as organizer_organize_case
from app.agents.reviewer import review_decision
from app.core.attestation import (
    AttestationError,
    build_decision_attestation,
    public_key_info,
    verify_attestation,
)
from app.core.audit import verify_audit_chain
from app.core.canonical import canonical_hash
from app.core.config import get_settings
from app.core.hashing import sha256_text
from app.core.manifest import lock_case_manifest
from app.core.signing import verify_signature
from app.db.access_repository import (
    accept_invitation,
    add_member,
    authenticate_user,
    create_deadline,
    create_invitation,
    create_notification,
    create_session,
    deadline_to_dict,
    get_user_by_token,
    invitation_to_dict,
    register_user,
    revoke_session,
    user_case_ids,
    user_has_role,
    user_to_dict,
)
from app.db.init_db import init_db
from app.db.repository import (
    add_document as persist_document,
    acknowledge_document as persist_acknowledgement,
    admit_document as persist_admission,
    case_to_dict,
    create_case as persist_case,
    document_to_dict,
    get_document,
    get_case,
    list_cases,
    lock_manifest as persist_manifest,
    record_consent,
    register_contest,
    respond_to_document as persist_response,
    save_stage,
    append_audit,
)
from app.db.models import Deadline, Invitation
from app.db.session import get_db
from app.documents.chunker import chunk_text
from app.documents.embeddings import build_embedding, retrieve_by_embedding
from app.documents.pdf_parser import extract_text_from_pdf_bytes
from app.documents.retrieval import retrieve_relevant_chunks
from app.reports.report_generator import build_report
from app.reports.docx_generator import build_docx_report
from app.schemas import (
    AcceptInvitationRequest,
    AddDocumentRequest,
    AttestationVerifyRequest,
    ConciliationRoundRequest,
    ConsentRequest,
    ContestRequest,
    CreateCaseRequest,
    DeadlineRequest,
    EvidenceActionRequest,
    InvitationRequest,
    LoginRequest,
    RegisterRequest,
)


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Valinor",
    version="0.5.0",
    description="Fluxo auditável de decisão de disputas documentais por IA.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _case_or_404(db: Session, case_id: str):
    case = get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Caso não encontrado")
    return case


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _require_actor(db: Session, case, token: str, expected_party: str):
    stored_hash = getattr(case, f"{expected_party}_token_hash", None)
    if token and stored_hash and secrets.compare_digest(_hash_token(token), stored_hash):
        return None
    user = get_user_by_token(db, token)
    if user and user_has_role(db, case.id, user.id, expected_party):
        return user
    raise HTTPException(
        status_code=403,
        detail=f"Credencial inválida para o papel {expected_party}",
    )


def _public_case(case) -> Dict:
    data = case_to_dict(case, include_content=False, include_embeddings=False)
    decision = data.get("decision") or {}
    data["ai_result_status"] = (
        "unavailable"
        if decision.get("execution", {}).get("mode") == "safe_fallback"
        else "completed"
        if decision
        else "pending"
    )
    data["documents_count"] = len(data.pop("documents"))
    data.pop("chunks", None)
    data.pop("audit_log", None)
    data.pop("locked_manifest", None)
    data.pop("conciliation", None)
    data.pop("conciliation_rounds", None)
    data.pop("organized", None)
    data.pop("decision", None)
    data.pop("review", None)
    data.pop("attestation", None)
    return data


def _retrieve(case_data: Dict, query: str, method: str = "embedding") -> List[Dict]:
    admitted_document_ids = {
        document["id"]
        for document in case_data["documents"]
        if document.get("admitted")
    }
    chunks = [
        chunk
        for chunk in case_data["chunks"]
        if chunk.get("document_id") in admitted_document_ids
    ]
    if method not in {"embedding", "lexical"}:
        raise HTTPException(
            status_code=400,
            detail="Método deve ser 'embedding' ou 'lexical'",
        )
    if method == "embedding":
        try:
            results = retrieve_by_embedding(query=query, chunks=chunks, limit=5)
            if results:
                return results
        except Exception:
            pass
    return retrieve_relevant_chunks(query=query, chunks=chunks, limit=5)


def _process_document(
    db: Session,
    case,
    name: str,
    content: str,
    submitted_by: str,
    material_type: str,
    purpose: str,
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
        if settings.openai_enabled:
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


@app.get("/")
def root():
    return {
        "project": "Valinor",
        "version": app.version,
        "status": "running",
        "docs": "/docs",
        "ui": "/ui/",
        "openai_enabled": settings.openai_enabled,
        "auth_required": settings.auth_required,
        "procedure_terms": {
            "version": "2026-07-12",
            "principles": [
                "participação voluntária e regras iguais para as partes",
                "conhecimento e oportunidade de resposta a todo material",
                "tentativas de composição dependem de aceitação das partes",
                "decisão por IA fundamentada apenas no registro admitido",
                "auditoria independente e indicação de revisão humana quando necessária",
            ],
        },
        "warnings": [
            warning
            for warning in [
                (
                    "OPENAI_API_KEY ausente: agentes usarão modo seguro inconclusivo."
                    if not settings.openai_enabled
                    else None
                ),
                (
                    "PLATFORM_SIGNING_SECRET usa valor de desenvolvimento."
                    if settings.using_development_signing_secret
                    else None
                ),
            ]
            if warning
        ],
    }


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "ok",
        "openai_enabled": settings.openai_enabled,
    }


def _session_user_or_401(db: Session, x_session_token: str):
    user = get_user_by_token(db, x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Sessão ausente, inválida ou expirada")
    return user


def _require_case_view(db: Session, case, x_session_token: str):
    if not settings.auth_required:
        return get_user_by_token(db, x_session_token)
    user = _session_user_or_401(db, x_session_token)
    if case.id not in set(user_case_ids(db, user.id)):
        raise HTTPException(status_code=403, detail="Sua conta não participa deste caso")
    return user


@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = register_user(db, payload.display_name, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token, session = create_session(db, user)
    return {
        "user": user_to_dict(user),
        "session_token": token,
        "expires_at": session.expires_at.isoformat(),
    }


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    token, session = create_session(db, user)
    return {
        "user": user_to_dict(user),
        "session_token": token,
        "expires_at": session.expires_at.isoformat(),
    }


@app.get("/auth/me")
def current_user(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    return user_to_dict(_session_user_or_401(db, x_session_token))


@app.post("/auth/logout")
def logout(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not revoke_session(db, x_session_token):
        raise HTTPException(status_code=401, detail="Sessão inválida")
    return {"message": "Sessão encerrada"}


@app.get("/cases")
def get_cases(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    cases = list_cases(db)
    user = get_user_by_token(db, x_session_token)
    if settings.auth_required and not user:
        raise HTTPException(status_code=401, detail="Entre para acessar seus casos")
    if user:
        allowed_ids = set(user_case_ids(db, user.id))
        cases = [case for case in cases if case.id in allowed_ids]
    return [_public_case(case) for case in cases]


@app.get("/cases/{case_id}")
def get_case_detail(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_content=False, include_embeddings=False)


@app.post("/cases", status_code=201)
def create_case(
    payload: CreateCaseRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    credentials = {
        "claimant": secrets.token_urlsafe(24),
        "respondent": secrets.token_urlsafe(24),
        "manager": secrets.token_urlsafe(24),
    }
    case = persist_case(
        db,
        title=payload.title,
        claimant=payload.claimant,
        respondent=payload.respondent,
        claimant_token_hash=_hash_token(credentials["claimant"]),
        respondent_token_hash=_hash_token(credentials["respondent"]),
        manager_token_hash=_hash_token(credentials["manager"]),
    )
    user = get_user_by_token(db, x_session_token)
    if user:
        add_member(db, case.id, user.id, "manager")
        db.expire_all()
        case = get_case(db, case.id)
    result = case_to_dict(case, include_content=False, include_embeddings=False)
    result["access_credentials"] = credentials
    return result


@app.get("/cases/{case_id}/invitations")
def get_invitations(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    return [invitation_to_dict(item) for item in case.invitations]


@app.post("/cases/{case_id}/invitations", status_code=201)
def invite_participant(
    case_id: str,
    payload: InvitationRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    actor = _require_actor(db, case, x_actor_token, "manager")
    token, invitation = create_invitation(
        db,
        case.id,
        payload.email,
        payload.role,
        actor.id if actor else None,
    )
    append_audit(
        db,
        case,
        "participant_invited",
        {"email": invitation.email, "role": invitation.role, "invitation_id": invitation.id},
    )
    db.commit()
    create_notification(
        db,
        case.id,
        payload.role,
        "invitation_created",
        "Convite para participar do procedimento",
        f"Você foi convidado para atuar como {payload.role} no caso {case.title}.",
    )
    result = invitation_to_dict(invitation)
    result["acceptance_token"] = token
    result["acceptance_path"] = f"/ui/?invite={token}"
    return result


@app.post("/invitations/accept")
def accept_case_invitation(
    payload: AcceptInvitationRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    user = _session_user_or_401(db, x_session_token)
    try:
        invitation = accept_invitation(db, payload.token, user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    case = _case_or_404(db, invitation.case_id)
    append_audit(
        db,
        case,
        "invitation_accepted",
        {"user_id": user.id, "role": invitation.role, "invitation_id": invitation.id},
    )
    db.commit()
    return {"case_id": case.id, "role": invitation.role, "message": "Convite aceito"}


@app.get("/cases/{case_id}/deadlines")
def get_deadlines(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return [deadline_to_dict(item) for item in case.deadlines]


@app.post("/cases/{case_id}/deadlines", status_code=201)
def add_deadline(
    case_id: str,
    payload: DeadlineRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    try:
        due_at = datetime.fromisoformat(payload.due_at.replace("Z", "+00:00"))
        if due_at.tzinfo is None:
            due_at = due_at.astimezone()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Data do prazo inválida") from exc
    deadline = create_deadline(
        db, case.id, payload.label, payload.kind, payload.assigned_to, due_at
    )
    append_audit(
        db,
        case,
        "deadline_created",
        {"deadline_id": deadline.id, "assigned_to": deadline.assigned_to, "due_at": deadline.due_at.isoformat()},
    )
    db.commit()
    for party in ({"claimant", "respondent", "manager"} if payload.assigned_to == "all" else {payload.assigned_to}):
        create_notification(
            db,
            case.id,
            party,
            "deadline_created",
            "Novo prazo no procedimento",
            f"{deadline.label}: até {deadline.due_at.isoformat()}.",
        )
    return deadline_to_dict(deadline)


@app.post("/cases/{case_id}/deadlines/{deadline_id}/complete")
def complete_deadline(
    case_id: str,
    deadline_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    deadline = db.query(Deadline).filter(
        Deadline.case_id == case.id, Deadline.id == deadline_id
    ).one_or_none()
    if not deadline:
        raise HTTPException(status_code=404, detail="Prazo não encontrado")
    deadline.completed_at = datetime.now().astimezone()
    append_audit(db, case, "deadline_completed", {"deadline_id": deadline.id})
    db.commit()
    return deadline_to_dict(deadline)


@app.post("/cases/{case_id}/consent")
def set_case_consent(
    case_id: str,
    payload: ConsentRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    if case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="O consentimento não pode ser alterado após a trava do processo",
        )
    updated = record_consent(
        db,
        case,
        party=payload.party,
        accepted=payload.accepted,
        terms_version=payload.terms_version,
    )
    return case_to_dict(updated, include_content=False, include_embeddings=False)[
        "consent"
    ]


@app.post("/cases/{case_id}/documents/text", status_code=201)
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


@app.post("/cases/{case_id}/documents/pdf", status_code=201)
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


def _document_or_404(db: Session, case_id: str, document_id: str):
    document = get_document(db, case_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return document


def _counterparty(document) -> str:
    return "respondent" if document.submitted_by == "claimant" else "claimant"


@app.post("/cases/{case_id}/documents/{document_id}/acknowledge")
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


@app.post("/cases/{case_id}/documents/{document_id}/respond")
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


@app.post("/cases/{case_id}/documents/{document_id}/admit")
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


@app.post("/cases/{case_id}/lock")
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


@app.get("/cases/{case_id}/manifest")
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


@app.get("/cases/{case_id}/manifest/verify")
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


@app.get("/cases/{case_id}/audit")
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


@app.get("/cases/{case_id}/chunks")
def list_chunks(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_embeddings=False)["chunks"]


@app.get("/cases/{case_id}/retrieve")
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


@app.post("/cases/{case_id}/conciliation")
def assess_case_conciliation(
    case_id: str,
    payload: ConciliationRoundRequest = ConciliationRoundRequest(),
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    if not case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="Trave o manifesto antes da triagem de composição",
        )
    rounds = case_data["conciliation_rounds"]
    if rounds and not payload.advance:
        return rounds[-1]
    if case_data["organized"]:
        raise HTTPException(
            status_code=409,
            detail="A fase de composição foi encerrada porque o julgamento já começou",
        )

    previous_round = rounds[-1] if rounds else None
    has_new_input = any(
        [
            payload.claimant_response,
            payload.respondent_response,
            payload.new_information,
        ]
    )
    if (
        previous_round
        and not previous_round.get("continue_recommended", False)
        and not has_new_input
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "A última rodada não recomendou nova tentativa. "
                "Informe fatos ou posições novas para reavaliar."
            ),
        )

    context = {
        "round_number": len(rounds) + 1,
        "manifest": case_data["locked_manifest"],
        "parties": {
            "claimant": case_data["claimant"],
            "respondent": case_data["respondent"],
        },
        "documents": [
            {
                "id": document["id"],
                "name": document["name"],
                "content": document.get("content", "")[:8000],
            }
            for document in case_data["documents"]
        ],
        "previous_rounds": rounds,
        "current_party_responses": {
            "claimant": payload.claimant_response,
            "respondent": payload.respondent_response,
            "new_information": payload.new_information,
        },
        "retrieved_evidence": {
            "shared_interests": _retrieve(
                case_data,
                "interesses comuns continuidade da relação acordo solução consensual",
            ),
            "possible_concessions": _retrieve(
                case_data,
                "propostas concessões negociação pagamento prazo entrega",
            ),
        },
    }
    round_number = len(rounds) + 1
    conciliation = assess_conciliation(context, round_number)
    updated_rounds = [*rounds, conciliation]
    save_stage(
        db,
        case,
        field="conciliation_json",
        value=updated_rounds,
        status="conciliation",
        event_type=(
            "conciliation_screened"
            if round_number == 1
            else "conciliation_round_generated"
        ),
        event_payload={
            "round_number": round_number,
            "convergence": conciliation.get("convergence"),
            "recommended_path": conciliation.get("recommended_path"),
            "confidence": conciliation.get("confidence"),
            "continue_recommended": conciliation.get("continue_recommended"),
            "recommended_additional_rounds": conciliation.get(
                "recommended_additional_rounds"
            ),
            "execution": conciliation.get("execution", {}),
        },
    )
    return conciliation


@app.post("/cases/{case_id}/organize")
def organize_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    if not case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="Trave o manifesto antes de organizar o caso",
        )
    if not case_data["conciliation"]:
        raise HTTPException(
            status_code=409,
            detail="Faça a triagem de conciliação ou mediação antes do julgamento",
        )
    if case_data["organized"]:
        return case_data["organized"]

    organized = organizer_organize_case(
        documents=case_data["documents"],
        chunks=case_data["chunks"],
    )
    save_stage(
        db,
        case,
        field="organized_json",
        value=organized,
        status="organized",
        event_type="case_organized",
        event_payload={"execution": organized.get("execution", {})},
    )
    return organized


@app.post("/cases/{case_id}/decide")
def decide_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    if not case_data["organized"]:
        raise HTTPException(
            status_code=409,
            detail="Organize o caso antes de proferir a decisão",
        )
    if case_data["decision"]:
        return case_data["decision"]

    decision_context = {
        "manifest": case_data["locked_manifest"],
        "conciliation_rounds": case_data["conciliation_rounds"],
        "organized_case": case_data["organized"],
        "retrieved_evidence": {
            "delivery": _retrieve(
                case_data,
                "obrigações de entrega e cumprimento parcial",
            ),
            "payment": _retrieve(
                case_data,
                "condições de pagamento e proporcionalidade",
            ),
            "deadline": _retrieve(
                case_data,
                "cumprimento de prazo e atraso",
            ),
        },
    }
    decision = judge_decide_case(decision_context)
    save_stage(
        db,
        case,
        field="decision_json",
        value=decision,
        status="decided",
        event_type="decision_generated",
        event_payload={
            "outcome": decision.get("outcome"),
            "confidence": decision.get("confidence"),
            "requires_human_review": decision.get("requires_human_review"),
            "execution": decision.get("execution", {}),
        },
    )
    return decision


@app.post("/cases/{case_id}/review")
def review_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    if not case_data["decision"]:
        raise HTTPException(
            status_code=409,
            detail="Profira a decisão antes da auditoria",
        )
    if case_data["review"]:
        return case_data["review"]

    review_payload = {
        "manifest": case_data["locked_manifest"],
        "conciliation_rounds": case_data["conciliation_rounds"],
        "organized_case": case_data["organized"],
        "decision": case_data["decision"],
    }
    review = review_decision(review_payload)
    save_stage(
        db,
        case,
        field="review_json",
        value=review,
        status="reviewed",
        event_type="review_generated",
        event_payload={
            "approved": review.get("approved"),
            "requires_human_review": review.get("requires_human_review"),
            "execution": review.get("execution", {}),
        },
    )
    return review


@app.get("/.well-known/valinor-signing-key")
def signing_key():
    settings_now = get_settings()
    if not settings_now.attestation_enabled:
        raise HTTPException(
            status_code=404,
            detail="A emissão de attestations não está habilitada nesta instância",
        )
    return public_key_info()


@app.post("/cases/{case_id}/attestation")
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


@app.get("/cases/{case_id}/attestation")
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


@app.post("/attestations/verify")
def verify_attestation_endpoint(payload: AttestationVerifyRequest):
    """Verificação stateless: qualquer terceiro pode validar uma attestation
    contra a chave pública da plataforma (ou uma chave informada)."""
    valid, checks = verify_attestation(
        payload.attestation,
        public_key_b64=payload.public_key_b64 or None,
    )
    return {"valid": valid, **checks}


@app.post("/cases/{case_id}/contest")
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


@app.get("/cases/{case_id}/report")
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


@app.get("/cases/{case_id}/report.docx")
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


frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/ui", StaticFiles(directory=frontend_dist, html=True), name="ui")
