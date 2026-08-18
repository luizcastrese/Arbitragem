from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
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

from app.core.attestation import public_key_info, verify_attestation
from app.core.audit import verify_audit_chain
from app.core.canonical import canonical_hash
from app.core.config import get_settings
from app.core.email import build_accept_url, deliver_invitation_email
from app.core.hashing import sha256_text
from app.core.procedure import (
    PARTIES,
    advance as advance_procedure,
    counterparty as party_counterparty,
    retrieve_admitted_chunks,
    state as procedure_state,
)
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.signed_url import (
    SignedUrlError,
    sign_download_token,
    verify_download_token,
)
from app.core.signing import verify_signature
from app.db.access_repository import (
    accept_invitation,
    add_member,
    authenticate_user,
    case_roles_taken,
    create_invitation,
    create_notification,
    create_session,
    deadline_to_dict,
    get_invitation,
    get_user_by_token,
    invitation_to_dict,
    pending_invitation_roles,
    register_user,
    reissue_invitation,
    revoke_session,
    user_case_ids,
    user_has_role,
    user_to_dict,
)
from app.db.init_db import init_db
from app.db.repository import (
    add_document as persist_document,
    acknowledge_document as persist_acknowledgement,
    case_to_dict,
    create_case as persist_case,
    document_to_dict,
    get_document,
    get_case,
    list_cases,
    load_document_content,
    load_document_original,
    record_composition_closure,
    record_composition_input,
    record_consent,
    record_ratification,
    record_submission_closure,
    register_contest,
    respond_to_document as persist_response,
    append_audit,
)
from app.db.session import get_db
from app.documents.chunker import chunk_text
from app.documents.embeddings import build_embedding
from app.documents.pdf_parser import extract_text_from_pdf_bytes
from app.documents.storage import StorageError, get_document_storage
from app.reports.report_generator import build_report
from app.reports.docx_generator import build_docx_report
from app.schemas import (
    AcceptInvitationRequest,
    AddDocumentRequest,
    AttestationVerifyRequest,
    CompositionPositionRequest,
    ConsentRequest,
    ContestRequest,
    CreateCaseRequest,
    EvidenceActionRequest,
    InvitationRequest,
    LoginRequest,
    RatificationRequest,
    RegisterRequest,
    SubmissionClosureRequest,
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

    if rate_limiter.enabled:
        client_key = request.client.host if request.client else "unknown"
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


def _require_actor(db: Session, case, token: str, expected_party: str):
    """Só as duas partes atuam no caso. O procedimento não tem terceiro
    humano: nenhum papel além de `claimant` e `respondent` é aceitável."""
    if expected_party not in PARTIES:
        raise HTTPException(
            status_code=403,
            detail="Este procedimento não tem terceiro humano; só as partes atuam",
        )
    if settings.allow_role_tokens:
        stored_hash = getattr(case, f"{expected_party}_token_hash", None)
        if token and stored_hash and secrets.compare_digest(
            _hash_token(token), stored_hash
        ):
            return None
    user = get_user_by_token(db, token)
    if user and user_has_role(db, case.id, user.id, expected_party):
        return user

    raise HTTPException(
        status_code=403,
        detail=f"Credencial inválida para o papel {expected_party}",
    )


def _actor_party(db: Session, case, token: str) -> str:
    """Descobre qual das duas partes está agindo, sem confiar no corpo da
    requisição. Uma parte nunca fala pela outra."""
    for party in PARTIES:
        try:
            _require_actor(db, case, token, party)
            return party
        except HTTPException:
            continue
    raise HTTPException(
        status_code=403,
        detail="Apenas o cliente reclamante ou a empresa reclamada podem agir no caso",
    )


def _advance_and_reload(db: Session, case_id: str) -> Dict:
    """Deixa o rito avançar tudo o que já pode avançar e devolve o caso."""
    case = _case_or_404(db, case_id)
    advance_procedure(db, case)
    return case_to_dict(
        _case_or_404(db, case_id),
        include_content=False,
        include_embeddings=False,
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
    if method not in {"embedding", "lexical"}:
        raise HTTPException(
            status_code=400,
            detail="Método deve ser 'embedding' ou 'lexical'",
        )
    return retrieve_admitted_chunks(case_data, query, method=method)


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
    if getattr(case, f"{submitted_by}_submission_closed", False):
        raise HTTPException(
            status_code=409,
            detail=(
                "Você declarou encerrada a sua produção de material. "
                "Reabra a produção antes de apresentar algo novo."
            ),
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
    result = document_to_dict(document, include_content=False)
    # O rito abre em seguida o prazo de ciência e resposta da contraparte.
    advance_procedure(db, case)
    return result


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
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = register_user(db, payload.display_name, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    return {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
    }


@app.post("/auth/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    return {
        "user": user_to_dict(user),
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
    credentials = {
        "claimant": secrets.token_urlsafe(24),
        "respondent": secrets.token_urlsafe(24),
    }
    case = persist_case(
        db,
        title=payload.title,
        claimant=payload.claimant,
        respondent=payload.respondent,
        claimant_token_hash=_hash_token(credentials["claimant"]),
        respondent_token_hash=_hash_token(credentials["respondent"]),
        created_by=payload.creator_role,
    )
    # Quem abre o caso entra como parte, do lado que declarou. Ninguém
    # administra o próprio litígio: o rito é que conduz o procedimento.
    if user:
        add_member(db, case.id, user.id, payload.creator_role)
        db.expire_all()
        case = get_case(db, case.id)
    result = case_to_dict(case, include_content=False, include_embeddings=False)
    if not settings.auth_required:
        result["access_credentials"] = credentials
    return result


def _invitation_result(invitation, token: str, email_delivery: Dict) -> Dict:
    """Devolve o convite com o link de aceite para quem convidou.

    O rito não tem operador humano: as duas partes são as únicas pessoas do
    procedimento. Se o link só existisse dentro do e-mail transacional, um
    deploy sem SMTP — ou uma entrega que falha, cai em spam ou vai para um
    endereço digitado errado — deixaria o caso parado para sempre, porque o
    token não é recuperável nem pelo banco (guarda-se apenas o hash).

    Entregar o link a quem convidou não afrouxa o vínculo do convite: aceitar
    continua exigindo uma conta com exatamente aquele e-mail, e quem convida
    não pode ocupar o outro polo do caso. Quem controla o endereço convidado
    segue sendo o único que consegue entrar.
    """
    result = invitation_to_dict(invitation)
    result["email_delivery"] = email_delivery
    result["acceptance_url"] = build_accept_url(settings.public_base_url, token)
    result["acceptance_path"] = f"/ui/?invite={token}"
    if settings.allow_role_tokens:
        result["acceptance_token"] = token
    return result


@app.get("/cases/{case_id}/invitations")
def get_invitations(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _actor_party(db, case, x_actor_token)
    return [invitation_to_dict(item) for item in case.invitations]


@app.post("/cases/{case_id}/invitations", status_code=201)
def invite_participant(
    case_id: str,
    payload: InvitationRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Uma parte convida a contraparte. Não há convite para terceiro: o único
    terceiro do procedimento é o próprio rito."""
    case = _case_or_404(db, case_id)
    actor_party = _actor_party(db, case, x_actor_token)
    actor = get_user_by_token(db, x_actor_token)
    if actor and payload.email.strip().lower() == actor.email:
        raise HTTPException(
            status_code=403,
            detail=(
                "O convite é para a contraparte. As duas partes precisam ser "
                "pessoas distintas."
            ),
        )
    if payload.role != party_counterparty(actor_party):
        raise HTTPException(
            status_code=403,
            detail=(
                "Só é possível convidar a contraparte: "
                f"{party_counterparty(actor_party)}"
            ),
        )
    if payload.role in case_roles_taken(db, case.id):
        raise HTTPException(
            status_code=409,
            detail=f"O papel {payload.role} já está ocupado neste caso",
        )
    if payload.role in pending_invitation_roles(db, case.id):
        raise HTTPException(
            status_code=409,
            detail=f"Já existe um convite pendente para o papel {payload.role}",
        )
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
        {
            "email": invitation.email,
            "role": invitation.role,
            "invitation_id": invitation.id,
            "actor": actor_party,
        },
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
    return _invitation_result(invitation, token, email_delivery)


@app.post("/cases/{case_id}/invitations/{invitation_id}/resend")
def resend_invitation(
    case_id: str,
    invitation_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Emite um link novo para um convite que ainda não foi aceito.

    O token anterior só existiu em claro no momento da criação. Sem esta rota,
    quem convidou e perdeu o link fica preso: o papel já tem convite pendente,
    então uma nova tentativa colide em 409 e a contraparte nunca entra.
    """
    case = _case_or_404(db, case_id)
    actor_party = _actor_party(db, case, x_actor_token)
    actor = get_user_by_token(db, x_actor_token)
    invitation = get_invitation(db, case.id, invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    if invitation.role != party_counterparty(actor_party):
        raise HTTPException(
            status_code=403,
            detail="Só é possível reemitir o convite da contraparte",
        )
    try:
        token, invitation = reissue_invitation(
            db, invitation, actor.id if actor else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    append_audit(
        db,
        case,
        "invitation_reissued",
        {
            "email": invitation.email,
            "role": invitation.role,
            "invitation_id": invitation.id,
            "actor": actor_party,
        },
    )
    db.commit()
    email_delivery = deliver_invitation_email(
        to_email=invitation.email,
        role=invitation.role,
        case_title=case.title,
        token=token,
    )
    return _invitation_result(invitation, token, email_delivery)


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
        {
            "user_id": user.id,
            "role": invitation.role,
            "invitation_id": invitation.id,
            "actor": invitation.role,
        },
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


# A agenda processual não tem mais um criador humano: o rito abre o prazo de
# ciência e resposta quando um material é disponibilizado e dá baixa nele
# quando a contraparte se manifesta. Ver `app.core.procedure`.


@app.get("/cases/{case_id}/procedure")
def get_procedure_state(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Estado do rito: em que etapa o caso está e o que ele espera, de quem.
    Enquanto houver pendência aqui, ela é sempre de uma das partes."""
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return procedure_state(case_to_dict(case, include_content=False))


@app.post("/cases/{case_id}/advance")
def advance_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Pede ao rito que execute tudo o que já pode ser executado.

    Não concede poder nenhum a quem chama: cada passo continua condicionado às
    suas próprias pré-condições. As partes chamam este endpoint apenas para
    não precisarem esperar o próximo ato de alguém.
    """
    case = _case_or_404(db, case_id)
    _actor_party(db, case, x_actor_token)
    return advance_procedure(db, case)


@app.post("/cases/{case_id}/submission-complete")
def close_submission(
    case_id: str,
    payload: SubmissionClosureRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte declara que encerrou a própria produção de material.

    Quando as duas encerram — e o contraditório está completo — o rito trava o
    manifesto sozinho. Este é o sinal que substitui o julgamento do gestor
    humano sobre quando o acervo está pronto.
    """
    case = _case_or_404(db, case_id)
    actor_party = _actor_party(db, case, x_actor_token)
    _assert_evidence_mutable(case)
    if payload.closed and not case.documents:
        raise HTTPException(
            status_code=409,
            detail="Não é possível encerrar a produção antes de haver material no caso",
        )
    record_submission_closure(db, case, actor_party, payload.closed)
    return _advance_and_reload(db, case_id)


@app.post("/cases/{case_id}/composition/position")
def submit_composition_position(
    case_id: str,
    payload: CompositionPositionRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte registra sua própria posição para a próxima rodada. Cada lado
    fala por si — ninguém redige a manifestação do outro."""
    case = _case_or_404(db, case_id)
    actor_party = _actor_party(db, case, x_actor_token)
    if not case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="A composição começa depois que o registro documental é travado",
        )
    data = case_to_dict(case, include_content=False)
    if data["organized"]:
        raise HTTPException(
            status_code=409,
            detail="A fase de composição foi encerrada porque o julgamento já começou",
        )
    if data["composition"]["closed"]:
        raise HTTPException(
            status_code=409,
            detail="A composição já foi encerrada neste caso",
        )
    record_composition_input(db, case, actor_party, payload.position)
    return _advance_and_reload(db, case_id)


@app.post("/cases/{case_id}/composition/close")
def close_composition(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte encerra a composição. Ela é voluntária: basta um dos lados não
    querer mais rodadas para o rito seguir para o julgamento."""
    case = _case_or_404(db, case_id)
    actor_party = _actor_party(db, case, x_actor_token)
    if not case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="A composição começa depois que o registro documental é travado",
        )
    record_composition_closure(db, case, actor_party)
    return _advance_and_reload(db, case_id)


@app.post("/cases/{case_id}/ratification")
def ratify_decision(
    case_id: str,
    payload: RatificationRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte revisa a decisão que a auditoria ressalvou.

    Esta é a revisão humana do procedimento. Ela não cabe a um terceiro — não
    há terceiro —, e sim a quem é titular do conflito: informadas da ressalva,
    as duas partes decidem se o resultado vale assim mesmo. Só o aceite das
    duas destrava a execução; a recusa de qualquer uma encerra o caso sem
    decisão executável.
    """
    case = _case_or_404(db, case_id)
    actor_party = _actor_party(db, case, x_actor_token)
    data = case_to_dict(case, include_content=False)
    if not data["ratification"]["open"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "Não há ratificação em aberto neste caso"
                if not data["ratification"]["outcome"]
                else "A fase de ratificação já foi encerrada"
            ),
        )
    if data["ratification"][actor_party]["answered"]:
        raise HTTPException(
            status_code=409,
            detail="Você já se manifestou sobre esta decisão",
        )
    record_ratification(
        db, case, actor_party, payload.accepted, payload.reason
    )
    return _advance_and_reload(db, case_id)


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
    record_consent(
        db,
        case,
        party=payload.party,
        accepted=payload.accepted,
        terms_version=payload.terms_version,
    )
    return _advance_and_reload(db, case_id)["consent"]


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
    return _advance_and_reload(db, case_id)


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
    # A admissão vem em seguida, pelo próprio rito: cumprido o contraditório,
    # ela é consequência automática, não um juízo de terceiro.
    return _advance_and_reload(db, case_id)


@app.get("/cases/{case_id}/documents/{document_id}/content")
def read_document_content(
    case_id: str,
    document_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """O teor integral do material, para quem participa do caso.

    Sem isto o contraditório é cerimônia: a parte confirma ciência e responde
    a um documento que não tem como ler. Como o prazo de resposta corre contra
    quem recebe o material e o silêncio preclui, a leitura precisa ser um
    direito do caso — e não uma cortesia de quem apresentou.
    """
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    document = _document_or_404(db, case_id, document_id)
    if not document.disclosed_at:
        raise HTTPException(status_code=409, detail="Material ainda não disponibilizado")
    return {
        "id": document.id,
        "name": document.name,
        "sha256": document.sha256,
        "submitted_by": document.submitted_by,
        "material_type": document.material_type,
        "purpose": document.purpose,
        "has_original": bool(document.original_key),
        "content": load_document_content(document),
    }


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


# A trava do manifesto é ato do rito, não de uma pessoa. Ela acontece sozinha
# quando as duas partes aceitaram o procedimento, encerraram a produção de
# material e o contraditório se completou. Ver `app.core.procedure._lock_manifest`.


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


def _anchors_consistent(events: List[Dict], anchors: List[Dict]) -> bool:
    """Confere a cadeia atual contra cada topo já ancorado publicamente.

    Uma reescrita completa da cadeia no banco continua passando em
    `verify_audit_chain` — o encadeamento é recalculável por qualquer um, já
    que não há segredo nele. O que não é recalculável é o que já foi publicado:
    o evento na posição ancorada tem que exibir exatamente o hash que a âncora
    registrou. Se divergir, a cadeia de hoje não é a de então.

    Continua sendo uma verificação local, e um adversário com escrita no banco
    pode reescrever também as âncoras guardadas aqui. Contra isso vale a cópia
    no relay, fora do alcance da plataforma — por isso `head_hash` e os
    `event_id` das âncoras são devolvidos junto: é o que permite a um terceiro
    refazer esta mesma conferência sem depender deste servidor.
    """
    for anchor in anchors:
        position = anchor.get("event_count")
        expected = anchor.get("audit_head_hash")
        if not position or not expected:
            continue
        if position > len(events):
            return False
        if events[position - 1].get("event_hash") != expected:
            return False
    return True


@app.get("/cases/{case_id}/audit")
def get_audit(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    data = case_to_dict(case, include_content=False)
    events = data["audit_log"]
    valid, errors = verify_audit_chain(events)
    anchors = data["audit_anchors"]
    return {
        "valid": valid,
        "errors": errors,
        # O topo é o que as âncoras públicas comprometem. Um verificador
        # externo compara este valor com o que está no relay: se a cadeia foi
        # reescrita por inteiro no banco — algo que a verificação local não
        # detecta, por não haver segredo nela —, os dois deixam de bater.
        "head_hash": events[-1]["event_hash"] if events else "",
        "event_count": len(events),
        "anchors": anchors,
        "anchors_consistent": _anchors_consistent(events, anchors),
        "events": events,
    }


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


# Composição, organização, decisão e auditoria deixaram de ter um gatilho
# humano. O rito conduz cada uma delas quando as pré-condições da etapa
# anterior estão satisfeitas, e as partes participam pelo que é delas:
# `POST /cases/{id}/composition/position` e `/composition/close`.
# Ver `app.core.procedure`.


@app.get("/.well-known/valinor-signing-key")
def signing_key():
    settings_now = get_settings()
    if not settings_now.attestation_enabled:
        raise HTTPException(
            status_code=404,
            detail="A emissão de attestations não está habilitada nesta instância",
        )
    return public_key_info()


# A attestation também é emitida pelo rito, assim que a decisão passa pela
# auditoria independente e a cadeia de auditoria fecha. Um caso inconclusivo,
# reprovado na auditoria ou que exige revisão humana simplesmente não gera
# attestation. Ver `app.core.procedure._issue_attestation`.


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
    # Quem ratificou já exerceu sua revisão sobre o mérito. Contestar depois
    # seria voltar atrás do próprio aceite — e a ratificação é justamente o
    # fundamento sobre o qual esta attestation foi emitida.
    if case_data["ratification"][actor_role]["accepted"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "Você ratificou esta decisão. A ratificação é o fundamento da "
                "attestation e não pode ser contestada em seguida."
            ),
        )

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
