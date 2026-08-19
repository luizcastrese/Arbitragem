"""A preclusão precisa acontecer sem que ninguém a provoque.

O rito só acorda quando uma parte age. Se quem se beneficia do silêncio da
outra nunca abre o aplicativo, o prazo vence e nada se move — o oposto do que
a preclusão existe para garantir. A varredura periódica é o que fecha isso.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["OPENAI_API_KEY"] = ""
os.environ["PLATFORM_SIGNING_SECRET"] = "test-signing-secret"
os.environ["AUTH_REQUIRED"] = "false"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core.worker import sweep  # noqa: E402
from app.db import session as session_module  # noqa: E402
from app.db.models import Base, Deadline  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

CREDENTIALS = {}


@pytest.fixture()
def client(monkeypatch):
    """Cliente HTTP e varredura compartilhando o mesmo banco.

    A varredura roda fora de uma requisição e abre a própria sessão, então
    `SessionLocal` precisa apontar para o mesmo engine do cliente — senão o
    teste olharia para um banco e o worker para outro.
    """
    CREDENTIALS.clear()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(session_module, "SessionLocal", factory)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.factory = factory
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _case_with_open_response_deadline(client):
    created = client.post(
        "/cases",
        json={
            "title": "Silêncio da contraparte",
            "claimant": "Cliente",
            "respondent": "Empresa",
            "creator_role": "claimant",
        },
    )
    assert created.status_code == 201
    case = created.json()
    CREDENTIALS[case["id"]] = case["access_credentials"]
    case_id = case["id"]

    def headers(party):
        return {"X-Actor-Token": CREDENTIALS[case_id][party]}

    for party in ("claimant", "respondent"):
        assert client.post(
            f"/cases/{case_id}/consent",
            json={"party": party, "accepted": True},
            headers=headers(party),
        ).status_code == 200

    document = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "contrato.txt",
            "content": "Entrega prometida para 30 de junho, não cumprida.",
            "submitted_by": "claimant",
            "material_type": "evidence",
            "purpose": "Comprovar o descumprimento.",
        },
        headers=headers("claimant"),
    )
    assert document.status_code == 201
    return case_id, document.json()["document"]["id"], headers


def _expire_deadlines(client, case_id):
    """Empurra os prazos abertos para o passado, como faria a passagem do tempo."""
    from datetime import datetime, timedelta, timezone

    db = client.factory()
    try:
        vencidos = 0
        for deadline in db.query(Deadline).filter(Deadline.case_id == case_id):
            if deadline.completed_at:
                continue
            deadline.due_at = datetime.now(timezone.utc) - timedelta(days=1)
            vencidos += 1
        db.commit()
        return vencidos
    finally:
        db.close()


def test_the_sweep_precludes_a_deadline_nobody_came_back_for(client):
    case_id, document_id, headers = _case_with_open_response_deadline(client)

    # O rito abriu o prazo da contraparte sozinho, e está esperando por ela.
    procedimento = client.get(f"/cases/{case_id}/procedure").json()
    assert procedimento["waiting_on"] == ["respondent"]
    assert client.get(f"/cases/{case_id}").json()["documents"][0]["response_status"] == "pending"

    assert _expire_deadlines(client, case_id) >= 1

    # Sem a varredura, o vencimento por si só não move nada: ninguém agiu.
    assert (
        client.get(f"/cases/{case_id}").json()["documents"][0]["response_status"]
        == "pending"
    )

    resultado = sweep()
    assert resultado["examined"] == 1
    assert resultado["advanced"] == 1
    assert resultado["failures"] == 0

    documento = client.get(f"/cases/{case_id}").json()["documents"][0]
    assert documento["response_status"] == "precluded"
    # Precluído não é concordância: o material entra, mas por esgotamento da
    # oportunidade, e o registro diz isso.
    assert documento["admitted"] is True

    eventos = [
        item["event_type"]
        for item in client.get(f"/cases/{case_id}/audit").json()["events"]
    ]
    assert "response_precluded" in eventos


def test_the_sweep_carries_the_case_to_its_end_when_both_sides_go_silent(client):
    """Silêncio dos dois lados não pode congelar o procedimento para sempre."""
    case_id, _, _ = _case_with_open_response_deadline(client)
    _expire_deadlines(client, case_id)
    sweep()

    # Precluída a resposta, o rito abre o prazo de encerramento da produção.
    _expire_deadlines(client, case_id)
    sweep()

    estado = client.get(f"/cases/{case_id}/procedure").json()
    assert estado["manifest_locked"] is True
    assert estado["pending"] == []
    auditoria = client.get(f"/cases/{case_id}/audit").json()
    assert auditoria["valid"] is True


def test_the_sweep_is_idempotent_and_quiet_when_there_is_nothing_to_do(client):
    case_id, _, _ = _case_with_open_response_deadline(client)

    # Prazo ainda em aberto: a varredura não força nada.
    primeira = sweep()
    assert primeira == {"examined": 1, "advanced": 0, "steps": 0, "failures": 0}

    antes = client.get(f"/cases/{case_id}/audit").json()["event_count"]
    for _ in range(3):
        assert sweep()["advanced"] == 0
    depois = client.get(f"/cases/{case_id}/audit").json()["event_count"]
    assert depois == antes


def test_one_broken_case_does_not_stop_the_queue(client, monkeypatch):
    """Um caso que falha não pode impedir a preclusão de outro."""
    primeiro, _, _ = _case_with_open_response_deadline(client)
    segundo, _, _ = _case_with_open_response_deadline(client)
    _expire_deadlines(client, primeiro)
    _expire_deadlines(client, segundo)

    import app.core.procedure as procedure_module

    original = procedure_module.advance
    quebrados = {primeiro}

    def advance_falhando(db, case):
        if case.id in quebrados:
            raise RuntimeError("falha simulada neste caso")
        return original(db, case)

    # `sweep` importa `advance` dentro da função, então trocar o atributo no
    # módulo de origem é o suficiente.
    monkeypatch.setattr(procedure_module, "advance", advance_falhando)

    resultado = sweep()
    assert resultado["examined"] == 2
    assert resultado["failures"] == 1
    assert resultado["advanced"] == 1

    # O caso sadio precluiu apesar do vizinho quebrado.
    documentos = client.get(f"/cases/{segundo}").json()["documents"]
    assert documentos[0]["response_status"] == "precluded"
    # E o quebrado ficou intacto, para ser reprocessado na próxima varredura.
    documentos = client.get(f"/cases/{primeiro}").json()["documents"]
    assert documentos[0]["response_status"] == "pending"
