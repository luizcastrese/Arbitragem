from sqlalchemy import inspect

from app.db.models import Base
from app.db.session import engine


def _upgrade_sqlite_schema():
    if engine.dialect.name != "sqlite":
        return

    case_columns = {column["name"] for column in inspect(engine).get_columns("cases")}
    document_columns = {
        column["name"] for column in inspect(engine).get_columns("documents")
    }
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    case_additions = {
        "conciliation_json": "TEXT",
        "claimant_consent": "BOOLEAN NOT NULL DEFAULT 1",
        "respondent_consent": "BOOLEAN NOT NULL DEFAULT 1",
        "claimant_consent_at": "TEXT",
        "respondent_consent_at": "TEXT",
        "claimant_token_hash": "TEXT",
        "respondent_token_hash": "TEXT",
        "manager_token_hash": "TEXT",
        "claimant_terms_version": "TEXT",
        "claimant_terms_sha256": "TEXT",
        "respondent_terms_version": "TEXT",
        "respondent_terms_sha256": "TEXT",
    }
    user_additions = {
        "email_verified_at": "TEXT",
        "failed_login_attempts": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "TEXT",
    }
    document_additions = {
        "submitted_by": "TEXT NOT NULL DEFAULT 'claimant'",
        "material_type": "TEXT NOT NULL DEFAULT 'evidence'",
        "purpose": "TEXT NOT NULL DEFAULT ''",
        "disclosed_at": "TEXT",
        "acknowledged_at": "TEXT",
        "acknowledged_by": "TEXT",
        "response_status": "TEXT NOT NULL DEFAULT 'answered'",
        "response_text": "TEXT NOT NULL DEFAULT ''",
        "responded_at": "TEXT",
        "admitted": "BOOLEAN NOT NULL DEFAULT 1",
        "admitted_at": "TEXT",
        "content_key": "TEXT",
        "original_key": "TEXT",
        "original_media_type": "TEXT",
        "byte_size": "INTEGER NOT NULL DEFAULT 0",
    }
    # Bancos legados guardavam o texto inline em `content`. Se a coluna existe
    # e ainda não migramos para referências, movemos cada conteúdo para o
    # object store e preenchemos `content_key`.
    needs_content_backfill = (
        "content" in document_columns and "content_key" not in document_columns
    )
    with engine.begin() as connection:
        for name, definition in case_additions.items():
            if name not in case_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE cases ADD COLUMN {name} {definition}"
                )
        for name, definition in document_additions.items():
            if name not in document_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE documents ADD COLUMN {name} {definition}"
                )
        for name, definition in user_additions.items():
            if name not in user_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE users ADD COLUMN {name} {definition}"
                )
        if document_additions.keys() - document_columns:
            connection.exec_driver_sql(
                "UPDATE documents SET "
                "disclosed_at = COALESCE(disclosed_at, created_at), "
                "acknowledged_at = COALESCE(acknowledged_at, created_at), "
                "acknowledged_by = COALESCE(acknowledged_by, 'legacy'), "
                "responded_at = COALESCE(responded_at, created_at), "
                "admitted_at = COALESCE(admitted_at, created_at)"
            )

        if needs_content_backfill:
            from app.documents.storage import build_content_key, get_document_storage

            storage = get_document_storage()
            rows = connection.exec_driver_sql(
                "SELECT id, case_id, content FROM documents"
            ).fetchall()
            for document_id, case_id, content in rows:
                content_bytes = (content or "").encode("utf-8")
                key = build_content_key(case_id, document_id)
                storage.put(key, content_bytes, "text/plain; charset=utf-8")
                connection.exec_driver_sql(
                    "UPDATE documents SET content_key = ?, byte_size = ? WHERE id = ?",
                    (key, len(content_bytes), document_id),
                )


def init_db():
    Base.metadata.create_all(bind=engine)
    _upgrade_sqlite_schema()


if __name__ == "__main__":
    init_db()
