import json
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, selectinload

from app.core.audit import build_audit_event
from app.core.encryption import decrypt_chunk_text, encrypt_chunk_text
from app.db.access_repository import deadline_to_dict, invitation_to_dict, notification_to_dict
from app.db.models import (
    AttestationRecord,
    AuditEvent,
    AutomaticAppeal,
    AutomaticReviewRun,
    Case,
    CaseMember,
    Chunk,
    DecisionRun,
    DecisionVerification,
    Document,
    LLMExecution,
)
from app.domain.legacy import public_decision_view, public_review_view
from app.documents.storage import (
    StorageError,
    build_content_key,
    build_original_key,
    get_document_storage,
)


def _json_dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def _conciliation_rounds(value: Any) -> List[Dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        legacy_round = dict(value)
        legacy_round.setdefault("round_number", 1)
        legacy_round.setdefault("continue_recommended", False)
        legacy_round.setdefault("recommended_additional_rounds", 0)
        legacy_round.setdefault("next_round_focus", "")
        legacy_round.setdefault(
            "stop_reason",
            "Triagem criada antes do suporte a múltiplas rodadas.",
        )
        return [legacy_round]
    return []


def _chunk_to_dict(chunk: Chunk, include_embedding: bool = True) -> Dict[str, Any]:
    result = {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "text": decrypt_chunk_text(chunk.text),
        "sha256": chunk.sha256,
        "embedding_error": chunk.embedding_error,
    }
    if include_embedding:
        result["embedding"] = _json_load(chunk.embedding_json)
    return result


def load_document_content(document: Document) -> str:
    """Carrega o texto canônico do documento a partir do object store."""
    if not document.content_key:
        return ""
    try:
        return get_document_storage().get(document.content_key).decode("utf-8")
    except StorageError:
        return ""


def load_document_original(document: Document) -> Optional[bytes]:
    """Carrega o arquivo original (por exemplo o PDF) do object store."""
    if not document.original_key:
        return None
    try:
        return get_document_storage().get(document.original_key)
    except StorageError:
        return None


def _document_to_dict(document: Document, include_content: bool = True) -> Dict[str, Any]:
    counterparty = (
        "respondent" if document.submitted_by == "claimant" else "claimant"
    )
    result = {
        "id": document.id,
        "name": document.name,
        "sha256": document.sha256,
        "byte_size": document.byte_size,
        "has_original": bool(document.original_key),
        "submitted_by": document.submitted_by,
        "counterparty": counterparty,
        "material_type": document.material_type,
        "purpose": document.purpose,
        "disclosed_at": document.disclosed_at,
        "acknowledged_at": document.acknowledged_at,
        "acknowledged_by": document.acknowledged_by,
        "response_status": document.response_status,
        "response_text": document.response_text,
        "responded_at": document.responded_at,
        "admitted": document.admitted,
        "admitted_at": document.admitted_at,
        "contradictory_complete": bool(
            document.disclosed_at
            and document.acknowledged_at
            and document.response_status in {"answered", "waived", "challenged"}
            and document.admitted
        ),
        "chunks_count": document.chunks_count,
        "created_at": document.created_at.isoformat(),
    }
    if include_content:
        result["content"] = load_document_content(document)
    return result


def document_to_dict(
    document: Document,
    include_content: bool = True,
) -> Dict[str, Any]:
    return _document_to_dict(document, include_content=include_content)


def case_to_dict(
    case: Case,
    include_content: bool = True,
    include_embeddings: bool = True,
) -> Dict[str, Any]:
    conciliation_rounds = _conciliation_rounds(
        _json_load(case.conciliation_json)
    )
    documents = [
        _document_to_dict(document, include_content=include_content)
        for document in case.documents
    ]
    pending_documents = [
        document["id"]
        for document in documents
        if not document["contradictory_complete"]
    ]
    decision_runs = [_run_to_dict(item) for item in case.decision_runs]
    original_decision = None
    if case.decision_runs:
        first = min(case.decision_runs, key=lambda item: item.version or 0)
        original_decision = _public_decision(_json_load(first.payload_json))
    return {
        "id": case.id,
        "title": case.title,
        "claimant": case.claimant,
        "respondent": case.respondent,
        "status": case.status,
        "consent": {
            "claimant": {
                "accepted": case.claimant_consent,
                "accepted_at": case.claimant_consent_at,
                "terms_version": case.claimant_terms_version,
                "terms_sha256": case.claimant_terms_sha256,
            },
            "respondent": {
                "accepted": case.respondent_consent,
                "accepted_at": case.respondent_consent_at,
                "terms_version": case.respondent_terms_version,
                "terms_sha256": case.respondent_terms_sha256,
            },
            "complete": case.claimant_consent and case.respondent_consent,
        },
        "contradictory": {
            "complete": bool(documents) and not pending_documents,
            "pending_document_ids": pending_documents,
            "admitted_document_ids": [
                document["id"] for document in documents if document["admitted"]
            ],
        },
        "manifest_locked": case.manifest_locked,
        "locked_manifest": _json_load(case.locked_manifest_json),
        "conciliation": conciliation_rounds[-1] if conciliation_rounds else None,
        "conciliation_rounds": conciliation_rounds,
        "organized": _json_load(case.organized_json),
        "decision": _public_decision(_json_load(case.decision_json)),
        "original_decision": original_decision,
        "review": _public_review(_json_load(case.review_json)),
        "attestation": _json_load(case.attestation_json),
        "nostr_anchor": _json_load(case.nostr_anchor_json),
        "verification": _json_load(case.verification_json),
        "stability": _json_load(case.stability_json),
        "procedure_conclusion": case.procedure_conclusion,
        "decision_runs": decision_runs,
        "review_runs": [_run_to_dict(item) for item in case.review_runs],
        "appeals": [_appeal_to_dict(item) for item in case.appeals],
        "attestation_records": [
            {
                "id": item.id,
                "version": item.version,
                "supersedes_id": item.supersedes_id,
                "attestation_hash": item.attestation_hash,
                "status": item.status,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in case.attestation_records
        ],
        "escrow_id": case.escrow_id,
        "contest": {
            "contested": bool(case.contested_at),
            "contested_at": case.contested_at,
            "contested_by": case.contested_by,
        },
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
        "documents": documents,
        "chunks": [
            _chunk_to_dict(chunk, include_embedding=include_embeddings)
            for chunk in case.chunks
        ],
        "audit_log": [audit_to_dict(event) for event in case.audit_events],
        "participants": [
            {
                "role": member.role,
                "display_name": member.user.display_name,
                "email": member.user.email,
                "joined_at": member.joined_at.isoformat(),
            }
            for member in case.members
        ],
        "invitations": [invitation_to_dict(item) for item in case.invitations],
        "deadlines": [deadline_to_dict(item) for item in case.deadlines],
        "notifications": [notification_to_dict(item) for item in case.notifications],
    }


def audit_to_dict(event: AuditEvent) -> Dict[str, Any]:
    return {
        "event_type": event.event_type,
        "timestamp_utc": event.timestamp_utc,
        "payload": _json_load(event.payload_json, {}),
        "previous_hash": event.previous_hash,
        "event_hash": event.event_hash,
    }


def _public_decision(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not value:
        return value
    return public_decision_view(value)


def _public_review(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not value:
        return value
    return public_review_view(value)


def _run_to_dict(item) -> Dict[str, Any]:
    payload = _json_load(getattr(item, "payload_json", None), {}) or {}
    if "material_findings" in payload or "framework_id" in payload:
        public_payload = _public_decision(payload)
    elif payload:
        public_payload = _public_review(payload)
    else:
        public_payload = None
    return {
        "id": item.id,
        "version": item.version,
        "supersedes_id": item.supersedes_id,
        "status": item.status,
        "role": getattr(item, "role", None),
        "execution_id": getattr(item, "execution_id", None),
        "input_hash": item.input_hash,
        "output_hash": item.output_hash,
        "outcome": getattr(item, "outcome", None) or (payload or {}).get("outcome"),
        "payload": public_payload,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _appeal_to_dict(item: AutomaticAppeal) -> Dict[str, Any]:
    return {
        "id": item.id,
        "filed_by": item.filed_by,
        "grounds": _json_load(item.grounds_json, []),
        "original_decision_hash": item.original_decision_hash,
        "status": item.status,
        "appeal_provider": item.appeal_provider,
        "appeal_model": item.appeal_model,
        "result": _json_load(item.result_json),
        "result_hash": item.result_hash,
        "version": item.version,
        "supersedes_id": item.supersedes_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }
    return {
        "event_type": event.event_type,
        "timestamp_utc": event.timestamp_utc,
        "payload": _json_load(event.payload_json, {}),
        "previous_hash": event.previous_hash,
        "event_hash": event.event_hash,
    }


def _case_query(db: Session):
    return db.query(Case).options(
        selectinload(Case.documents),
        selectinload(Case.chunks),
        selectinload(Case.audit_events),
        selectinload(Case.members).selectinload(CaseMember.user),
        selectinload(Case.invitations),
        selectinload(Case.deadlines),
        selectinload(Case.notifications),
        selectinload(Case.decision_runs),
        selectinload(Case.review_runs),
        selectinload(Case.verifications),
        selectinload(Case.appeals),
        selectinload(Case.attestation_records),
        selectinload(Case.llm_executions),
    )


def create_case(
    db: Session,
    title: str,
    claimant: str,
    respondent: str,
    claimant_token_hash: str,
    respondent_token_hash: str,
    manager_token_hash: str,
) -> Case:
    case = Case(
        id=str(uuid.uuid4()),
        title=title.strip(),
        claimant=claimant.strip(),
        respondent=respondent.strip(),
        claimant_token_hash=claimant_token_hash,
        respondent_token_hash=respondent_token_hash,
        manager_token_hash=manager_token_hash,
        status="draft",
    )
    db.add(case)
    db.flush()
    append_audit(db, case, "case_created", {"title": case.title})
    db.commit()
    return get_case(db, case.id)


def get_case(db: Session, case_id: str) -> Optional[Case]:
    return _case_query(db).filter(Case.id == case_id).one_or_none()


def get_document(
    db: Session,
    case_id: str,
    document_id: str,
) -> Optional[Document]:
    return (
        db.query(Document)
        .filter(Document.case_id == case_id, Document.id == document_id)
        .one_or_none()
    )


def list_cases(db: Session) -> List[Case]:
    return _case_query(db).order_by(Case.created_at.desc()).all()


def append_audit(
    db: Session,
    case: Case,
    event_type: str,
    payload: Dict[str, Any],
) -> AuditEvent:
    previous = (
        db.query(AuditEvent)
        .filter(AuditEvent.case_id == case.id)
        .order_by(AuditEvent.id.desc())
        .first()
    )
    event = build_audit_event(
        event_type,
        payload,
        previous_hash=previous.event_hash if previous else "",
    )
    record = AuditEvent(
        case_id=case.id,
        event_type=event_type,
        timestamp_utc=event["timestamp_utc"],
        payload_json=_json_dump(payload) or "{}",
        previous_hash=event["previous_hash"],
        event_hash=event["event_hash"],
    )
    db.add(record)
    db.flush()
    return record


def add_document(
    db: Session,
    case: Case,
    name: str,
    content: str,
    document_hash: str,
    chunk_records: List[Dict[str, Any]],
    submitted_by: str,
    material_type: str,
    purpose: str,
    original_bytes: Optional[bytes] = None,
    original_filename: Optional[str] = None,
    original_media_type: Optional[str] = None,
) -> Document:
    sequence = len(case.documents) + 1
    document_id = f"{case.id[:8]}-D{sequence}"

    # Grava os bytes no object store antes de persistir a referência. Uma
    # eventual falha após esta etapa deixa apenas um objeto órfão (coletável),
    # nunca uma linha apontando para conteúdo inexistente.
    storage = get_document_storage()
    content_bytes = content.encode("utf-8")
    content_key = build_content_key(case.id, document_id)
    storage.put(content_key, content_bytes, "text/plain; charset=utf-8")

    original_key = None
    if original_bytes is not None:
        original_key = build_original_key(
            case.id, document_id, original_filename or name
        )
        storage.put(
            original_key,
            original_bytes,
            original_media_type or "application/octet-stream",
        )

    document = Document(
        id=document_id,
        case_id=case.id,
        name=name,
        content_key=content_key,
        original_key=original_key,
        original_media_type=original_media_type,
        byte_size=len(content_bytes),
        sha256=document_hash,
        submitted_by=submitted_by,
        material_type=material_type,
        purpose=purpose,
        disclosed_at=datetime.now(timezone.utc).isoformat(),
        chunks_count=len(chunk_records),
    )
    db.add(document)
    for index, record in enumerate(chunk_records, start=1):
        db.add(
            Chunk(
                id=f"{document_id}-C{index}",
                case_id=case.id,
                document_id=document.id,
                text=encrypt_chunk_text(record["text"]),
                sha256=record["sha256"],
                embedding_json=_json_dump(record.get("embedding")),
                embedding_error=record.get("embedding_error", False),
            )
        )
    append_audit(
        db,
        case,
        "document_added",
        {
            "document_id": document.id,
            "name": name,
            "sha256": document_hash,
            "submitted_by": submitted_by,
            "material_type": material_type,
            "chunks_count": len(chunk_records),
        },
    )
    append_audit(
        db,
        case,
        "evidence_disclosed",
        {
            "document_id": document.id,
            "submitted_by": submitted_by,
            "disclosed_to": (
                "respondent" if submitted_by == "claimant" else "claimant"
            ),
            "sha256": document_hash,
        },
    )
    db.commit()
    db.refresh(document)
    return document


def record_consent(
    db: Session,
    case: Case,
    party: str,
    accepted: bool,
    terms_version: str,
    terms_sha256: str,
) -> Case:
    """Registra o aceite com a versão E o hash do texto exibido à parte. Sem o
    hash não há como provar depois o que foi aceito."""
    now = datetime.now(timezone.utc).isoformat()
    setattr(case, f"{party}_consent", accepted)
    setattr(case, f"{party}_consent_at", now if accepted else None)
    setattr(case, f"{party}_terms_version", terms_version if accepted else None)
    setattr(case, f"{party}_terms_sha256", terms_sha256 if accepted else None)
    append_audit(
        db,
        case,
        "consent_accepted" if accepted else "consent_withdrawn",
        {
            "party": party,
            "accepted": accepted,
            "terms_version": terms_version,
            "terms_sha256": terms_sha256,
        },
    )
    db.commit()
    return get_case(db, case.id)


def acknowledge_document(
    db: Session,
    case: Case,
    document: Document,
    party: str,
) -> Document:
    now = datetime.now(timezone.utc).isoformat()
    document.acknowledged_at = now
    document.acknowledged_by = party
    append_audit(
        db,
        case,
        "notice_acknowledged",
        {"document_id": document.id, "party": party},
    )
    db.commit()
    db.refresh(document)
    return document


def respond_to_document(
    db: Session,
    case: Case,
    document: Document,
    party: str,
    response_status: str,
    response_text: str,
) -> Document:
    document.response_status = response_status
    document.response_text = response_text
    document.responded_at = datetime.now(timezone.utc).isoformat()
    append_audit(
        db,
        case,
        "response_submitted",
        {
            "document_id": document.id,
            "party": party,
            "response_status": response_status,
            "response_sha256": (
                hashlib.sha256(response_text.encode("utf-8")).hexdigest()
                if response_text
                else None
            ),
        },
    )
    db.commit()
    db.refresh(document)
    return document


def admit_document(
    db: Session,
    case: Case,
    document: Document,
) -> Document:
    document.admitted = True
    document.admitted_at = datetime.now(timezone.utc).isoformat()
    append_audit(
        db,
        case,
        "evidence_admitted",
        {"document_id": document.id, "sha256": document.sha256},
    )
    db.commit()
    db.refresh(document)
    return document


def lock_manifest(db: Session, case: Case, manifest: Dict[str, Any]) -> Case:
    case.locked_manifest_json = _json_dump(manifest)
    case.manifest_locked = True
    case.status = "locked"
    append_audit(
        db,
        case,
        "manifest_locked",
        {
            "manifest_hash": manifest["manifest_hash"],
            "platform_signature": manifest["platform_signature"],
        },
    )
    db.commit()
    return get_case(db, case.id)


def save_stage(
    db: Session,
    case: Case,
    field: str,
    value: Dict[str, Any],
    status: str,
    event_type: str,
    event_payload: Dict[str, Any],
) -> Case:
    setattr(case, field, _json_dump(value))
    case.status = status
    append_audit(db, case, event_type, event_payload)
    db.commit()
    return get_case(db, case.id)


def save_nostr_anchor(db: Session, case: Case, anchor: Dict[str, Any]) -> Case:
    """Registra a âncora Nostr da attestation. Não altera `case.status`: é
    metadado complementar, não uma etapa do fluxo do procedimento."""
    case.nostr_anchor_json = _json_dump(anchor)
    append_audit(
        db,
        case,
        "attestation_anchored_nostr",
        {"event_id": anchor.get("event_id"), "relays": anchor.get("relays")},
    )
    db.commit()
    return get_case(db, case.id)


def register_contest(
    db: Session,
    case: Case,
    contested_by: str,
    reason: str,
) -> Case:
    contested_at = datetime.now(timezone.utc).isoformat()
    case.contested_at = contested_at
    case.contested_by = contested_by
    case.status = "contested"
    append_audit(
        db,
        case,
        "contest_registered",
        {
            "contested_by": contested_by,
            "contested_at": contested_at,
            "reason": reason,
        },
    )
    db.commit()
    return get_case(db, case.id)


def next_decision_version(db: Session, case_id: str) -> int:
    current = (
        db.query(DecisionRun)
        .filter(DecisionRun.case_id == case_id)
        .order_by(DecisionRun.version.desc())
        .first()
    )
    return (current.version + 1) if current else 1


def persist_llm_execution(
    db: Session,
    case: Case,
    execution: Dict[str, Any],
    *,
    agent: str,
    task: str = "",
    input_hash: Optional[str] = None,
    output_hash: Optional[str] = None,
    status: str = "completed",
) -> LLMExecution:
    record = LLMExecution(
        id=str(uuid.uuid4()),
        case_id=case.id,
        agent=agent,
        task=task or agent,
        requested_provider=execution.get("provider_requested") or "",
        requested_model=execution.get("model_requested") or "",
        effective_provider=execution.get("provider") or execution.get("mode") or "",
        effective_model=execution.get("model"),
        provider_response_id=execution.get("response_id"),
        prompt_tokens=(execution.get("usage") or {}).get("input_tokens"),
        completion_tokens=(execution.get("usage") or {}).get("output_tokens"),
        total_tokens=(execution.get("usage") or {}).get("total_tokens"),
        latency_ms=execution.get("latency_ms"),
        attempts=int(execution.get("attempts") or 1),
        fallback_used=bool(execution.get("fallback_used")),
        fallback_reason=execution.get("fallback_reason"),
        status=status,
        input_hash=input_hash,
        output_hash=output_hash,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    return record


def persist_decision_run(
    db: Session,
    case: Case,
    payload: Dict[str, Any],
    *,
    status: str,
    role: str = "judge",
    supersedes_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    provenance: Optional[Dict[str, Any]] = None,
    input_hash: Optional[str] = None,
    output_hash: Optional[str] = None,
) -> DecisionRun:
    version = next_decision_version(db, case.id)
    record = DecisionRun(
        id=str(uuid.uuid4()),
        case_id=case.id,
        version=version,
        supersedes_id=supersedes_id,
        status=status,
        role=role,
        execution_id=(payload.get("execution") or {}).get("execution_id"),
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        output_hash=output_hash or (provenance or {}).get("decision_payload_hash"),
        payload_json=_json_dump(payload),
        provenance_json=_json_dump(provenance),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    case.current_decision_run_id = record.id
    return record


def persist_review_run(
    db: Session,
    case: Case,
    payload: Dict[str, Any],
    *,
    status: str,
    decision_run_id: Optional[str] = None,
    input_hash: Optional[str] = None,
    output_hash: Optional[str] = None,
) -> AutomaticReviewRun:
    current = (
        db.query(AutomaticReviewRun)
        .filter(AutomaticReviewRun.case_id == case.id)
        .order_by(AutomaticReviewRun.version.desc())
        .first()
    )
    record = AutomaticReviewRun(
        id=str(uuid.uuid4()),
        case_id=case.id,
        decision_run_id=decision_run_id or case.current_decision_run_id,
        version=(current.version + 1) if current else 1,
        supersedes_id=current.id if current else None,
        status=status,
        outcome=payload.get("outcome"),
        execution_id=(payload.get("execution") or {}).get("execution_id"),
        input_hash=input_hash,
        output_hash=output_hash,
        payload_json=_json_dump(payload),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    case.current_review_run_id = record.id
    return record


def persist_verification(
    db: Session,
    case: Case,
    result: Dict[str, Any],
    *,
    result_hash: str,
    decision_run_id: Optional[str] = None,
) -> DecisionVerification:
    record = DecisionVerification(
        id=str(uuid.uuid4()),
        case_id=case.id,
        decision_run_id=decision_run_id or case.current_decision_run_id,
        valid=bool(result.get("valid")),
        result_json=_json_dump(result) or "{}",
        result_hash=result_hash,
        execution_id=result.get("execution_id"),
    )
    db.add(record)
    case.verification_json = _json_dump(result)
    db.flush()
    return record


def persist_appeal(
    db: Session,
    case: Case,
    *,
    filed_by: str,
    grounds: List[Any],
    original_decision_hash: str,
    idempotency_key: Optional[str] = None,
    status: str = "filed",
) -> AutomaticAppeal:
    current = (
        db.query(AutomaticAppeal)
        .filter(AutomaticAppeal.case_id == case.id)
        .order_by(AutomaticAppeal.version.desc())
        .first()
    )
    record = AutomaticAppeal(
        id=str(uuid.uuid4()),
        case_id=case.id,
        filed_by=filed_by,
        grounds_json=_json_dump(grounds) or "[]",
        original_decision_hash=original_decision_hash,
        status=status,
        idempotency_key=idempotency_key,
        version=(current.version + 1) if current else 1,
        supersedes_id=current.id if current else None,
    )
    db.add(record)
    db.flush()
    return record


def complete_appeal(
    db: Session,
    appeal: AutomaticAppeal,
    result: Dict[str, Any],
    *,
    result_hash: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status: str = "completed",
) -> AutomaticAppeal:
    appeal.result_json = _json_dump(result)
    appeal.result_hash = result_hash
    appeal.status = status
    appeal.appeal_provider = provider
    appeal.appeal_model = model
    appeal.execution_id = (result.get("execution") or {}).get("execution_id")
    appeal.completed_at = datetime.now(timezone.utc)
    db.add(appeal)
    db.flush()
    return appeal


def persist_attestation_record(
    db: Session,
    case: Case,
    attestation: Dict[str, Any],
    *,
    decision_run_id: Optional[str] = None,
    review_run_id: Optional[str] = None,
    verification_id: Optional[str] = None,
    appeal_id: Optional[str] = None,
) -> AttestationRecord:
    current = (
        db.query(AttestationRecord)
        .filter(AttestationRecord.case_id == case.id)
        .order_by(AttestationRecord.version.desc())
        .first()
    )
    record = AttestationRecord(
        id=str(uuid.uuid4()),
        case_id=case.id,
        version=(current.version + 1) if current else 1,
        supersedes_id=current.id if current else None,
        status="issued",
        payload_json=_json_dump(attestation) or "{}",
        attestation_hash=attestation.get("attestation_hash") or "",
        decision_run_id=decision_run_id or case.current_decision_run_id,
        review_run_id=review_run_id or case.current_review_run_id,
        verification_id=verification_id,
        appeal_id=appeal_id,
    )
    db.add(record)
    db.flush()
    return record


def find_appeal_by_idempotency(
    db: Session,
    case_id: str,
    idempotency_key: str,
) -> Optional[AutomaticAppeal]:
    if not idempotency_key:
        return None
    return (
        db.query(AutomaticAppeal)
        .filter(
            AutomaticAppeal.case_id == case_id,
            AutomaticAppeal.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )


def count_appeals(db: Session, case_id: str) -> int:
    return db.query(AutomaticAppeal).filter(AutomaticAppeal.case_id == case_id).count()
