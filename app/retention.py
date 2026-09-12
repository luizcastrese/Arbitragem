"""Expurgo de documentos por retenção.

Apaga o **conteúdo** dos documentos de casos encerrados há mais tempo que a
janela de retenção — os bytes no object store e o texto dos trechos indexados
no banco, que são a segunda cópia do mesmo material — e preserva metadados e
hashes. É o único desenho compatível
com as duas obrigações do sistema: minimizar a guarda de dados pessoais (art.
15 e 16 da LGPD) e manter verificável uma decisão que terceiros podem ter
executado — a cadeia de auditoria e as attestations continuam conferindo
porque nunca dependeram do conteúdo, só do hash dele.

Uso:

    python -m app.retention --dry-run   # lista o que sairia, sem apagar
    python -m app.retention             # executa

Configure ``DOCUMENT_RETENTION_DAYS`` (0 desliga) e rode por cron, diariamente.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Case, Chunk, Document
from app.db.repository import append_audit
from app.documents.storage import StorageError, get_document_storage
from app.domain.concurrency import TERMINAL_STATUSES


logger = logging.getLogger("valinor.retention")


def _aware(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _case_closed_at(case: Case) -> Optional[datetime]:
    """Momento em que o caso encerrou, para contar a janela de retenção."""
    if case.status not in TERMINAL_STATUSES:
        return None
    return _aware(case.updated_at) or _aware(case.created_at)


def expired_documents(
    db: Session,
    retention_days: int,
    now: Optional[datetime] = None,
) -> List[Document]:
    """Documentos de casos encerrados além da janela e ainda não expurgados."""
    if retention_days <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    expired: List[Document] = []
    for case in db.query(Case).filter(Case.status.in_(tuple(TERMINAL_STATUSES))):
        closed_at = _case_closed_at(case)
        if closed_at is None or closed_at > cutoff:
            continue
        documents = (
            db.query(Document)
            .filter(
                Document.case_id == case.id,
                Document.content_purged_at.is_(None),
            )
            .all()
        )
        expired.extend(documents)
    return expired


def purge_documents(
    db: Session,
    retention_days: Optional[int] = None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Apaga os bytes dos documentos vencidos. Devolve o relatório da execução."""
    settings = get_settings()
    days = settings.document_retention_days if retention_days is None else retention_days
    now = now or datetime.now(timezone.utc)

    if days <= 0:
        return {
            "enabled": False,
            "retention_days": days,
            "documents": 0,
            "chunks": 0,
            "cases": [],
            "dry_run": dry_run,
            "detail": "DOCUMENT_RETENTION_DAYS=0: expurgo desligado.",
        }

    documents = expired_documents(db, days, now=now)
    storage = get_document_storage()
    touched_cases: Dict[str, int] = {}
    errors: List[str] = []

    purged_chunks = 0
    for document in documents:
        touched_cases[document.case_id] = touched_cases.get(document.case_id, 0) + 1
        if dry_run:
            purged_chunks += (
                db.query(Chunk)
                .filter(Chunk.document_id == document.id, Chunk.text != "")
                .count()
            )
            continue
        for key in (document.content_key, document.original_key):
            if not key:
                continue
            try:
                storage.delete(key)
            except StorageError as exc:
                # Objeto já ausente não impede a marcação: o efeito desejado
                # (bytes fora do armazenamento) está atingido de qualquer modo.
                errors.append(f"{key}: {exc}")

        # Os trechos indexados são uma segunda cópia do conteúdo, dentro do
        # banco, e continuam servidos por /cases/{id}/chunks e /retrieve.
        # Apagar só o object store deixaria o documento recuperável e faria o
        # relatório de expurgo mentir. A linha fica, com o id e o sha256, para
        # que as referências de prova da decisão continuem verificáveis.
        purged_chunks += (
            db.query(Chunk)
            .filter(Chunk.document_id == document.id)
            .update(
                {Chunk.text: "", Chunk.embedding_json: None},
                synchronize_session=False,
            )
        )

        document.content_purged_at = now
        db.add(document)

    if not dry_run and documents:
        for case_id, count in sorted(touched_cases.items()):
            case = db.query(Case).filter(Case.id == case_id).first()
            if case is None:  # pragma: no cover - integridade referencial
                continue
            append_audit(
                db,
                case,
                "documents_purged_by_retention",
                {
                    "documents": count,
                    "retention_days": days,
                    "purged_at_utc": now.isoformat(),
                },
            )
        db.commit()

    return {
        "enabled": True,
        "retention_days": days,
        "documents": len(documents),
        "chunks": purged_chunks,
        "cases": sorted(touched_cases),
        "dry_run": dry_run,
        "errors": errors,
    }


def main() -> int:  # pragma: no cover - entrada de linha de comando
    parser = argparse.ArgumentParser(
        description="Expurga os bytes de documentos de casos encerrados."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="lista o que seria apagado, sem apagar nada",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="sobrescreve DOCUMENT_RETENTION_DAYS nesta execução",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        report = purge_documents(
            db,
            retention_days=args.retention_days,
            dry_run=args.dry_run,
        )
    finally:
        db.close()

    prefix = "simulação" if report["dry_run"] else "expurgo"
    if not report["enabled"]:
        logger.info("%s: %s", prefix, report["detail"])
        return 0
    logger.info(
        "%s: %s documentos e %s trechos em %s casos (retenção de %s dias)",
        prefix,
        report["documents"],
        report["chunks"],
        len(report["cases"]),
        report["retention_days"],
    )
    for message in report.get("errors", []):
        logger.warning("objeto não removido: %s", message)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
