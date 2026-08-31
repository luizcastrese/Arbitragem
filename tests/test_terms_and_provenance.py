"""Termos versionados no consentimento e procedência das etapas de IA.

São as duas provas que o produto promete e que antes não existiam: *o que* a
parte aceitou (texto endereçado por hash) e *com o quê* a decisão foi produzida
(prompt versionado e modelo efetivo).
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

from app.core import config  # noqa: E402

config.get_settings.cache_clear()

from app.core import terms as terms_module  # noqa: E402
from app.core.prompt_registry import (  # noqa: E402
    detect_drift,
    get_prompt,
    prompt_policy,
    register_prompt,
)
from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app import main  # noqa: E402


CASE_CREDENTIALS = {}


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

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def create_case(client):
    response = client.post(
        "/cases",
        json={
            "title": "Entrega parcial de software",
            "claimant": "Cliente Alfa",
            "respondent": "Fornecedor Beta",
        },
    )
    assert response.status_code == 201
    case = response.json()
    CASE_CREDENTIALS[case["id"]] = case.pop("access_credentials")
    return case


def actor_headers(case_id, party):
    return {"X-Actor-Token": CASE_CREDENTIALS[case_id][party]}


def add_document(client, case_id):
    response = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "contrato.txt",
            "content": "A Fornecedora entregará o sistema até 30 de junho.",
            "submitted_by": "claimant",
            "material_type": "evidence",
            "purpose": "Comprovar o prazo.",
        },
        headers=actor_headers(case_id, "claimant"),
    )
    assert response.status_code == 201
    return response.json()["document"]


def complete_contradictory(client, case_id, document_id):
    client.post(
        f"/cases/{case_id}/documents/{document_id}/acknowledge",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "respondent"),
    )
    client.post(
        f"/cases/{case_id}/documents/{document_id}/respond",
        json={"party": "respondent", "response_status": "waived"},
        headers=actor_headers(case_id, "respondent"),
    )
    admitted = client.post(
        f"/cases/{case_id}/documents/{document_id}/admit",
        headers=actor_headers(case_id, "claimant"),
    )
    assert admitted.status_code == 200, admitted.text


def accept_terms(client, case_id, version=None):
    for party in ("claimant", "respondent"):
        payload = {"party": party, "accepted": True}
        if version is not None:
            payload["terms_version"] = version
        response = client.post(
            f"/cases/{case_id}/consent",
            json=payload,
            headers=actor_headers(case_id, party),
        )
        assert response.status_code == 200, response.text
    return response.json()


# --- termos versionados -----------------------------------------------------


def test_terms_endpoint_serves_text_version_and_hash(client):
    body = client.get("/terms").json()
    assert body["version"] == terms_module.current_version()
    assert body["sha256"] == terms_module.current_terms().sha256
    assert "Participação voluntária" in body["text"]
    assert body["available_versions"] == terms_module.list_versions()


def test_specific_version_is_addressable_and_unknown_is_404(client):
    version = terms_module.current_version()
    assert client.get(f"/terms/{version}").json()["current"] is True
    assert client.get("/terms/1999-01-01").status_code == 404


def test_consent_records_the_hash_of_the_text_shown(client):
    case = create_case(client)
    consent = accept_terms(client, case["id"])

    expected = terms_module.current_terms()
    for party in ("claimant", "respondent"):
        assert consent[party]["terms_version"] == expected.version
        assert consent[party]["terms_sha256"] == expected.sha256


def test_consent_with_an_unknown_terms_version_is_rejected(client):
    case = create_case(client)
    response = client.post(
        f"/cases/{case['id']}/consent",
        json={"party": "claimant", "accepted": True, "terms_version": "1999-01-01"},
        headers=actor_headers(case["id"], "claimant"),
    )
    assert response.status_code == 422
    assert "desconhecida" in response.json()["detail"]


def test_withdrawing_consent_clears_the_recorded_terms(client):
    case = create_case(client)
    accept_terms(client, case["id"])
    response = client.post(
        f"/cases/{case['id']}/consent",
        json={"party": "claimant", "accepted": False},
        headers=actor_headers(case["id"], "claimant"),
    )
    assert response.json()["claimant"]["terms_sha256"] is None


def test_consent_hash_reaches_the_audit_chain(client):
    case = create_case(client)
    accept_terms(client, case["id"])
    events = client.get(f"/cases/{case['id']}").json()["audit_log"]
    accepted = [item for item in events if item["event_type"] == "consent_accepted"]
    assert accepted
    assert all(
        event["payload"]["terms_sha256"] == terms_module.current_terms().sha256
        for event in accepted
    )


def test_locked_manifest_carries_the_accepted_terms(client):
    case = create_case(client)
    document = add_document(client, case["id"])
    complete_contradictory(client, case["id"], document["id"])
    accept_terms(client, case["id"])

    manifest = client.post(
        f"/cases/{case['id']}/lock", headers=actor_headers(case["id"], "claimant")
    ).json()["manifest"]

    current = terms_module.current_terms()
    assert manifest["terms"]["current_sha256"] == current.sha256
    assert manifest["terms"]["accepted"]["claimant"]["sha256"] == current.sha256
    assert manifest["terms"]["accepted"]["respondent"]["sha256"] == current.sha256

    verification = client.get(f"/cases/{case['id']}/manifest/verify").json()
    assert verification["hash_valid"] is True
    assert verification["signature_valid"] is True


def test_lock_is_blocked_when_the_accepted_text_no_longer_reproduces(
    client, monkeypatch
):
    """Editar um texto já publicado quebraria a prova do aceite. O caso não
    pode ser travado nesse estado."""
    case = create_case(client)
    document = add_document(client, case["id"])
    complete_contradictory(client, case["id"], document["id"])
    accept_terms(client, case["id"])

    original = terms_module.current_terms()
    adulterated = terms_module.Terms(
        version=original.version,
        text=original.text + "\ncláusula acrescentada depois do aceite\n",
        sha256="0" * 64,
    )
    monkeypatch.setattr(main, "get_terms", lambda version=None: adulterated)

    response = client.post(
        f"/cases/{case['id']}/lock", headers=actor_headers(case["id"], "claimant")
    )
    assert response.status_code == 409
    assert "mudou depois do aceite" in response.json()["detail"]


# --- procedência das etapas de IA -------------------------------------------


def test_every_agent_registers_a_versioned_prompt():
    policy = prompt_policy()
    assert set(policy) == {"appeal", "conciliator", "judge", "organizer", "reviewer"}
    for agent, reference in policy.items():
        assert reference["version"]
        assert len(reference["sha256"]) == 64
        assert reference["sha256"] == get_prompt(agent).sha256


def test_prompt_hash_changes_when_the_text_changes():
    first = register_prompt("agente_de_teste", "1.0.0", "texto original")
    second = register_prompt("agente_de_teste", "1.0.0", "texto editado")
    assert first.sha256 != second.sha256


def test_locked_manifest_pins_the_prompt_policy(client):
    case = create_case(client)
    document = add_document(client, case["id"])
    complete_contradictory(client, case["id"], document["id"])
    accept_terms(client, case["id"])

    manifest = client.post(
        f"/cases/{case['id']}/lock", headers=actor_headers(case["id"], "claimant")
    ).json()["manifest"]

    prompts = manifest["model_policy"]["prompts"]
    assert prompts["judge"]["sha256"] == get_prompt("judge").sha256
    assert prompts["reviewer"]["version"] == get_prompt("reviewer").version


def test_stage_execution_records_prompt_and_model(client):
    case = create_case(client)
    document = add_document(client, case["id"])
    complete_contradictory(client, case["id"], document["id"])
    accept_terms(client, case["id"])
    client.post(f"/cases/{case['id']}/lock", headers=actor_headers(case["id"], "claimant"))

    conciliation = client.post(
        f"/cases/{case['id']}/conciliation",
        json={"claimant_response": "", "respondent_response": "", "new_information": ""},
        headers=actor_headers(case["id"], "claimant"),
    ).json()

    execution = conciliation["execution"]
    # Sem OPENAI_API_KEY o caminho é o de contingência: mesmo aí a procedência
    # do prompt precisa estar registrada.
    assert execution["mode"] == "safe_fallback"
    assert execution["prompt"] == get_prompt("conciliator").as_reference()
    assert execution["model"] is None
    assert execution["model_requested"]


def test_drift_between_locked_and_running_prompt_is_detected():
    manifest = {
        "model_policy": {
            "prompts": {
                "judge": {
                    "agent": "judge",
                    "version": "0.9.0",
                    "sha256": "a" * 64,
                }
            }
        }
    }
    drift = detect_drift(manifest, "judge")
    assert drift is not None
    assert drift["locked_version"] == "0.9.0"
    assert drift["running_sha256"] == get_prompt("judge").sha256

    aligned = {
        "model_policy": {"prompts": {"judge": get_prompt("judge").as_reference()}}
    }
    assert detect_drift(aligned, "judge") is None
    # Manifesto antigo, sem política de prompts, não vira alarme falso.
    assert detect_drift({"model_policy": {}}, "judge") is None


def test_drift_is_annotated_on_the_executed_stage(client, monkeypatch):
    case = create_case(client)
    document = add_document(client, case["id"])
    complete_contradictory(client, case["id"], document["id"])
    accept_terms(client, case["id"])
    client.post(f"/cases/{case['id']}/lock", headers=actor_headers(case["id"], "claimant"))

    monkeypatch.setattr(
        main,
        "detect_drift",
        lambda manifest, agent: {
            "agent": agent,
            "locked_version": "0.9.0",
            "locked_sha256": "a" * 64,
            "running_version": "1.0.0",
            "running_sha256": "b" * 64,
        },
    )

    conciliation = client.post(
        f"/cases/{case['id']}/conciliation",
        json={"claimant_response": "", "respondent_response": "", "new_information": ""},
        headers=actor_headers(case["id"], "claimant"),
    ).json()

    assert conciliation["execution"]["prompt_drift"]["locked_version"] == "0.9.0"
    events = client.get(f"/cases/{case['id']}").json()["audit_log"]
    screened = [e for e in events if e["event_type"] == "conciliation_screened"][-1]
    assert screened["payload"]["execution"]["prompt_drift"]["agent"] == "conciliator"
