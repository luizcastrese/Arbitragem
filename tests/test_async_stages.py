"""Etapas de modelo fora do request HTTP.

O que estes testes protegem:

- por padrão a etapa responde 202 na hora e roda em segundo plano, em vez de
  segurar a conexão pelo tempo das chamadas de modelo;
- `?wait=` continua entregando o resultado na própria resposta, para clientes
  que preferem uma chamada só;
- o polling reflete o estado real, que é o do banco;
- uma etapa que falha devolve o caso ao estado anterior em vez de deixá-lo
  preso em `processing_*` até o TTL.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Case
from app.db.session import get_db
from app.main import app, stage_runner
from tests.test_api import CASE_CREDENTIALS, actor_headers, prepare_locked_case


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
    CASE_CREDENTIALS.clear()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def poll_until_done(client, case_id: str, stage: str, timeout: float = 30.0):
    """Aguarda a etapa sair de `processing`, como faria um cliente real."""
    deadline = time.monotonic() + timeout
    body = {}
    while time.monotonic() < deadline:
        response = client.get(f"/cases/{case_id}/stage/{stage}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["state"] != "processing":
            return body
        time.sleep(0.05)
    raise AssertionError(f"A etapa {stage} não concluiu em {timeout}s: {body}")


def test_etapa_responde_202_e_conclui_em_segundo_plano(client):
    case_id, _document, _ = prepare_locked_case(client)

    response = client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "manager"),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "processing"
    assert body["stage"] == "conciliation"
    assert body["poll"] == f"/cases/{case_id}/stage/conciliation"

    done = poll_until_done(client, case_id, "conciliation")
    assert done["state"] == "completed"
    assert done["result"]["round_number"] == 1


def test_wait_devolve_o_resultado_na_propria_resposta(client):
    case_id, _document, _ = prepare_locked_case(client)

    response = client.post(
        f"/cases/{case_id}/conciliation?wait=60",
        headers=actor_headers(case_id, "manager"),
    )

    assert response.status_code == 200
    assert response.json()["round_number"] == 1


def test_polling_de_etapa_ainda_nao_iniciada(client):
    case_id, _document, _ = prepare_locked_case(client)

    body = client.get(f"/cases/{case_id}/stage/decide").json()

    assert body["state"] == "pending"
    assert body["case_status"] == "locked"


def test_polling_de_etapa_desconhecida_e_404(client):
    case_id, _document, _ = prepare_locked_case(client)
    assert client.get(f"/cases/{case_id}/stage/inexistente").status_code == 404


def test_fluxo_assincrono_completo_ate_a_revisao(client):
    case_id, _document, _ = prepare_locked_case(client)

    for stage in ("conciliation", "organize", "decide", "review"):
        accepted = client.post(
            f"/cases/{case_id}/{stage}",
            headers=actor_headers(case_id, "manager"),
        )
        assert accepted.status_code == 202, accepted.text
        done = poll_until_done(client, case_id, stage)
        assert done["state"] == "completed", done

    persisted = client.get(f"/cases/{case_id}").json()
    assert persisted["status"] == "reviewed"
    audit = client.get(f"/cases/{case_id}/audit").json()
    assert audit["valid"] is True


def test_polling_reflete_o_banco_mesmo_sem_registro_em_memoria(client):
    """O registro em memória some num restart; o resultado gravado não."""
    case_id, _document, _ = prepare_locked_case(client)
    client.post(
        f"/cases/{case_id}/conciliation?wait=60",
        headers=actor_headers(case_id, "manager"),
    )

    stage_runner.reset()

    body = client.get(f"/cases/{case_id}/stage/conciliation").json()
    assert body["state"] == "completed"
    assert body["result"]["round_number"] == 1


def test_etapa_que_falha_devolve_o_caso_ao_estado_anterior(
    client, session_factory, monkeypatch
):
    """Sem a recuperação, o caso ficaria em processing_decision até o TTL de
    10 minutos, sem ninguém conseguir repetir a etapa."""
    from app import main

    case_id, _document, _ = prepare_locked_case(client)
    for stage in ("conciliation", "organize"):
        assert (
            client.post(
                f"/cases/{case_id}/{stage}?wait=60",
                headers=actor_headers(case_id, "manager"),
            ).status_code
            == 200
        )

    def explode(*_args, **_kwargs):
        raise RuntimeError("provedor fora do ar")

    monkeypatch.setattr(main, "generate_and_verify_decision", explode)

    accepted = client.post(
        f"/cases/{case_id}/decide",
        headers=actor_headers(case_id, "manager"),
    )
    assert accepted.status_code == 202

    failed = poll_until_done(client, case_id, "decide")
    assert failed["state"] == "failed"
    assert "provedor fora do ar" in failed["error"]

    db = session_factory()
    try:
        case = db.query(Case).filter(Case.id == case_id).one()
        assert case.status == "organized"
        assert case.processing_started_at is None
    finally:
        db.close()

    # E a etapa pode ser repetida: o caso não ficou preso.
    monkeypatch.undo()
    retry = client.post(
        f"/cases/{case_id}/decide?wait=60",
        headers=actor_headers(case_id, "manager"),
    )
    assert retry.status_code == 200
    assert retry.json()["outcome"] == "inconclusive"


def test_falha_com_wait_vira_500_com_o_motivo(client, monkeypatch):
    from app import main

    case_id, _document, _ = prepare_locked_case(client)
    for stage in ("conciliation", "organize"):
        client.post(
            f"/cases/{case_id}/{stage}?wait=60",
            headers=actor_headers(case_id, "manager"),
        )

    def explode(*_args, **_kwargs):
        raise RuntimeError("provedor fora do ar")

    monkeypatch.setattr(main, "generate_and_verify_decision", explode)

    response = client.post(
        f"/cases/{case_id}/decide?wait=60",
        headers=actor_headers(case_id, "manager"),
    )
    assert response.status_code == 500
    assert "provedor fora do ar" in response.json()["detail"]


def test_rodada_de_composicao_simultanea_e_recusada(client, monkeypatch):
    from app import main

    case_id, _document, _ = prepare_locked_case(client)

    liberar = __import__("threading").Event()

    original = main.assess_conciliation

    def lenta(context, round_number):
        liberar.wait(timeout=10)
        return original(context, round_number)

    monkeypatch.setattr(main, "assess_conciliation", lenta)

    primeira = client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "manager"),
    )
    assert primeira.status_code == 202

    segunda = client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "manager"),
        json={"advance": True, "new_information": "outra tentativa"},
    )
    assert segunda.status_code == 409

    liberar.set()
    poll_until_done(client, case_id, "conciliation")


def test_wait_acima_do_teto_e_recusado(client):
    case_id, _document, _ = prepare_locked_case(client)
    response = client.post(
        f"/cases/{case_id}/conciliation?wait=100000",
        headers=actor_headers(case_id, "manager"),
    )
    assert response.status_code == 422
