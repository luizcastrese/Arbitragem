from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import logging
from pathlib import Path
import secrets
import time
from typing import Dict, List
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.conciliator import assess_conciliation
from app.agents.execution import with_drift
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
from app.core.email import (
    deliver_invitation_email,
    deliver_password_reset_email,
    deliver_verification_email,
)
from app.core.hashing import sha256_text
from app.core.manifest import lock_case_manifest
from app.core.nostr_anchor import publish_attestation_anchor
from app.core.prompt_registry import detect_drift
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.signed_url import (
    SignedUrlError,
    sign_download_token,
    verify_download_token,
)
from app.core.signing import verify_signature
from app.core.terms import (
    TermsNotFound,
    current_terms,
    get_terms,
    list_versions as list_terms_versions,
)
from app.db.access_repository import (
    EMAIL_VERIFICATION,
    PASSWORD_RESET,
    AccountLocked,
    accept_invitation,
    add_member,
    authenticate_user,
    consume_auth_token,
    create_deadline,
    create_invitation,
    create_notification,
    create_session,
    deadline_to_dict,
    get_user_by_email,
    get_user_by_token,
    invitation_to_dict,
    issue_auth_token,
    mark_email_verified,
    register_user,
    revoke_session,
    set_password,
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
    count_appeals,
    create_case as persist_case,
    document_to_dict,
    find_appeal_by_idempotency,
    get_document,
    get_case,
    list_cases,
    load_document_original,
    lock_manifest as persist_manifest,
    persist_appeal,
    persist_attestation_record,
    record_consent,
    register_contest,
    respond_to_document as persist_response,
    save_stage,
    save_nostr_anchor,
    append_audit,
)
from app.db.models import Deadline, Invitation
from app.db.session import get_db
from app.domain.concurrency import StageBusy, claim_case_stage
from app.domain.frameworks import list_frameworks
from app.domain.legacy import public_decision_view
from app.domain.procedure import (
    generate_and_verify_decision,
    maybe_run_stability,
    reconstruct_once,
    reviewer_payload,
    run_appeal,
    run_automatic_review,
    finalize_review_outcome,
)
from app.documents.chunker import chunk_text
from app.documents.embeddings import build_embedding, retrieve_by_embedding
from app.documents.pdf_parser import extract_text_from_pdf_bytes
from app.documents.retrieval import retrieve_relevant_chunks
from app.documents.storage import StorageError, get_document_storage
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
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    VerifyEmailRequest,
)


settings = get_settings()
SESSION_COOKIE_NAME = "valinor_session"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("valinor.request")

rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.rate_limit_max_requests,
    window_seconds=settings.rate_limit_window_seconds,
    enabled=settings.rate_limit_enabled,
)

# As rotas de credencial (login, cadastro, verificação e redefinição) têm um
# limite próprio e bem mais estreito que o limite geral: são elas que um
# atacante repete para adivinhar senha ou varrer e-mails cadastrados. Fica
# ligado sempre, inclusive em desenvolvimento.
auth_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.auth_rate_limit_max_requests,
    window_seconds=settings.auth_rate_limit_window_seconds,
    enabled=True,
)

