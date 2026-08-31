"""API: estados autônomos, recurso, concorrência e registros encadeados."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["OPENAI_API_KEY"] = ""
os.environ["PLATFORM_SIGNING_SECRET"] = "test-signing-secret"
os.environ["AUTH_REQUIRED"] = "false"

from app.core.config import get_settings

get_settings.cache_clear()

from app.core.canonical import canonical_hash
from app.db.models import Base
from app.db.session import get_db
from app.main import app
from tests.test_api import (
    CASE_CREDENTIALS,
    actor_headers,
    prepare_locked_case,
)


@pytest.fixture()
def client():
    CASE_CREDENTIALS.clear()
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
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _through_review(client):
    case_id, document, _ = prepare_locked_case(client)
    assert client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "manager"),
    ).status_code == 200
    assert client.post(
        f"/cases/{case_id}/organize",
        headers=actor_headers(case_id, "manager"),
    ).status_code == 200
    decision = client.post(
        f"/cases/{case_id}/decide",
        headers=actor_headers(case_id, "manager"),
    )
    assert decision.status_code == 200
    review = client.post(
        f"/cases/{case_id}/review",
        headers=actor_headers(case_id, "manager"),
    )
    assert review.status_code == 200
    return case_id, decision.json(), review.json()


def test_safe_flow_ends_autonomously_without_human_review(client):
    case_id, decision, review = _through_review(client)
    assert "requires_human_review" not in decision
    assert "requires_human_review" not in review
    assert decision["outcome"] == "inconclusive"
    assert decision["procedure_conclusion"] in {
        "system_failure",
        "inconclusive",
    }
    persisted = client.get(f"/cases/{case_id}").json()
    assert persisted["status"] == "reviewed"
    assert persisted["procedure_conclusion"] in {
        "system_failure",
        "inconclusive",
        None,
    }


def test_decide_is_idempotent_and_does_not_loop(client):
    case_id, first, _ = _through_review(client)
    second = client.post(
        f"/cases/{case_id}/decide",
        headers=actor_headers(case_id, "manager"),
    ).json()
    third = client.post(
        f"/cases/{case_id}/review",
        headers=actor_headers(case_id, "manager"),
    ).json()
    assert first["decision"] == second["decision"]
    assert canonical_hash(first) == canonical_hash(second)
    review_again = client.post(
        f"/cases/{case_id}/review",
        headers=actor_headers(case_id, "manager"),
    ).json()
    assert third == review_again


def test_verification_endpoint_exists_after_decision(client):
    case_id, _, _ = _through_review(client)
    response = client.get(f"/cases/{case_id}/verification")
    assert response.status_code == 200
    body = response.json()
    assert "valid" in body
    assert "errors" in body


def test_frameworks_endpoint_lists_both_frameworks(client):
    body = client.get("/frameworks").json()
    ids = {item["id"] for item in body}
    assert "digital_services_b2b_v1" in ids
    assert "commercial_balanced_v1" in ids


def test_root_does_not_promise_human_review(client):
    body = client.get("/").json()
    principles = " ".join(body["procedure_terms"]["principles"])
    assert "revisão humana" not in principles
    assert "autônom" in principles or "abster" in principles


def test_locked_manifest_records_independence_and_framework(client):
    case_id, _, locked = prepare_locked_case(client)
    manifest = locked.json()["manifest"]
    assert manifest["framework_id"] in {
        "digital_services_b2b_v1",
        "commercial_balanced_v1",
    }
    assert "framework_hash" in manifest
    assert "deterministic_verification_version" in manifest
    commitments = manifest["anti_bias_commitments"]
    assert commitments["parties_cannot_choose_model_after_decision"] is True
    assert commitments["parties_cannot_select_favorable_reviewer"] is True
    assert commitments["procedure_is_autonomous_without_internal_human_adjudicator"] is True


def test_contest_without_attestation_is_still_409(client):
    case_id, _, _ = _through_review(client)
    response = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Discordo do resultado apresentado."},
        headers=actor_headers(case_id, "claimant"),
    )
    assert response.status_code == 409


def test_frontend_exposes_autonomous_states():
    from pathlib import Path

    source = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
    for label in (
        "Decisão em processamento",
        "Auditoria automática",
        "Decisão inconclusiva",
        "Caso inadmissível",
        "Decisão invalidada",
        "Recurso automático",
        "Decisão mantida",
        "Decisão corrigida",
        "Decisão anulada",
        "Falha do sistema",
        "Decisão aprovada",
        "Verificação determinística",
    ):
        assert label in source


def test_new_schema_tables_exist_on_create_all():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    names = set(inspect(engine).get_table_names())
    for table in (
        "llm_executions",
        "decision_runs",
        "automatic_review_runs",
        "automatic_appeals",
        "decision_verifications",
        "attestation_records",
    ):
        assert table in names
    columns = {item["name"] for item in inspect(engine).get_columns("cases")}
    assert "procedure_conclusion" in columns
    assert "row_version" in columns
    Base.metadata.drop_all(bind=engine)
