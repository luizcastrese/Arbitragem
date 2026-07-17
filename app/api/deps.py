"""Dependências e helpers compartilhados entre os routers da API.

Concentra a lógica transversal (autorização por papel, resolução de caso/
documento, processamento de material e recuperação de trechos) que antes vivia
diretamente em ``app/main.py``.
"""

from datetime import datetime
import hashlib
import secrets
from typing import Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.hashing import sha256_text
from app.db.access_repository import (
    create_notification,
    get_user_by_token,
    user_case_ids,
    user_has_role,
)
from app.db.repository import (
    add_document as persist_document,
    case_to_dict,
    document_to_dict,
    get_case,
    get_document,
)
from app.db.session import get_db  # noqa: F401  (re-exportado para os routers)
from app.documents.chunker import chunk_text
from app.documents.embeddings import build_embedding, retrieve_by_embedding
from app.documents.retrieval import retrieve_relevant_chunks

API_VERSION = "0.5.0"

settings = get_settings()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _case_or_404(db: Session, case_id: str):
    case = get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Caso não encontrado")
    return case


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


def _document_or_404(db: Session, case_id: str, document_id: str):
    document = get_document(db, case_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return document


def _counterparty(document) -> str:
    return "respondent" if document.submitted_by == "claimant" else "claimant"
