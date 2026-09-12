"""Direitos do titular: exportação e eliminação de dados pessoais.

Duas restrições moldam este módulo.

A primeira é a cadeia de auditoria: cada ato do procedimento é encadeado por
hash e sustenta attestations que terceiros podem já ter usado para executar
uma decisão. Apagar um elo torna inverificável tudo o que veio depois. Por
isso a eliminação **anonimiza a identificação do titular** em vez de remover
registros do procedimento — o vínculo entre pessoa e caso é desfeito, os
hashes continuam conferindo.

A segunda é a outra parte: enquanto um caso está em andamento, ela tem direito
de saber com quem litiga. O pedido é recusado enquanto houver caso aberto e
atendido assim que ele encerra.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.identifiers import email_fingerprint
from app.db.models import (
    AuditEvent,
    AuthSession,
    AuthToken,
    Case,
    CaseMember,
    Document,
    Invitation,
    Notification,
    User,
)
from app.domain.concurrency import TERMINAL_STATUSES


ANONYMIZED_DOMAIN = "anonimizado.invalid"
ANONYMIZED_NAME = "Titular removido"


class ErasureBlocked(RuntimeError):
    """A conta ainda participa de um caso em andamento."""

    def __init__(self, case_ids: List[str]) -> None:
        self.case_ids = case_ids
        super().__init__(
            "A conta participa de casos em andamento e a identificação não "
            "pode ser removida no meio do procedimento: "
            + ", ".join(case_ids)
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def residual_audit_identifiers(db: Session, email: str) -> List[str]:
    """Eventos de auditoria que ainda contêm o endereço em texto claro.

    A cadeia é encadeada por hash e sustenta attestations já emitidas:
    reescrever um evento antigo invalidaria tudo o que veio depois. Eventos
    gravados antes de a plataforma passar a registrar e-mail apenas por
    máscara e impressão são, portanto, irreversíveis — e o titular precisa
    saber disso em vez de receber um `anonymized: true` que não conta a
    história inteira.
    """
    if not email:
        return []
    needle = f'"{email}"'
    return [
        str(event.id)
        for event in db.query(AuditEvent).filter(
            AuditEvent.payload_json.contains(needle)
        )
    ]


def open_case_ids(db: Session, user_id: str) -> List[str]:
    """Casos do titular que ainda não chegaram a um estado terminal."""
    rows = (
        db.query(Case)
        .join(CaseMember, CaseMember.case_id == Case.id)
        .filter(CaseMember.user_id == user_id)
        .all()
    )
    return [case.id for case in rows if case.status not in TERMINAL_STATUSES]


def export_user_data(db: Session, user: User) -> Dict[str, Any]:
    """Tudo o que a plataforma guarda sobre o titular, em formato estruturado.

    Inclui os casos de que a conta participa, mas não o conteúdo dos
    documentos da outra parte: a exportação é do titular, não do caso inteiro.
    Os documentos que a própria conta apresentou aparecem com metadados e
    hash, e continuam disponíveis para download pelas rotas do caso.
    """
    memberships = (
        db.query(CaseMember).filter(CaseMember.user_id == user.id).all()
    )
    case_ids = sorted({item.case_id for item in memberships})
    roles_by_case: Dict[str, List[str]] = {}
    for item in memberships:
        roles_by_case.setdefault(item.case_id, []).append(item.role)

    cases: List[Dict[str, Any]] = []
    for case_id in case_ids:
        case = db.query(Case).filter(Case.id == case_id).first()
        if case is None:  # pragma: no cover - integridade referencial
            continue
        roles = sorted(roles_by_case.get(case_id, []))
        documents = (
            db.query(Document)
            .filter(
                Document.case_id == case_id,
                Document.submitted_by.in_(roles),
            )
            .all()
        )
        cases.append(
            {
                "id": case.id,
                "title": case.title,
                "status": case.status,
                "roles": roles,
                "created_at": _iso(case.created_at),
                "procedure_conclusion": case.procedure_conclusion,
                "documents_submitted": [
                    {
                        "id": document.id,
                        "name": document.name,
                        "sha256": document.sha256,
                        "byte_size": document.byte_size,
                        "material_type": document.material_type,
                        "content_available": bool(document.content_key),
                        "created_at": _iso(document.created_at),
                    }
                    for document in documents
                ],
            }
        )

    sessions = db.query(AuthSession).filter(AuthSession.user_id == user.id).all()
    notifications = (
        db.query(Notification).filter(Notification.user_id == user.id).all()
    )
    invitations = (
        db.query(Invitation).filter(Invitation.email == user.email).all()
    )

    return {
        "generated_at_utc": _utc_now().isoformat(),
        "account": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "active": user.active,
            "email_verified_at": _iso(user.email_verified_at),
            "created_at": _iso(user.created_at),
        },
        "cases": cases,
        "sessions": [
            {
                "id": item.id,
                "created_at": _iso(item.created_at),
                "expires_at": _iso(item.expires_at),
                "revoked_at": _iso(item.revoked_at),
            }
            for item in sessions
        ],
        "notifications": [
            {
                "id": item.id,
                "case_id": item.case_id,
                "message": item.message,
                "created_at": _iso(item.created_at),
            }
            for item in notifications
        ],
        "invitations": [
            {
                "id": item.id,
                "case_id": item.case_id,
                "role": item.role,
                "created_at": _iso(item.created_at),
                "accepted_at": _iso(item.accepted_at),
            }
            for item in invitations
        ],
        "nota": (
            "Registros de auditoria e attestations do procedimento são "
            "preservados por integridade e não constam desta exportação; "
            "eles guardam hashes e atos, não dados de conta."
        ),
    }


def anonymize_user(db: Session, user: User) -> Dict[str, Any]:
    """Desfaz o vínculo entre a pessoa e os dados que sobram no procedimento.

    O e-mail vira um endereço irreversível em domínio reservado, o nome vira
    um rótulo genérico, a senha vira um valor aleatório inutilizável, e todas
    as sessões e tokens pendentes são encerrados. A conta permanece como
    identificador opaco para que os papéis no caso continuem consistentes.
    """
    open_cases = open_case_ids(db, user.id)
    if open_cases:
        raise ErasureBlocked(open_cases)

    original_email = user.email
    residual = residual_audit_identifiers(db, original_email)
    now = _utc_now()
    # Sufixo aleatório: o hash sozinho seria reversível por dicionário de
    # e-mails conhecidos.
    digest = hashlib.sha256(
        f"{user.id}:{secrets.token_hex(16)}".encode("utf-8")
    ).hexdigest()[:32]

    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).update({AuthSession.revoked_at: now}, synchronize_session=False)
    db.query(AuthToken).filter(AuthToken.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(Invitation).filter(Invitation.email == user.email).update(
        {Invitation.email: f"{digest}@{ANONYMIZED_DOMAIN}"},
        synchronize_session=False,
    )
    db.query(Notification).filter(Notification.user_id == user.id).delete(
        synchronize_session=False
    )

    user.email = f"{digest}@{ANONYMIZED_DOMAIN}"
    user.display_name = ANONYMIZED_NAME
    user.password_hash = f"anonymized${secrets.token_hex(32)}"
    user.active = False
    user.email_verified_at = None
    user.failed_login_attempts = 0
    user.locked_until = None
    db.add(user)
    db.commit()

    result = {
        "anonymized": True,
        "user_id": user.id,
        "anonymized_at_utc": now.isoformat(),
        "sessions_revoked": True,
        "email_sha256": email_fingerprint(original_email),
        "preserved": (
            "Cadeia de auditoria, hashes de documentos e attestations "
            "permanecem para manter o procedimento verificável."
        ),
    }
    if residual:
        result["residual_identifiers"] = {
            "audit_event_ids": residual,
            "detail": (
                "Estes eventos de auditoria foram gravados antes de a "
                "plataforma passar a registrar e-mail apenas por máscara e "
                "impressão, e ainda contêm o endereço em texto claro. A "
                "cadeia é encadeada por hash e sustenta attestations já "
                "emitidas: reescrevê-los invalidaria decisões que terceiros "
                "podem ter executado. Eventos novos não retêm o endereço."
            ),
        }
    return result
