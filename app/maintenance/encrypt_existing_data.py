from app.core.config import get_settings
from app.core.encryption import encrypt_text
from app.db.models import AuditEvent, Case, Chunk, Document, Notification
from app.db.session import SessionLocal


CASE_FIELDS = (
    "locked_manifest_json",
    "conciliation_json",
    "organized_json",
    "decision_json",
    "review_json",
    "finalization_note",
)


def encrypt_existing_data() -> int:
    if not get_settings().data_encryption_key:
        raise RuntimeError("Defina DATA_ENCRYPTION_KEY antes de executar a migração")

    changed = 0
    with SessionLocal() as db:
        for case in db.query(Case):
            for field in CASE_FIELDS:
                current = getattr(case, field)
                encrypted = encrypt_text(current)
                if encrypted != current:
                    setattr(case, field, encrypted)
                    changed += 1
        for document in db.query(Document):
            for field in ("content", "response_text"):
                current = getattr(document, field)
                encrypted = encrypt_text(current)
                if encrypted != current:
                    setattr(document, field, encrypted)
                    changed += 1
        for chunk in db.query(Chunk):
            for field in ("text", "embedding_json"):
                current = getattr(chunk, field)
                encrypted = encrypt_text(current)
                if encrypted != current:
                    setattr(chunk, field, encrypted)
                    changed += 1
        for event in db.query(AuditEvent):
            encrypted = encrypt_text(event.payload_json)
            if encrypted != event.payload_json:
                event.payload_json = encrypted
                changed += 1
        for notification in db.query(Notification):
            for field in ("title", "message"):
                current = getattr(notification, field)
                encrypted = encrypt_text(current)
                if encrypted != current:
                    setattr(notification, field, encrypted)
                    changed += 1
        db.commit()
    return changed


if __name__ == "__main__":
    print(f"Campos criptografados: {encrypt_existing_data()}")
