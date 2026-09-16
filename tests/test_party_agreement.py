import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Case
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def agreement_case():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        created = client.post(
            "/cases",
            json={"title": "Acordo bilateral", "claimant": "Ana", "respondent": "Beta"},
        ).json()
        credentials = created["access_credentials"]
        with sessions.begin() as db:
            case = db.get(Case, created["id"])
            case.manifest_locked = True
            case.status = "conciliation"
            case.conciliation_json = json.dumps(
                [{"round_number": 1, "possible_terms": ["Pagamento de R$ 100 em 10 dias"]}]
            )
        yield client, created["id"], credentials
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_agreement_requires_independent_acceptance_from_both_parties(agreement_case):
    client, case_id, credentials = agreement_case
    endpoint = f"/cases/{case_id}/conciliation/1/agreement"

    first = client.post(
        endpoint,
        headers={"X-Actor-Token": credentials["claimant"]},
        json={"party": "claimant", "accepted": True},
    )
    assert first.status_code == 200
    assert first.json()["complete"] is False

    second = client.post(
        endpoint,
        headers={"X-Actor-Token": credentials["respondent"]},
        json={"party": "respondent", "accepted": True},
    )
    assert second.status_code == 200
    assert second.json()["complete"] is True
    case = client.get(f"/cases/{case_id}").json()
    assert case["procedure_conclusion"] == "agreement"
    assert case["status"] == "agreement"


def test_one_party_cannot_accept_for_the_other(agreement_case):
    client, case_id, credentials = agreement_case
    response = client.post(
        f"/cases/{case_id}/conciliation/1/agreement",
        headers={"X-Actor-Token": credentials["claimant"]},
        json={"party": "respondent", "accepted": True},
    )
    assert response.status_code == 403


def test_parties_can_conduct_procedural_actions(agreement_case):
    client, case_id, credentials = agreement_case
    response = client.get(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": credentials["claimant"]},
    )
    assert response.status_code == 200
