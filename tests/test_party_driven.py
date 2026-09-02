"""Rito impulsionado pelas partes, sem gestor, com subsidiários por lado."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["OPENAI_API_KEY"] = ""
os.environ["PLATFORM_SIGNING_SECRET"] = "test-signing-secret"
os.environ["AUTH_REQUIRED"] = "false"

from app.core.config import get_settings

get_settings.cache_clear()

from app.db.models import Base
from app.db.session import get_db
from app.main import app
from tests.test_api import (
    CASE_CREDENTIALS,
    actor_headers,
    add_contract,
    create_case,
    register_user,
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


def test_new_case_has_no_manager_role_or_token(client):
    case = create_case(client)
    assert "manager" not in CASE_CREDENTIALS[case["id"]]
    assert case["participants"] == []
    rejected = client.post(
        f"/cases/{case['id']}/invitations",
        headers=actor_headers(case["id"], "claimant"),
        json={"email": "gestor@example.com", "role": "manager"},
    )
    assert rejected.status_code == 422


def test_either_party_can_lock_after_contradictory(client):
    case_id = create_case(client)["id"]
    for party in ("claimant", "respondent"):
        assert (
            client.post(
                f"/cases/{case_id}/consent",
                json={"party": party, "accepted": True},
                headers=actor_headers(case_id, party),
            ).status_code
            == 200
        )
    document = add_contract(client, case_id)["document"]
    assert (
        client.post(
            f"/cases/{case_id}/documents/{document['id']}/acknowledge",
            json={"party": "respondent"},
            headers=actor_headers(case_id, "respondent"),
        ).status_code
        == 200
    )
    responded = client.post(
        f"/cases/{case_id}/documents/{document['id']}/respond",
        json={
            "party": "respondent",
            "response_status": "waived",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    assert responded.status_code == 200
    assert responded.json()["documents"][0]["admitted"] is True

    locked = client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "respondent"),
    )
    assert locked.status_code == 200
    assert locked.json()["manifest"]["manifest_hash"]


def test_subsidiary_can_access_and_file_but_cannot_drive_procedure(client):
    claimant = register_user(client, "Cliente Ana", "ana@example.com")
    created = client.post(
        "/cases",
        headers={"X-Session-Token": claimant["session_token"]},
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Ana",
            "respondent": "Empresa Delta",
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    CASE_CREDENTIALS[case_id] = created.json()["access_credentials"]

    invite = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "advogada@example.com", "role": "subsidiary"},
    )
    assert invite.status_code == 201
    assert invite.json()["role"] == "subsidiary"
    assert invite.json()["party"] == "claimant"

    counsel = register_user(client, "Advogada Lia", "advogada@example.com")
    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": counsel["session_token"]},
        json={"token": invite.json()["acceptance_token"]},
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "subsidiary"

    visible = client.get(
        f"/cases/{case_id}",
        headers={"X-Session-Token": counsel["session_token"]},
    )
    assert visible.status_code == 200
    participants = visible.json()["participants"]
    subsidiary = next(item for item in participants if item["role"] == "subsidiary")
    assert subsidiary["party"] == "claimant"
    assert subsidiary["email"] == "advogada@example.com"

    filed = client.post(
        f"/cases/{case_id}/documents/text",
        headers={"X-Actor-Token": counsel["session_token"]},
        json={
            "name": "peticao.txt",
            "content": "A reclamante alega cobrança indevida após o cancelamento.",
            "submitted_by": "claimant",
            "material_type": "argument",
            "purpose": "Peça apresentada pela advogada da reclamante.",
        },
    )
    assert filed.status_code == 201

    cannot_invite_other_side = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": counsel["session_token"]},
        json={"email": "terceiro-delta@example.com", "role": "subsidiary"},
    )
    assert cannot_invite_other_side.status_code == 403

    cannot_lock = client.post(
        f"/cases/{case_id}/lock",
        headers={"X-Actor-Token": counsel["session_token"]},
    )
    assert cannot_lock.status_code == 403

    cannot_consent_for_party = client.post(
        f"/cases/{case_id}/consent",
        headers={"X-Actor-Token": counsel["session_token"]},
        json={"party": "claimant", "accepted": True},
    )
    assert cannot_consent_for_party.status_code == 403


def test_party_invites_only_own_subsidiaries_and_the_other_principal(client):
    claimant = register_user(client, "Cliente Ana", "ana@example.com")
    created = client.post(
        "/cases",
        headers={"X-Session-Token": claimant["session_token"]},
        json={
            "title": "Serviço incompleto",
            "claimant": "Cliente Ana",
            "respondent": "Fornecedor Beta",
        },
    ).json()
    case_id = created["id"]

    duplicate_claimant = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "outra-ana@example.com", "role": "claimant"},
    )
    assert duplicate_claimant.status_code == 409

    respondent_invite = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "beta@example.com", "role": "respondent"},
    )
    assert respondent_invite.status_code == 201

    company = register_user(client, "Fornecedor Beta", "beta@example.com")
    assert (
        client.post(
            "/invitations/accept",
            headers={"X-Session-Token": company["session_token"]},
            json={"token": respondent_invite.json()["acceptance_token"]},
        ).status_code
        == 200
    )

    own_side = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": company["session_token"]},
        json={
            "email": "advogado-beta@example.com",
            "role": "subsidiary",
            "party": "claimant",
        },
    )
    assert own_side.status_code == 201
    assert own_side.json()["party"] == "respondent"


def test_frontend_explains_unique_process():
    from pathlib import Path

    source = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
    for phrase in (
        "Não há gestor",
        "julgador humano interno",
        "segundo modelo",
        "verificador determinístico",
        "contraditório",
        "se abstém",
        "O que só a Valinor faz",
        "Seis etapas, as mesmas regras",
        "admissão é automática",
        "Attestation e contestação",
    ):
        assert phrase in source
    assert "Gestor do procedimento" not in source
    assert "option value=\"manager\"" not in source
    assert "roles.manager" not in source
    assert "terms={terms}" in source
    styles = Path("frontend/src/styles.css").read_text(encoding="utf-8")
    assert ".unique-guarantees" in styles
    assert ".intro-guarantees" in styles
    assert ".process-guarantee" in styles
    assert ".stage-guarantee" in styles
