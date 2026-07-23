import io
import os

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ["DOCUMENT_STORAGE_BACKEND"] = "memory"
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core.config import get_settings  # noqa: E402
from app.documents.storage import (  # noqa: E402
    InMemoryStorage,
    LocalDiskStorage,
    StorageError,
    build_content_key,
    build_original_key,
)

get_settings.cache_clear()

from app.db.models import Base  # noqa: E402
from app.db.repository import get_document, load_document_content  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


# --- Backends de armazenamento ------------------------------------------------


def test_key_builders():
    assert build_content_key("case1", "case1-D1") == "case1/case1-D1/content.txt"
    assert (
        build_original_key("case1", "case1-D1", "contrato.PDF")
        == "case1/case1-D1/original.pdf"
    )
    assert build_original_key("c", "d", "semextensao") == "c/d/original.bin"


def test_in_memory_storage_roundtrip():
    storage = InMemoryStorage()
    storage.put("a/b", b"conteudo")
    assert storage.exists("a/b") is True
    assert storage.get("a/b") == b"conteudo"
    storage.delete("a/b")
    assert storage.exists("a/b") is False
    with pytest.raises(StorageError):
        storage.get("a/b")


def test_local_disk_storage_roundtrip(tmp_path):
    storage = LocalDiskStorage(str(tmp_path))
    storage.put("caso/doc/content.txt", b"texto")
    assert storage.exists("caso/doc/content.txt") is True
    assert storage.get("caso/doc/content.txt") == b"texto"
    with pytest.raises(StorageError):
        storage.get("caso/doc/ausente.txt")


def test_local_disk_storage_rejects_path_traversal(tmp_path):
    storage = LocalDiskStorage(str(tmp_path))
    with pytest.raises(StorageError):
        storage.put("../fora.txt", b"x")


# --- Integração: conteúdo fora do banco --------------------------------------


def _create_case(client):
    response = client.post(
        "/cases",
        json={
            "title": "Disputa com documentos",
            "claimant": "Cliente",
            "respondent": "Empresa",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_text_document_content_lives_in_storage(client):
    test_client, session_factory = client
    case = _create_case(test_client)
    case_id = case["id"]
    credentials = case["access_credentials"]

    response = test_client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "relato.txt",
            "content": "O cliente descreve o problema em detalhes.",
            "submitted_by": "claimant",
            "material_type": "argument",
            "purpose": "Relato inicial.",
        },
        headers={"X-Actor-Token": credentials["claimant"]},
    )
    assert response.status_code == 201
    document_id = response.json()["document"]["id"]

    # O banco não guarda mais o texto inline, apenas a referência.
    db = session_factory()
    try:
        document = get_document(db, case_id, document_id)
        assert getattr(document, "content", None) is None
        assert document.content_key == build_content_key(case_id, document_id)
        assert document.byte_size > 0
        assert document.original_key is None
        # O texto é recuperável a partir do object store.
        assert "descreve o problema" in load_document_content(document)
    finally:
        db.close()


def test_pdf_original_is_preserved_and_downloadable(client):
    test_client, session_factory = client
    case = _create_case(test_client)
    case_id = case["id"]
    credentials = case["access_credentials"]

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Contrato assinado entre as partes")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    upload = test_client.post(
        f"/cases/{case_id}/documents/pdf",
        data={
            "submitted_by": "respondent",
            "material_type": "evidence",
            "purpose": "Contrato.",
        },
        files={"file": ("contrato.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"X-Actor-Token": credentials["respondent"]},
    )
    assert upload.status_code == 201
    document = upload.json()["document"]
    document_id = document["id"]
    assert document["has_original"] is True

    # O arquivo original (bytes do PDF) é recuperável, byte a byte.
    download = test_client.get(
        f"/cases/{case_id}/documents/{document_id}/original"
    )
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content == pdf_bytes


def test_original_download_404_for_text_document(client):
    test_client, _ = client
    case = _create_case(test_client)
    case_id = case["id"]
    credentials = case["access_credentials"]

    response = test_client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "nota.txt",
            "content": "Texto puro, sem arquivo original.",
            "submitted_by": "claimant",
            "material_type": "argument",
            "purpose": "Nota.",
        },
        headers={"X-Actor-Token": credentials["claimant"]},
    )
    document_id = response.json()["document"]["id"]

    missing = test_client.get(
        f"/cases/{case_id}/documents/{document_id}/original"
    )
    assert missing.status_code == 404