AUTH_RATE_LIMITED_PATHS = {
    "/auth/register",
    "/auth/login",
    "/auth/verify-email",
    "/auth/verify-email/resend",
    "/auth/password-reset",
    "/auth/password-reset/confirm",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Valinor",
    version="0.6.0",
    description=(
        "Procedimento autônomo, auditável e multi-modelo de resolução privada "
        "de disputas documentais B2B. O sistema não depende de revisão humana "
        "interna para concluir um procedimento e nunca é obrigado a declarar um "
        "vencedor. O resultado não constitui automaticamente sentença judicial "
        "ou arbitral."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_and_rate_limit(request: Request, call_next):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        headers = list(request.scope.get("headers", []))
        names = {name.lower() for name, _ in headers}
        if b"x-session-token" not in names:
            headers.append((b"x-session-token", token.encode("utf-8")))
        if b"x-actor-token" not in names:
            headers.append((b"x-actor-token", token.encode("utf-8")))
        request.scope["headers"] = headers

    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    client_key = request.client.host if request.client else "unknown"

    if request.url.path in AUTH_RATE_LIMITED_PATHS and request.method == "POST":
        allowed, retry_after = auth_rate_limiter.allow(f"auth:{client_key}")
        if not allowed:
            logger.warning(
                "auth_rate_limited request_id=%s client=%s path=%s",
                request_id,
                client_key,
                request.url.path,
            )
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Muitas tentativas de acesso a partir deste endereço. "
                        "Aguarde antes de tentar de novo."
                    )
                },
            )
            response.headers["Retry-After"] = str(int(retry_after) + 1)
            response.headers["X-Request-ID"] = request_id
            return response

    if rate_limiter.enabled:
        allowed, retry_after = rate_limiter.allow(client_key)
        if not allowed:
            logger.warning(
                "rate_limited request_id=%s client=%s path=%s",
                request_id,
                client_key,
                request.url.path,
            )
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Limite de requisições excedido. Tente novamente em instantes."
                },
            )
            response.headers["Retry-After"] = str(int(retry_after) + 1)
            response.headers["X-Request-ID"] = request_id
            return response

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "request_failed request_id=%s method=%s path=%s elapsed_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request request_id=%s method=%s path=%s status=%s elapsed_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


def _set_session_cookie(response: Response, token: str, max_age: int = 7 * 86400):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


def _case_or_404(db: Session, case_id: str):
    case = get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Caso não encontrado")
    return case


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _require_verified_email(user) -> None:
    """Nenhuma conta pratica atos no procedimento antes de comprovar o
    controle do e-mail. A leitura do caso continua liberada: a parte precisa
    conseguir ver o que está pendente enquanto confirma o endereço."""
    if not settings.email_verification_required:
        return
    if user is None or user.email_verified_at:
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Confirme seu e-mail antes de praticar atos no procedimento. "
            "Reenvie o link em /auth/verify-email/resend."
        ),
    )


def _require_actor(db: Session, case, token: str, expected_party: str):
    if settings.allow_role_tokens:
        stored_hash = getattr(case, f"{expected_party}_token_hash", None)
        if token and stored_hash and secrets.compare_digest(
            _hash_token(token), stored_hash
        ):
            return None
    user = get_user_by_token(db, token)
    if user and user_has_role(db, case.id, user.id, expected_party):
        _require_verified_email(user)
        return user

    raise HTTPException(
        status_code=403,
        detail=f"Credencial inválida para o papel {expected_party}",
    )


def _record_prompt_provenance(case_data: Dict, agent: str, stage: Dict) -> Dict:
    """Compara o prompt que rodou com o que o manifesto travou e anota a
    divergência na própria etapa. Um prompt trocado depois da trava deixa de
    ser invisível: aparece na etapa, no evento de auditoria e no relatório."""
    drift = detect_drift(case_data.get("locked_manifest"), agent)
    if drift:
        logger.warning(
            "prompt_drift agent=%s case=%s locked=%s running=%s",
            agent,
            case_data.get("id"),
            drift.get("locked_sha256"),
            drift.get("running_sha256"),
        )
        stage["execution"] = with_drift(stage.get("execution", {}), drift)
    return stage


def _assert_consent_terms_reproducible(case_data: Dict) -> None:
    """Impede travar o caso quando o aceite de alguma parte não pode mais ser
    reproduzido: versão ausente, desconhecida ou com hash diferente do texto
    publicado. Sem isso, o manifesto assinado registraria um consentimento que
    a plataforma não consegue mais exibir."""
    consent = case_data.get("consent") or {}
    for party in ("claimant", "respondent"):
        entry = consent.get(party) or {}
        version = entry.get("terms_version")
        recorded = entry.get("terms_sha256")
        if not version or not recorded:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O aceite de {party} foi registrado sem versão e hash dos "
                    "termos. Peça um novo aceite antes de travar o caso."
                ),
            )
        try:
            terms = get_terms(version)
        except TermsNotFound as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O aceite de {party} aponta para a versão de termos "
                    f"{version}, que não existe mais na plataforma."
                ),
            ) from exc
        if terms.sha256 != recorded:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O texto dos termos {version} mudou depois do aceite de "
                    f"{party}. Publique uma versão nova e colha novo aceite: "
                    "versões publicadas não podem ser editadas."
                ),
            )


