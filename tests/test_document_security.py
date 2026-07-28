import base64
import io
import os

import fitz
import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ["DOCUMENT_STORAGE_BACKEND"] = "memory"
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core import signed_url as signed_url_module  # noqa: E402
from app.core import encryption as encryption_module  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.encryption import (  # noqa: E402
    DocumentCipher,
    decrypt_chunk_text,
    encrypt_chunk_text,
    generate_key,
)
from app.core.signed_url import (  # noqa: E402
    SignedUrlError,
    sign_download_token,
    verify_download_token,
)
from app.documents.storage import (  # noqa: E402
    EncryptedStorage,
    InMemoryStorage,
    LocalDiskStorage,
    StorageError,
)

get_settings.cache_clear()

from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


# --- Cifra --------------------------------------------------------------------


def _cipher() -> DocumentCipher:
    return DocumentCipher(base64.b64decode(generate_key()))


def test_cipher_roundtrip_and_header():
    cipher = _cipher()
    blob = cipher.encrypt(b"conteudo sensivel")
    assert DocumentCipher.is_encrypted(blob) is True
    assert b"conteudo sensivel" not in blob
    assert cipher.decrypt(blob) == b"conteudo sensivel"


def test_cipher_detects_tampering():
    cipher = _cipher()
    blob = bytearray(cipher.encrypt(b"intacto"))
    blob[-1] ^= 0x01  # adultera a tag/ciphertext
    with pytest.raises(InvalidTag):
        cipher.decrypt(bytes(blob))


def test_cipher_passes_through_legacy_plaintext():
    cipher = _cipher()
    # Objeto legado sem cabeçalho MAGIC continua legível.
    assert cipher.decrypt(b"texto legado em claro") == b"texto legado em claro"


def test_nonce_is_per_object():
    cipher = _cipher()
    assert cipher.encrypt(b"x") != cipher.encrypt(b"x")


# --- EncryptedStorage ---------------------------------------------------------


def test_encrypted_storage_stores_ciphertext_in_memory():
    inner = InMemoryStorage()
    storage = EncryptedStorage(inner, _cipher())
    storage.put("k", b"segredo")
    # O backend interno guarda ciphertext; o texto claro não aparece.
    assert b"segredo" not in inner.get("k")
    assert DocumentCipher.is_encrypted(inner.get("k"))
    # A leitura pela camada cifrada devolve o texto claro.
    assert storage.get("k") == b"segredo"


def test_encrypted_storage_on_disk_is_ciphertext(tmp_path):
    disk = LocalDiskStorage(str(tmp_path))
    storage = EncryptedStorage(disk, _cipher())
    storage.put("caso/doc/original.pdf", b"%PDF-1.7 conteudo confidencial")
    raw = (tmp_path / "caso/doc/original.pdf").read_bytes()
    assert b"confidencial" not in raw
    assert storage.get("caso/doc/original.pdf") == b"%PDF-1.7 conteudo confidencial"


def test_encrypted_storage_raises_on_corruption():
    inner = InMemoryStorage()
    storage = EncryptedStorage(inner, _cipher())
    storage.put("k", b"dado")
    corrupted = bytearray(inner.get("k"))
    corrupted[-1] ^= 0x01
    inner.put("k", bytes(corrupted))
    with pytest.raises(StorageError):
        storage.get("k")


# --- URLs assinadas -----------------------------------------------------------


def test_signed_url_roundtrip():
    token, expires_at = sign_download_token(
        key="c/d/original.pdf",
        filename="contrato.pdf",
        media_type="application/pdf",
        expires_in=300,
    )
    claims = verify_download_token(token)
    assert claims["k"] == "c/d/original.pdf"
    assert claims["n"] == "contrato.pdf"
    assert claims["m"] == "application/pdf"
    assert int(claims["e"]) == expires_at


def test_signed_url_rejects_tampered_signature():
    token, _ = sign_download_token("k", "f", "m", 300)
    payload, _sig = token.rsplit(".", 1)
    forged = f"{payload}.{'0' * 64}"
    with pytest.raises(SignedUrlError):
        verify_download_token(forged)


def test_signed_url_rejects_expired(monkeypatch):
    token, _ = sign_download_token("k", "f", "m", expires_in=1)
    real_time = signed_url_module.time.time()
    monkeypatch.setattr(signed_url_module.time, "time", lambda: real_time + 10)
    with pytest.raises(SignedUrlError):
        verify_download_token(token)


def test_signed_url_rejects_malformed():
    with pytest.raises(SignedUrlError):
        verify_download_token("sem-ponto-nem-assinatura")


