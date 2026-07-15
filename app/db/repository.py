import json
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, selectinload

from app.core.audit import build_audit_event
from app.core.encryption import decrypt_text, encrypt_text
from app.db.access_repository import deadline_to_dict, invitation_to_dict, notification_to_dict
from app.db.models import AuditEvent, Case, CaseMember, Chunk, Document


def _json_dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return encrypt_text(json.dumps(value, ensure_ascii=False))


def _json_load(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(decrypt_text(value))


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
        "text": decrypt_text(chunk.text),
        "sha256": chunk.sha256,
        "embedding_error": chunk.embedding_error,
    }
    if include_embedding:
        result["embedding"] = _json_load(chunk.embedding_json)
    return result


def _document_to_dict(document: Document, include_content: bool = True) -> Dict[str, Any]:
    counterparty = (
        "respondent" if document.submitted_by == "claimant" else "claimant"
    )
    result = {
        "id": document.id,
        "name": document.name,
        "sha256": document.sha256,
        "submitted_by": document.submitted_by,
        "counterparty": counterparty,
        "material_type": document.material_type,
        "purpose": document.purpose,
        "disclosed_at": document.disclosed_at,
        "acknowledged_at": document.acknowledged_at,
        "acknowledged_by": document.acknowledged_by,
        "response_status": document.response_status,
        "response_text": decrypt_text(document.response_text) or "",
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
        result["content"] = decrypt_text(document.content)
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
            },
            "respondent": {
                "accepted": case.respondent_consent,
                "accepted_at": case.respondent_consent_at,
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
        "decision": _json_load(case.decision_json),
        "review": _json_load(case.review_json),
        "finalization": {
            "complete": bool(case.finalized_at),
            "finalized_at": case.finalized_at.isoformat() if case.finalized_at else None,
            "finalized_by_user_id": case.finalized_by_user_id,
            "basis": case.finalization_basis,
            "note": decrypt_text(case.finalization_note) or "",
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


def _case_query(db: Session):
    return db.query(Case).options(
        selectinload(Case.documents),
        selectinload(Case.chunks),
        selectinload(Case.audit_events),
        selectinload(Case.members).selectinload(CaseMember.user),
        selectinload(Case.invitations),
        selectinload(Case.deadlines),
        selectinload(Case.notifications),
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
) -> Document:
    sequence = len(case.documents) + 1
    document_id = f"{case.id[:8]}-D{sequence}"
    document = Document(
        id=document_id,
        case_id=case.id,
        name=name,
        content=encrypt_text(content),
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
                text=encrypt_text(record["text"]),
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
    terms_version: str = "2026-07-12",
) -> Case:
    now = datetime.now(timezone.utc).isoformat()
    setattr(case, f"{party}_consent", accepted)
    setattr(case, f"{party}_consent_at", now if accepted else None)
    append_audit(
        db,
        case,
        "consent_accepted" if accepted else "consent_withdrawn",
        {"party": party, "accepted": accepted, "terms_version": terms_version},
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
    document.response_text = encrypt_text(response_text) or ""
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


def finalize_case(
    db: Session,
    case: Case,
    reviewer_id: str,
    basis: str,
    note: str,
) -> Case:
    case.finalized_at = datetime.now(timezone.utc)
    case.finalized_by_user_id = reviewer_id
    case.finalization_basis = basis
    case.finalization_note = encrypt_text(note) or ""
    case.status = "finalized"
    append_audit(
        db,
        case,
        "case_finalized",
        {
            "reviewer_id": reviewer_id,
            "basis": basis,
            "note_sha256": hashlib.sha256(note.encode("utf-8")).hexdigest() if note else None,
        },
    )
    db.commit()
    return get_case(db, case.id)
