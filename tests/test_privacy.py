"""Camada LGPD: política publicada, exportação, eliminação e retenção.

O que estes testes protegem:

- a política de privacidade é versionada e imutável, como os termos;
- o titular consegue extrair e eliminar seus dados sem que a cadeia de
  auditoria seja destruída no caminho;
- a eliminação é recusada no meio de um caso em andamento;
- o expurgo por retenção apaga bytes e preserva hashes.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core import config  # noqa: E402
from app.core import privacy  # noqa: E402

config.get_settings.cache_clear()

from app.db.models import Base, Case, Document  # noqa: E402
from app.db.privacy_repository import ANONYMIZED_NAME  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.documents.storage import get_document_storage  # noqa: E402
from app.retention import expired_documents, purge_documents  # noqa: E402
from app import main  # noqa: E402


PASSWORD = "senha-bem-comprida-1"


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    yield factory
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def register(client, email="titular@example.com"):
    response = client.post(
        "/auth/register",
        json={
            "display_name": "Titular Teste",
            "email": email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- política publicada -------------------------------------------------------


def test_politica_vigente_traz_versao_hash_e_controlador(client):
    response = client.get("/privacy")
    assert response.status_code == 200
    body = response.json()

    assert body["version"] == privacy.current_version()
    assert body["sha256"] == privacy.current_policy().sha256
    assert "LGPD" in body["text"]
    assert body["rights_endpoints"]["erasure"] == "POST /account/erasure"
    assert "declared" in body["controller"]


def test_politica_por_versao_e_versao_desconhecida(client):
    version = privacy.current_version()
    assert client.get(f"/privacy/{version}").json()["current"] is True
    assert client.get("/privacy/1999-01-01").status_code == 404


def test_hash_da_politica_e_estavel():
    """O hash é a prova de qual texto estava vigente: precisa depender só do
    conteúdo normalizado."""
    primeira = privacy.current_policy().sha256
    privacy._load_all.cache_clear()
    assert privacy.current_policy().sha256 == primeira


def test_politica_declara_a_ancoragem_publica_e_a_transferencia_internacional():
    """Os dois pontos que um titular não descobriria sozinho."""
    text = privacy.current_policy().text
    assert "transferência internacional" in text.lower()
    assert "nostr" in text.lower()


# --- exportação ---------------------------------------------------------------


def test_exportacao_exige_sessao(client):
    assert client.get("/account/data-export").status_code == 401


def test_exportacao_traz_conta_e_casos(client):
    register(client)
    created = client.post(
        "/cases",
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]

    export = client.get("/account/data-export")
    assert export.status_code == 200
    body = export.json()

    assert body["account"]["email"] == "titular@example.com"
    assert [item["id"] for item in body["cases"]] == [case_id]
    assert "manager" in body["cases"][0]["roles"]
    assert body["generated_at_utc"]


# --- eliminação ---------------------------------------------------------------


def test_eliminacao_e_recusada_com_caso_em_andamento(client):
    register(client)
    client.post(
        "/cases",
        json={
            "title": "Caso aberto",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    )

    preview = client.get("/account/erasure/preview").json()
    assert preview["allowed"] is False
    assert preview["blocking_case_ids"]

    response = client.post("/account/erasure")
    assert response.status_code == 409
    assert "andamento" in response.json()["detail"]


def test_eliminacao_anonimiza_e_derruba_a_sessao(client, session_factory):
    register(client)

    preview = client.get("/account/erasure/preview").json()
    assert preview["allowed"] is True

    response = client.post("/account/erasure")
    assert response.status_code == 200
    assert response.json()["anonymized"] is True

    # A sessão morre junto: a conta não pratica mais atos.
    assert client.get("/auth/me").status_code == 401
    # E o login com a credencial antiga não volta.
    relogin = client.post(
        "/auth/login",
        json={"email": "titular@example.com", "password": PASSWORD},
    )
    assert relogin.status_code == 401

    db = session_factory()
    try:
        from app.db.models import User

        user = db.query(User).one()
        assert user.display_name == ANONYMIZED_NAME
        assert user.email.endswith("@anonimizado.invalid")
        assert user.active is False
    finally:
        db.close()


def test_eliminacao_preserva_a_cadeia_de_auditoria(client, session_factory):
    """A conta some, o caso continua verificável — é a razão de a eliminação
    ser anonimização e não deleção."""
    register(client)
    created = client.post(
        "/cases",
        json={
            "title": "Caso encerrado",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    ).json()
    case_id = created["id"]

    db = session_factory()
    try:
        case = db.query(Case).filter(Case.id == case_id).one()
        case.status = "reviewed"
        db.commit()
    finally:
        db.close()

    assert client.post("/account/erasure").status_code == 200

    audit = client.get(f"/cases/{case_id}/audit")
    assert audit.status_code == 200
    assert audit.json()["valid"] is True


# --- retenção -----------------------------------------------------------------


def _documento_encerrado(session_factory, *, dias_atras: int) -> str:
    db = session_factory()
    try:
        moment = datetime.now(timezone.utc) - timedelta(days=dias_atras)
        case = Case(
            id="caso-retencao",
            title="Encerrado",
            claimant="A",
            respondent="B",
            status="reviewed",
            created_at=moment,
            updated_at=moment,
        )
        db.add(case)
        storage = get_document_storage()
        storage.put("caso-retencao/doc-1/content.txt", b"conteudo sensivel")
        storage.put("caso-retencao/doc-1/original.pdf", b"%PDF-1.4")
        db.add(
            Document(
                id="doc-1",
                case_id=case.id,
                name="contrato.pdf",
                content_key="caso-retencao/doc-1/content.txt",
                original_key="caso-retencao/doc-1/original.pdf",
                byte_size=17,
                sha256="a" * 64,
                submitted_by="claimant",
            )
        )
        db.commit()
        return case.id
    finally:
        db.close()


def test_expurgo_ignora_caso_dentro_da_janela(session_factory):
    _documento_encerrado(session_factory, dias_atras=10)
    db = session_factory()
    try:
        assert expired_documents(db, retention_days=365) == []
    finally:
        db.close()


def test_expurgo_apaga_bytes_e_preserva_hash(session_factory):
    case_id = _documento_encerrado(session_factory, dias_atras=400)
    storage = get_document_storage()

    db = session_factory()
    try:
        simulacao = purge_documents(db, dry_run=True)
        assert simulacao["documents"] == 1
        # Simulação não apaga nada.
        assert storage.exists("caso-retencao/doc-1/content.txt")

        report = purge_documents(db)
        assert report["documents"] == 1
        assert report["cases"] == [case_id]
    finally:
        db.close()

    assert not storage.exists("caso-retencao/doc-1/content.txt")
    assert not storage.exists("caso-retencao/doc-1/original.pdf")

    db = session_factory()
    try:
        document = db.query(Document).one()
        assert document.content_purged_at is not None
        # O hash é o que mantém a decisão verificável depois do expurgo.
        assert document.sha256 == "a" * 64
        # Segunda passada não reprocessa o que já saiu.
        assert purge_documents(db)["documents"] == 0
    finally:
        db.close()


def test_expurgo_apaga_o_texto_dos_trechos_indexados(session_factory):
    """Os trechos são a segunda cópia do conteúdo, dentro do banco, e ficam
    expostos em /cases/{id}/chunks e /retrieve. Apagar só o object store
    deixaria o documento recuperável e faria o relatório de expurgo mentir."""
    from app.db.models import Chunk

    _documento_encerrado(session_factory, dias_atras=400)

    db = session_factory()
    try:
        db.add(
            Chunk(
                id="chunk-1",
                case_id="caso-retencao",
                document_id="doc-1",
                text="clausula sensivel com dado pessoal",
                sha256="b" * 64,
                embedding_json="[0.1, 0.2]",
            )
        )
        db.commit()

        assert purge_documents(db, dry_run=True)["chunks"] == 1
        assert db.query(Chunk).one().text  # a simulação não apaga

        report = purge_documents(db)
        assert report["chunks"] == 1
    finally:
        db.close()

    db = session_factory()
    try:
        chunk = db.query(Chunk).one()
        assert chunk.text == ""
        assert chunk.embedding_json is None
        # O hash fica: é o que mantém verificável a prova citada na decisão.
        assert chunk.sha256 == "b" * 64
    finally:
        db.close()


def test_auditoria_de_convite_nao_guarda_o_email(client):
    """A cadeia de auditoria é imutável e legível por todos os participantes:
    um e-mail gravado ali não poderia mais ser removido na eliminação."""
    register(client)
    case_id = client.post(
        "/cases",
        json={
            "title": "Caso com convite",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    ).json()["id"]

    client.post(
        f"/cases/{case_id}/invitations",
        json={"email": "convidado@example.com", "role": "claimant"},
    )

    audit = client.get(f"/cases/{case_id}/audit").json()
    convite = [
        event
        for event in audit["events"]
        if event["event_type"] == "participant_invited"
    ]
    assert convite, audit
    payload = convite[0]["payload"]
    assert "convidado@example.com" not in str(payload)
    assert payload["email_masked"] == "c****@example.com"
    assert payload["email_sha256"]
    assert audit["valid"] is True


def test_eliminacao_relata_identificadores_residuais(client, session_factory):
    """Eventos gravados antes da máscara não podem ser reescritos sem quebrar
    a cadeia. O titular precisa saber disso, e não receber um `anonymized:
    true` que não conta a história inteira."""
    from app.db.models import AuditEvent

    register(client)
    case_id = client.post(
        "/cases",
        json={
            "title": "Caso legado",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    ).json()["id"]

    db = session_factory()
    try:
        case = db.query(Case).filter(Case.id == case_id).one()
        case.status = "reviewed"
        # Evento no formato antigo, com o endereço em texto claro.
        legado = db.query(AuditEvent).filter(AuditEvent.case_id == case_id).first()
        legado.payload_json = '{"email": "titular@example.com"}'
        db.commit()
    finally:
        db.close()

    body = client.post("/account/erasure").json()

    assert body["anonymized"] is True
    assert body["residual_identifiers"]["audit_event_ids"]
    assert "attestations" in body["residual_identifiers"]["detail"]


def test_expurgo_desligado_com_retencao_zero(session_factory):
    _documento_encerrado(session_factory, dias_atras=400)
    db = session_factory()
    try:
        report = purge_documents(db, retention_days=0)
        assert report["enabled"] is False
        assert report["documents"] == 0
    finally:
        db.close()