# --- Integração: fluxo de download assinado -----------------------------------


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
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
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _upload_pdf(client):
    case = client.post(
        "/cases",
        json={"title": "Caso", "claimant": "Cliente", "respondent": "Empresa"},
    ).json()
    case_id = case["id"]
    credentials = case["access_credentials"]
    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "Documento probatório")
    pdf_bytes = pdf.tobytes()
    pdf.close()
    upload = client.post(
        f"/cases/{case_id}/documents/pdf",
        data={"submitted_by": "claimant", "material_type": "evidence", "purpose": "p"},
        files={"file": ("prova.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"X-Actor-Token": credentials["claimant"]},
    )
    assert upload.status_code == 201
    return case_id, upload.json()["document"]["id"], pdf_bytes


def _extract_token(url: str) -> str:
    return url.split("token=", 1)[1]


def test_signed_download_flow(client):
    case_id, document_id, pdf_bytes = _upload_pdf(client)

    issued = client.post(f"/cases/{case_id}/documents/{document_id}/original-url")
    assert issued.status_code == 200
    body = issued.json()
    assert body["expires_in"] > 0
    assert "/documents/download?token=" in body["url"]

    token = _extract_token(body["url"])
    download = client.get(f"/documents/download?token={token}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content == pdf_bytes


def test_signed_download_rejects_bad_token(client):
    _upload_pdf(client)
    bad = client.get("/documents/download?token=abc.def")
    assert bad.status_code == 403


def test_signed_url_404_for_text_document(client):
    case = client.post(
        "/cases",
        json={"title": "Caso", "claimant": "Cliente", "respondent": "Empresa"},
    ).json()
    case_id = case["id"]
    credentials = case["access_credentials"]
    doc = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "nota.txt",
            "content": "Sem arquivo original.",
            "submitted_by": "claimant",
            "material_type": "argument",
            "purpose": "p",
        },
        headers={"X-Actor-Token": credentials["claimant"]},
    ).json()["document"]["id"]
    response = client.post(f"/cases/{case_id}/documents/{doc}/original-url")
    assert response.status_code == 404


# --- Texto do chunk cifrado em repouso -----------------------------------------


def test_encrypt_decrypt_chunk_text_roundtrip(monkeypatch):
    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    encryption_module.get_document_cipher.cache_clear()
    try:
        stored = encrypt_chunk_text("trecho sensível do documento")
        assert stored.startswith(encryption_module.CHUNK_TEXT_PREFIX)
        assert "sensível" not in stored
        assert decrypt_chunk_text(stored) == "trecho sensível do documento"
    finally:
        encryption_module.get_document_cipher.cache_clear()


def test_decrypt_chunk_text_legacy_plaintext_passthrough():
    encryption_module.get_document_cipher.cache_clear()
    assert decrypt_chunk_text("texto legado sem prefixo") == "texto legado sem prefixo"


def test_decrypt_chunk_text_without_key_raises(monkeypatch):
    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    encryption_module.get_document_cipher.cache_clear()
    stored = encrypt_chunk_text("outro trecho sensível")
    monkeypatch.delenv("DOCUMENT_ENCRYPTION_KEY", raising=False)
    encryption_module.get_document_cipher.cache_clear()
    try:
        with pytest.raises(ValueError, match="DOCUMENT_ENCRYPTION_KEY"):
            decrypt_chunk_text(stored)
    finally:
        encryption_module.get_document_cipher.cache_clear()


def test_add_document_stores_encrypted_chunk_text_in_db(monkeypatch):
    from app.db.models import Chunk
    from app.db.repository import add_document, case_to_dict, create_case, get_case

    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    encryption_module.get_document_cipher.cache_clear()
    try:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        session_factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        Base.metadata.create_all(bind=engine)
        db = session_factory()
        try:
            case = create_case(
                db,
                title="Caso",
                claimant="Cliente",
                respondent="Empresa",
                claimant_token_hash="x",
                respondent_token_hash="y",
                manager_token_hash="z",
            )
            secret_text = "Informação confidencial da parte reclamante sobre o contrato."
            add_document(
                db,
                case,
                name="nota.txt",
                content=secret_text,
                document_hash="deadbeef",
                chunk_records=[
                    {"text": secret_text, "sha256": "deadbeef", "embedding": None}
                ],
                submitted_by="claimant",
                material_type="argument",
                purpose="prova",
            )

            raw_chunk = db.query(Chunk).one()
            assert raw_chunk.text.startswith(encryption_module.CHUNK_TEXT_PREFIX)
            assert "confidencial" not in raw_chunk.text

            # Sessão de teste reutiliza o mesmo objeto `case`; força releitura
            # em vez do relacionamento já resolvido (vazio) em `create_case`.
            db.expire_all()
            full = case_to_dict(get_case(db, case.id))
            assert full["chunks"][0]["text"] == secret_text
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)
    finally:
        encryption_module.get_document_cipher.cache_clear()