def _assert_evidence_mutable(case) -> None:
    if case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="O registro documental está travado e não aceita alterações",
        )


def _public_case(case) -> Dict:
    data = case_to_dict(case, include_content=False, include_embeddings=False)
    decision = data.get("decision") or {}
    conclusion = data.get("procedure_conclusion") or decision.get("procedure_conclusion")
    execution_mode = decision.get("execution", {}).get("mode")
    if data.get("status", "").startswith("processing"):
        ai_status = "processing"
    elif conclusion in {"invalidated", "inadmissible", "system_failure"}:
        ai_status = conclusion
    elif execution_mode == "safe_fallback":
        ai_status = "unavailable"
    elif decision:
        ai_status = "completed"
    else:
        ai_status = "pending"
    data["ai_result_status"] = ai_status
    data["procedure_conclusion"] = conclusion
    data["model_independence_satisfied"] = settings.model_independence_satisfied
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
                "auditoria automática independente, verificador determinístico e recurso automático",
                "o sistema pode se abster; não há julgador humano interno",
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


def _send_verification(db: Session, user) -> Dict:
    """Emite e envia um novo link de verificação. No modo local (sem produção)
    o token volta na resposta para permitir testar sem SMTP configurado."""
    token, record = issue_auth_token(
        db,
        user,
        EMAIL_VERIFICATION,
        timedelta(hours=settings.email_verification_ttl_hours),
    )
    delivery = deliver_verification_email(
        to_email=user.email,
        display_name=user.display_name,
        token=token,
    )
    result = {
        "required": settings.email_verification_required,
        "verified": user.email_verified_at is not None,
        "expires_at": record.expires_at.isoformat(),
        "delivery": delivery,
    }
    if settings.allow_role_tokens:
        result["verification_token"] = token
        result["verification_path"] = f"/ui/?verify={token}"
    return result


