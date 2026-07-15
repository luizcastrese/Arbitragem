from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
from io import BytesIO
import json
import logging
from pathlib import Path
import secrets
from time import perf_counter
from typing import Dict, List
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.conciliator import assess_conciliation
from app.agents.judge import decide_case as judge_decide_case
from app.agents.organizer import organize_case as organizer_organize_case
from app.agents.reviewer import review_decision
from app.core.audit import verify_audit_chain
from app.core.canonical import canonical_hash
from app.core.config import get_settings
from app.core.encryption import decrypt_text, encrypt_text
from app.core.hashing import sha256_text
from app.core.manifest import lock_case_manifest
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.signing import verify_signature
from app.db.access_repository import (
    accept_invitation,
    add_member,
    authenticate_user,
    create_deadline,
    create_invitation,
    create_notification,
    create_session,
    create_user_action_token,
    consume_user_action_token,
    deadline_to_dict,
    get_user_by_token,
    get_user_by_email,
    invitation_to_dict,
    mark_email_verified,
    register_user,
    reset_password,
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
    finalize_case as persist_finalization,
    list_cases,
    lock_manifest as persist_manifest,
    record_consent,
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
    ConciliationRoundRequest,
    ConsentRequest,
    CreateCaseRequest,
    DeadlineRequest,
    EmailAddressRequest,
    EmailTokenRequest,
    EvidenceActionRequest,
    FinalizeCaseRequest,
    InvitationRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    RegisterRequest,
)
from app.services.email import (
    send_invitation_email,
    send_password_reset_email,
    send_verification_email,
)


settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("valinor")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_for_startup()
    if settings.data_encryption_key:
        probe = encrypt_text("valinor-startup-check")
        if decrypt_text(probe) != "valinor-startup-check":
            raise RuntimeError("Falha ao validar DATA_ENCRYPTION_KEY")
    init_db()
    yield


app = FastAPI(
    title="Valinor",
    version="0.6.0",
    description="Fluxo auditável de decisão de disputas documentais por IA.",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")[:100] or str(uuid.uuid4())
    started_at = perf_counter()
    cookie_token = request.cookies.get(settings.session_cookie_name, "")
    if cookie_token:
        headers = list(request.scope.get("headers", []))
        names = {name.lower() for name, _ in headers}
        encoded = cookie_token.encode("latin-1")
        if b"x-session-token" not in names:
            headers.append((b"x-session-token", encoded))
        if b"x-actor-token" not in names:
            headers.append((b"x-actor-token", encoded))
        request.scope["headers"] = headers

    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    limit = 10 if path in {"/auth/login", "/auth/register"} else None
    bucket = f"{client_ip}:{path}"
    if not rate_limiter.allow(bucket, limit=limit):
        return JSONResponse(
            status_code=429,
            content={"detail": "Muitas solicitações. Aguarde um minuto e tente novamente."},
            headers={"Retry-After": "60", "X-Request-ID": request_id},
        )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self' https://api.openai.com"
    )
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
            ensure_ascii=True,
        )
    )
    return response


def _set_session_cookie(response: Response, token: str, max_age: int = 7 * 24 * 60 * 60) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
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
    if (
        settings.allow_legacy_case_tokens
        and token
        and stored_hash
        and secrets.compare_digest(_hash_token(token), stored_hash)
    ):
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
        "docs": None if settings.is_production else "/docs",
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
                "auditoria separada por IA e indicação de revisão humana quando necessária",
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


def _require_final_report_access(
    db: Session,
    case,
    x_session_token: str,
    draft: bool,
):
    user = _require_case_view(db, case, x_session_token)
    if case.finalized_at:
        case_data = case_to_dict(case)
        audit_valid, _ = verify_audit_chain(case_data.get("audit_log", []))
        manifest = case_data.get("locked_manifest") or {}
        unsigned = dict(manifest)
        manifest_hash = unsigned.pop("manifest_hash", None)
        unsigned.pop("platform_signature", None)
        unsigned.pop("signature_algorithm", None)
        integrity_valid = (
            audit_valid
            and manifest_hash == canonical_hash(unsigned)
            and verify_signature(manifest)
        )
        if not integrity_valid:
            raise HTTPException(
                status_code=409,
                detail="A integridade do procedimento falhou; o relatório foi bloqueado",
            )
        return user
    if not draft:
        raise HTTPException(
            status_code=409,
            detail="O relatório final só é liberado depois da finalização do procedimento",
        )
    if not user or not user_has_role(db, case.id, user.id, "manager"):
        raise HTTPException(
            status_code=403,
            detail="Somente o gestor pode gerar uma prévia antes da finalização",
        )
    return user


@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user = register_user(
            db,
            payload.display_name,
            payload.email,
            payload.password,
            email_verified=not settings.email_verification_required,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if settings.email_verification_required:
        verification_token, _ = create_user_action_token(db, user, "verify_email")
        try:
            send_verification_email(user.email, verification_token)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Conta criada, mas o e-mail de verificação não pôde ser enviado",
            ) from exc
        result = {
            "user": user_to_dict(user),
            "verification_required": True,
        }
        if settings.expose_auth_tokens:
            result["verification_token"] = verification_token
        return result

    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    result = {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
    }
    if settings.expose_auth_tokens:
        result["session_token"] = token
    return result


