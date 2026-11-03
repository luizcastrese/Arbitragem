"""Guardas e utilidades compartilhadas pelas rotas: autorização por papel,
leitura do caso e cookie de sessão.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Dict, List

from fastapi import HTTPException, Response
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.core.config import get_settings
from app.db.access_repository import get_user_by_token, user_case_ids, user_has_role
from app.db.repository import case_to_dict, get_case, get_document
from app.documents.embeddings import retrieve_by_embedding
from app.documents.retrieval import retrieve_relevant_chunks
from app.domain.steward import steward_actuator_token


def _set_session_cookie(response: Response, token: str, max_age: int = 7 * 86400):
    response.set_cookie(
        key=ctx.SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=ctx.settings.is_production,
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
    if not ctx.settings.email_verification_required:
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
    if ctx.settings.allow_role_tokens:
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


def _assert_procedure_open(case) -> None:
    """Depois da opção pela via judicial, o caso só pode ser lido e auditado."""
    if case.status == "withdrawn":
        raise HTTPException(
            status_code=409,
            detail=(
                "O caso foi encerrado porque uma parte optou pela via judicial. "
                "O histórico continua disponível no auto e na trilha de auditoria."
            ),
        )


def _require_steward_actuator(token: str) -> None:
    """O atuador das etapas é o processo do gestor, não a sessão de uma parte."""
    expected = steward_actuator_token()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=403,
            detail=(
                "O gestor do procedimento é a IA da Valinor. "
                "As partes não conduzem esta etapa."
            ),
        )


def _model_stages_enabled(header: str) -> bool:
    """Em produção o gestor sempre segue para a etapa de modelo.

    Fora de produção, `X-Steward-Run-Models: 0` pausa essa sequência para
    que um teste observe o caso travado antes da composição. A sessão de
    uma parte não escolhe o mérito: só impede o agendamento.
    """
    if get_settings().is_production:
        return True
    return (header or "1").strip() != "0"


def _require_procedure_party(db: Session, case, token: str) -> str:
    """Autoriza convite e prazo por qualquer uma das duas partes.

    O papel de gestor humano não conduz mais o rito. O token legado só
    permanece para casos antigos nestes atos de coordenação entre as partes.
    """
    for party in ("claimant", "respondent"):
        try:
            _require_actor(db, case, token, party)
            return party
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
    try:
        _require_actor(db, case, token, "manager")
        return "manager"
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
    raise HTTPException(
        status_code=403,
        detail="Somente as partes do caso podem conduzir o procedimento",
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
    data["model_independence_satisfied"] = ctx.settings.model_independence_satisfied
    data["documents_count"] = len(data.pop("documents"))
    data.pop("chunks", None)
    data.pop("audit_log", None)
    data.pop("locked_manifest", None)
    data.pop("conciliation", None)
    data.pop("conciliation_rounds", None)
    data.pop("organized", None)
    data.pop("decision", None)
    data.pop("original_decision", None)
    data.pop("review", None)
    data.pop("attestation", None)
    return data


def _session_user_or_401(db: Session, x_session_token: str):
    user = get_user_by_token(db, x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Sessão ausente, inválida ou expirada")
    return user


def _require_admin(db: Session, x_session_token: str):
    """Painel de operação: conta listada em ADMIN_EMAILS, com sessão válida e
    (quando a confirmação é exigida) e-mail confirmado. Não há token por papel
    nem atalho de desenvolvimento: sem sessão, não entra."""
    user = _session_user_or_401(db, x_session_token)
    if not ctx.settings.is_admin_email(user.email):
        raise HTTPException(status_code=403, detail="Acesso restrito à operação")
    if ctx.settings.email_verification_required and not user.email_verified_at:
        raise HTTPException(
            status_code=403,
            detail="Confirme o e-mail da conta antes de usar o painel de operação",
        )
    return user


def _require_case_view(db: Session, case, x_session_token: str):
    if not ctx.settings.auth_required:
        return get_user_by_token(db, x_session_token)
    user = _session_user_or_401(db, x_session_token)
    if case.id not in set(user_case_ids(db, user.id)):
        raise HTTPException(status_code=403, detail="Sua conta não participa deste caso")
    return user


def _document_or_404(db: Session, case_id: str, document_id: str):
    document = get_document(db, case_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return document


def _assert_not_purged(document) -> None:
    """410 e não 404: o documento existiu e seu hash continua no registro; o
    que saiu foram os bytes, pela política de retenção."""
    if getattr(document, "content_purged_at", None):
        raise HTTPException(
            status_code=410,
            detail=(
                "O conteúdo deste documento foi expurgado pela política de "
                "retenção. Os metadados e o hash permanecem no registro do "
                "caso, que segue verificável."
            ),
        )


def _counterparty(document) -> str:
    return "respondent" if document.submitted_by == "claimant" else "claimant"


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