@app.post("/auth/register", status_code=201)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = register_user(db, payload.display_name, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    verification = _send_verification(db, user)
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    return {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
        "email_verification": verification,
    }


@app.post("/auth/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = authenticate_user(db, payload.email, payload.password)
    except AccountLocked as locked:
        minutes = max(1, round(locked.retry_after_seconds / 60))
        raise HTTPException(
            status_code=429,
            detail=(
                "Conta temporariamente bloqueada por tentativas de senha "
                f"malsucedidas. Tente novamente em cerca de {minutes} min ou "
                "redefina a senha."
            ),
            headers={"Retry-After": str(locked.retry_after_seconds)},
        ) from locked
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    return {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
    }


@app.post("/auth/verify-email")
def verify_email(
    payload: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    try:
        user = consume_auth_token(db, payload.token, EMAIL_VERIFICATION)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    user = mark_email_verified(db, user)
    return {"message": "E-mail verificado", "user": user_to_dict(user)}


@app.post("/auth/verify-email/resend")
def resend_verification(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    user = _session_user_or_401(db, x_session_token)
    if user.email_verified_at:
        return {
            "message": "Este e-mail já está verificado",
            "email_verification": {"required": settings.email_verification_required, "verified": True},
        }
    return {
        "message": "Novo link de verificação enviado",
        "email_verification": _send_verification(db, user),
    }


@app.post("/auth/password-reset", status_code=202)
def request_password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    """Sempre responde igual, exista ou não a conta: a resposta não pode
    servir para descobrir quais e-mails estão cadastrados."""
    generic = {
        "message": (
            "Se existir uma conta com este e-mail, o link de redefinição foi "
            "enviado para ele."
        )
    }
    user = get_user_by_email(db, payload.email)
    if not user or not user.active:
        return generic

    token, _ = issue_auth_token(
        db,
        user,
        PASSWORD_RESET,
        timedelta(minutes=settings.password_reset_ttl_minutes),
    )
    deliver_password_reset_email(
        to_email=user.email,
        display_name=user.display_name,
        token=token,
    )
    if settings.allow_role_tokens:
        # Modo local: sem SMTP configurado o link precisa sair por algum
        # canal. Em produção isso nunca é exposto.
        return {**generic, "reset_token": token, "reset_path": f"/ui/?reset={token}"}
    return generic


@app.post("/auth/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = consume_auth_token(db, payload.token, PASSWORD_RESET)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    user = set_password(db, user, payload.password)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
    )
    return {
        "message": (
            "Senha redefinida. Todas as sessões abertas foram encerradas: "
            "entre novamente com a nova senha."
        ),
        "user": user_to_dict(user),
    }


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
        SESSION_COOKIE_NAME,
        path="/",
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
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
    _require_verified_email(user)
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
    if user:
        add_member(db, case.id, user.id, "manager")
        db.expire_all()
        case = get_case(db, case.id)
    result = case_to_dict(case, include_content=False, include_embeddings=False)
    if not settings.auth_required:
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
    email_delivery = deliver_invitation_email(
        to_email=invitation.email,
        role=invitation.role,
        case_title=case.title,
        token=token,
    )
    result = invitation_to_dict(invitation)
    result["email_delivery"] = email_delivery
    # O token de aceite só é exposto na resposta no modo local. Em produção o
    # convite chega exclusivamente pelo e-mail transacional, evitando que o
    # segredo trafegue por outro canal.
    if settings.allow_role_tokens:
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
    # O convite é entregue exclusivamente por e-mail e vinculado ao endereço:
    # apresentá-lo prova o controle da caixa, o mesmo que a verificação faria.
    if not settings.allow_role_tokens:
        user = mark_email_verified(db, user)
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


@app.get("/terms")
def get_current_terms():
    """Texto vigente dos termos, com versão e hash. É este texto que a parte
    precisa ver antes de aceitar."""
    return {**current_terms().as_dict(), "available_versions": list_terms_versions()}


@app.get("/terms/{version}")
def get_terms_version(version: str):
    try:
        terms = get_terms(version)
    except TermsNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Versão de termos desconhecida: {version}",
        ) from exc
    return {
        **terms.as_dict(),
        "current": version == current_terms().version,
        "available_versions": list_terms_versions(),
    }


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
    try:
        terms = get_terms(payload.terms_version)
    except TermsNotFound as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Versão de termos desconhecida: {payload.terms_version}. "
                "Recarregue os termos vigentes em /terms antes de aceitar."
            ),
        ) from exc
    updated = record_consent(
        db,
        case,
        party=payload.party,
        accepted=payload.accepted,
        terms_version=terms.version,
        terms_sha256=terms.sha256,
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
        original_bytes=file_bytes,
        original_filename=filename,
        original_media_type="application/pdf",
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
    _assert_evidence_mutable(case)
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
    _assert_evidence_mutable(case)
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
    _assert_evidence_mutable(case)
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


@app.get("/cases/{case_id}/documents/{document_id}/original")
def download_document_original(
    case_id: str,
    document_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    document = _document_or_404(db, case_id, document_id)
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


@app.post("/cases/{case_id}/documents/{document_id}/original-url")
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
    if not document.original_key:
        raise HTTPException(
            status_code=404,
            detail="Este documento não possui arquivo original armazenado",
        )
    ttl = settings.download_url_ttl_seconds
    token, expires_at = sign_download_token(
        key=document.original_key,
        filename=document.name,
        media_type=document.original_media_type or "application/octet-stream",
        expires_in=ttl,
    )
    return {
        "url": f"{settings.public_base_url}/documents/download?token={token}",
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "expires_in": ttl,
    }


@app.get("/documents/download")
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
    _assert_consent_terms_reproducible(case_data)

    try:
        claimed = claim_case_stage(db, case, "lock")
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        if case.manifest_locked:
            return {
                "message": "Manifesto já estava travado",
                "manifest": case_to_dict(case)["locked_manifest"],
            }
        raise HTTPException(status_code=409, detail="Trava do manifesto já em andamento")

    manifest = lock_case_manifest(case_to_dict(case))
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
    manifest = case_to_dict(case, include_content=False)["locked_manifest"]
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
    events = case_to_dict(case, include_content=False)["audit_log"]
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
    return case_to_dict(
        case, include_content=False, include_embeddings=False
    )["chunks"]


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
    return _retrieve(case_to_dict(case, include_content=False), query, method)


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
    conciliation = _record_prompt_provenance(
        case_data,
        "conciliator",
        assess_conciliation(context, round_number),
    )
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
    try:
        claimed = claim_case_stage(
            db,
            case,
            "organize",
            extra_from_statuses=("conciliation", "locked"),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        organized = case_to_dict(case).get("organized")
        if organized:
            return organized
        raise HTTPException(status_code=409, detail="Organização já em andamento")

    organized = _record_prompt_provenance(
        case_data,
        "organizer",
        organizer_organize_case(
            documents=case_data["documents"],
            chunks=case_data["chunks"],
        ),
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
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
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
    try:
        claimed = claim_case_stage(
            db,
            case,
            "decide",
            extra_from_statuses=("organized",),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        existing = case_to_dict(case).get("decision")
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Decisão já em processamento")

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
    decision, verification, conclusion = generate_and_verify_decision(
        db,
        case,
        case_data,
        decision_context,
        role="judge",
        idempotency_key=idempotency_key or None,
    )
    decision = _record_prompt_provenance(case_data, "judge", decision)
    stability = maybe_run_stability(db, case, case_data, decision_context, decision)
    if stability and not stability.get("stable"):
        decision["procedure_conclusion"] = "inconclusive"
        decision.setdefault("abstention_reasons", [])
        if "unstable_decision" not in decision["abstention_reasons"]:
            decision["abstention_reasons"].append("unstable_decision")
        if "material_model_disagreement" not in decision["abstention_reasons"]:
            decision["abstention_reasons"].append("material_model_disagreement")
        conclusion = "inconclusive"
        append_audit(
            db,
            case,
            "decision_unstable",
            {"disagreements": stability.get("material_disagreements") or []},
        )
    case.procedure_conclusion = conclusion
    case.stability_json = (
        __import__("json").dumps(stability, ensure_ascii=False) if stability else case.stability_json
    )
    status = "invalidated" if conclusion == "invalidated" else "decided"
    save_stage(
        db,
        case,
        field="decision_json",
        value=decision,
        status=status,
        event_type="decision_generated",
        event_payload={
            "outcome": decision.get("outcome"),
            "confidence": decision.get("confidence"),
            "procedure_conclusion": conclusion,
            "verification_valid": verification.get("valid"),
            "execution": decision.get("execution", {}),
        },
    )
    return public_decision_view(decision)


@app.post("/cases/{case_id}/review")
def review_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
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
    try:
        claimed = claim_case_stage(
            db,
            case,
            "review",
            extra_from_statuses=("decided", "invalidated", "inconclusive"),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        existing = case_to_dict(case).get("review")
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Auditoria já em processamento")

    verification = case_data.get("verification") or {}
    review = _record_prompt_provenance(
        case_data,
        "reviewer",
        run_automatic_review(db, case, case_data, case_data["decision"], verification),
    )

    reconstruction_used = False
    decision = case_data["decision"]
    conclusion, decision = finalize_review_outcome(
        decision, verification, review, reconstruction_used
    )
    if conclusion == "pending_reconstruction":
        reconstruction_used = True
        new_input = {
            "manifest": case_data["locked_manifest"],
            "conciliation_rounds": case_data["conciliation_rounds"],
            "organized_case": case_data["organized"],
            "retrieved_evidence": {
                "delivery": _retrieve(
                    case_data, "obrigações de entrega e cumprimento parcial"
                ),
                "payment": _retrieve(
                    case_data, "condições de pagamento e proporcionalidade"
                ),
                "deadline": _retrieve(case_data, "cumprimento de prazo e atraso"),
            },
            "reconstruction": True,
        }
        decision, verification, _conclusion, review = reconstruct_once(
            db,
            case,
            case_data,
            new_input,
            case.current_decision_run_id,
        )
        review = _record_prompt_provenance(case_data, "reviewer", review)
        conclusion, decision = finalize_review_outcome(
            decision, verification, review, reconstruction_used=True
        )
        # A decisão original permanece no DecisionRun version=1. A corrente
        # aponta para a reconstrução, sem apagar o registro anterior.
        save_stage(
            db,
            case,
            field="decision_json",
            value=decision,
            status="decided",
            event_type="decision_reconstructed",
            event_payload={
                "outcome": decision.get("outcome"),
                "procedure_conclusion": conclusion,
                "supersedes_id": case.current_decision_run_id,
            },
        )

    case.procedure_conclusion = (
        conclusion if conclusion != "pending_reconstruction" else decision.get("procedure_conclusion")
    )
    save_stage(
        db,
        case,
        field="review_json",
        value=review,
        status="reviewed",
        event_type="review_generated",
        event_payload={
            "approved": review.get("approved"),
            "outcome": review.get("outcome"),
            "procedure_conclusion": case.procedure_conclusion,
            "reconstruction_used": reconstruction_used,
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

    return attestation


@app.get("/cases/{case_id}/attestation")
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


@app.get("/cases/{case_id}/attestation/nostr-anchor")
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
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
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
    if case_data["contest"]["contested"] or case.contested_at:
        existing = find_appeal_by_idempotency(db, case.id, idempotency_key)
        if existing:
            return {
                **case_data["contest"],
                "appeal": existing.result_json and __import__("json").loads(existing.result_json),
                "appeal_id": existing.id,
            }
        return {
            **case_data["contest"],
            "appeal": (case_data.get("appeals") or [None])[-1],
        }

    try:
        claimed = claim_case_stage(
            db,
            case,
            "appeal",
            extra_from_statuses=("reviewed",),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        refreshed = case_to_dict(case)
        return {
            **refreshed["contest"],
            "appeal": (refreshed.get("appeals") or [None])[-1],
        }

    window_ends = datetime.fromisoformat(attestation["contest_window_ends_utc"])
    if datetime.now(window_ends.tzinfo) > window_ends:
        raise HTTPException(
            status_code=409,
            detail="A janela de contestação já se encerrou",
        )

    explanation = payload.resolved_explanation()
    grounds = payload.resolved_grounds()
    if settings.max_appeals_per_attestation <= count_appeals(db, case.id):
        raise HTTPException(
            status_code=409,
            detail="O limite de recursos automáticos deste caso já foi atingido",
        )

    findings = {
        item.get("finding_id")
        for item in (case_data.get("decision") or {}).get("material_findings") or []
        if isinstance(item, dict)
    }
    unknown_findings = [
        item for item in payload.challenged_finding_ids if item not in findings
    ]
    if unknown_findings and findings:
        raise HTTPException(
            status_code=422,
            detail="Finding impugnado não existe na decisão",
        )
    manifest_doc_ids = {
        item.get("id")
        for item in (case_data.get("locked_manifest") or {}).get("documents") or []
    }
    for ref in payload.evidence_refs:
        document_id = ref.get("document_id") if isinstance(ref, dict) else None
        if document_id and manifest_doc_ids and document_id not in manifest_doc_ids:
            raise HTTPException(
                status_code=422,
                detail="Evidência do recurso não pertence ao manifesto",
            )

    original_hash = ((case_data.get("decision") or {}).get("provenance") or {}).get(
        "decision_payload_hash"
    ) or canonical_hash(case_data.get("decision") or {})
    appeal = persist_appeal(
        db,
        case,
        filed_by=actor_role,
        grounds=grounds,
        original_decision_hash=original_hash,
        idempotency_key=idempotency_key or None,
        status="processing",
    )
    updated = register_contest(db, case, actor_role, explanation)
    contest_payload = {
        "grounds": grounds,
        "explanation": explanation,
        "challenged_finding_ids": payload.challenged_finding_ids,
        "evidence_refs": payload.evidence_refs,
        "requested_correction": payload.requested_correction,
        "filed_by": actor_role,
    }
    result = run_appeal(db, updated, case_to_dict(updated), appeal, contest_payload)
    db.commit()
    refreshed = case_to_dict(get_case(db, case_id))
    return {
        **refreshed["contest"],
        "appeal": result,
        "grounds": grounds,
    }


@app.get("/cases/{case_id}/verification")
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


@app.get("/cases/{case_id}/appeals")
def get_appeals(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_content=False).get("appeals") or []


@app.get("/frameworks")
def get_frameworks():
    return [item.lock_summary() for item in list_frameworks()]


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