@app.post("/auth/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    if settings.email_verification_required and not user.email_verified:
        raise HTTPException(status_code=403, detail="Confirme seu e-mail antes de entrar")
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    result = {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
    }
    if settings.expose_auth_tokens:
        result["session_token"] = token
    return result


@app.post("/auth/verify-email")
def verify_email(
    payload: EmailTokenRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = consume_user_action_token(db, payload.token, "verify_email")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    mark_email_verified(db, user)
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    result = {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
    }
    if settings.expose_auth_tokens:
        result["session_token"] = token
    return result


@app.post("/auth/verify-email/request")
def request_email_verification(
    payload: EmailAddressRequest,
    db: Session = Depends(get_db),
):
    user = get_user_by_email(db, payload.email)
    result = {"message": "Se a conta existir e precisar de confirmação, enviaremos um e-mail."}
    if user and not user.email_verified:
        token, _ = create_user_action_token(db, user, "verify_email")
        try:
            send_verification_email(user.email, token)
        except RuntimeError:
            pass
        if settings.expose_auth_tokens:
            result["verification_token"] = token
    return result


@app.post("/auth/password-reset/request")
def request_password_reset(
    payload: EmailAddressRequest,
    db: Session = Depends(get_db),
):
    user = get_user_by_email(db, payload.email)
    result = {"message": "Se a conta existir, enviaremos as instruções de redefinição."}
    if user:
        token, _ = create_user_action_token(db, user, "reset_password")
        try:
            send_password_reset_email(user.email, token)
        except RuntimeError:
            pass
        if settings.expose_auth_tokens:
            result["reset_token"] = token
    return result


@app.post("/auth/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: Session = Depends(get_db),
):
    try:
        user = consume_user_action_token(db, payload.token, "reset_password")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    reset_password(db, user, payload.password)
    return {"message": "Senha redefinida. Entre novamente com a nova senha."}


@app.get("/auth/me")
def current_user(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    return user_to_dict(_session_user_or_401(db, x_session_token))


@app.post("/auth/logout")
def logout(
    response: Response,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not revoke_session(db, x_session_token):
        raise HTTPException(status_code=401, detail="Sessão inválida")
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
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
    user = get_user_by_token(db, x_session_token)
    if settings.auth_required and not user:
        raise HTTPException(status_code=401, detail="Entre para criar um caso")
    credentials = (
        {
            "claimant": secrets.token_urlsafe(24),
            "respondent": secrets.token_urlsafe(24),
            "manager": secrets.token_urlsafe(24),
        }
        if settings.allow_legacy_case_tokens
        else {}
    )
    case = persist_case(
        db,
        title=payload.title,
        claimant=payload.claimant,
        respondent=payload.respondent,
        claimant_token_hash=_hash_token(credentials["claimant"]) if credentials else None,
        respondent_token_hash=_hash_token(credentials["respondent"]) if credentials else None,
        manager_token_hash=_hash_token(credentials["manager"]) if credentials else None,
    )
    if user:
        add_member(db, case.id, user.id, "manager")
        db.expire_all()
        case = get_case(db, case.id)
    result = case_to_dict(case, include_content=False, include_embeddings=False)
    if credentials:
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
    if settings.smtp_host:
        try:
            send_invitation_email(invitation.email, token, case.title, invitation.role)
            result["delivery"] = "email"
        except RuntimeError as exc:
            if settings.is_production:
                raise HTTPException(
                    status_code=503,
                    detail="Convite criado, mas o e-mail não pôde ser enviado",
                ) from exc
            result["delivery"] = "manual"
    else:
        result["delivery"] = "manual"
    if not settings.is_production:
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
    if not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="O arquivo não possui assinatura válida de PDF")

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


@app.post("/cases/{case_id}/finalize")
def finalize_case(
    case_id: str,
    payload: FinalizeCaseRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    actor = _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    review = case_data.get("review") or {}
    if not review:
        raise HTTPException(status_code=409, detail="Audite a decisão antes de finalizar")
    if case.finalized_at:
        return case_data["finalization"]

    audit_valid, _ = verify_audit_chain(case_data.get("audit_log", []))
    manifest = case_data.get("locked_manifest") or {}
    unsigned = dict(manifest)
    manifest_hash = unsigned.pop("manifest_hash", None)
    unsigned.pop("platform_signature", None)
    unsigned.pop("signature_algorithm", None)
    if not (
        audit_valid
        and manifest_hash == canonical_hash(unsigned)
        and verify_signature(manifest)
    ):
        raise HTTPException(
            status_code=409,
            detail="A integridade do manifesto ou da auditoria precisa ser restaurada antes da finalização",
        )

    human_review_required = (
        not review.get("approved", False)
        or review.get("requires_human_review", False)
    )
    if human_review_required and not payload.human_override:
        raise HTTPException(
            status_code=409,
            detail="A auditoria exige revisão humana e uma justificativa antes da finalização",
        )
    basis = "human_review" if human_review_required else "ai_audit_approved"
    reviewer_id = actor.id if actor else "legacy-manager"
    updated = persist_finalization(
        db,
        case,
        reviewer_id=reviewer_id,
        basis=basis,
        note=payload.rationale,
    )
    return case_to_dict(updated, include_content=False, include_embeddings=False)[
        "finalization"
    ]


@app.get("/cases/{case_id}/report")
def report(
    case_id: str,
    draft: bool = False,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_final_report_access(db, case, x_session_token, draft)
    return build_report(
        case_to_dict(case, include_content=False, include_embeddings=False)
    )


@app.get("/cases/{case_id}/report.docx")
def report_docx(
    case_id: str,
    draft: bool = False,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_final_report_access(db, case, x_session_token, draft)
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
