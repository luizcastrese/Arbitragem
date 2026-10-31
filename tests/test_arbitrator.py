"""Árbitro pessoa física: designação pelas partes e assinatura da sentença.

A IA elabora a decisão; só o árbitro aceito e confirmado pelas duas partes,
antes da trava, pode adotá-la e assiná-la como sentença arbitral (Lei
9.307/96, arts. 10, 13, 14 e 26).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.db.models import Case
from app.db.session import get_db
from app.main import app
from tests.test_api import (  # noqa: F401  (fixture)
    CASE_CREDENTIALS,
    actor_headers,
    add_contract,
    client,
    complete_contradictory,
    declare_submissions_ready,
    register_user,
    steward_headers,
)

CPF = "52998224725"


def _new_case(client):
    response = client.post(
        "/cases",
        json={
            "title": "Tarifa de pacote não contratado",
            "claimant": "Maria Consumidora",
            "respondent": "Banco Exemplo S.A.",
        },
    )
    assert response.status_code == 201, response.text
    case = response.json()
    CASE_CREDENTIALS[case["id"]] = case.pop("access_credentials")
    return case["id"]


def _consent(client, case_id, elects=True):
    for party in ("claimant", "respondent"):
        response = client.post(
            f"/cases/{case_id}/consent",
            json={"party": party, "accepted": True, "elects_arbitration": elects},
            headers=actor_headers(case_id, party),
        )
        assert response.status_code == 200, response.text


def _invite_arbitrator(client, case_id, email="arbitra@example.com"):
    invite = client.post(
        f"/cases/{case_id}/invitations",
        json={"email": email, "role": "arbitrator"},
        headers=actor_headers(case_id, "claimant"),
    )
    assert invite.status_code == 201, invite.text
    arbitrator = register_user(client, "Ana Árbitra", email)
    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": arbitrator["session_token"]},
        json={"token": invite.json()["acceptance_token"]},
    )
    assert accepted.status_code == 200, accepted.text
    return {"X-Actor-Token": arbitrator["session_token"]}


def _accept_nomination(client, case_id, headers, disclosure=""):
    return client.post(
        f"/cases/{case_id}/arbitrator/accept",
        json={
            "tax_id": CPF,
            "qualification": "Advogada, domiciliada em São Paulo/SP",
            "independent": True,
            "disclosure": disclosure,
        },
        headers=headers,
    )


def _confirm(client, case_id, party):
    return client.post(
        f"/cases/{case_id}/arbitrator/confirm",
        json={"party": party},
        headers=actor_headers(case_id, party),
    )


def _designated_locked_case(client):
    case_id = _new_case(client)
    _consent(client, case_id)
    arbitrator = _invite_arbitrator(client, case_id)
    assert _accept_nomination(client, case_id, arbitrator).status_code == 200
    for party in ("claimant", "respondent"):
        assert _confirm(client, case_id, party).status_code == 200
    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])
    declare_submissions_ready(client, case_id)
    locked = client.post(f"/cases/{case_id}/lock", headers=steward_headers())
    assert locked.status_code == 200, locked.text
    return case_id, arbitrator, locked.json()["manifest"]


def _force_final_decision(case_id, *, window_days=-1):
    """Sem modelo, a decisão é sempre inconclusiva: grava uma de mérito."""
    db = next(app.dependency_overrides[get_db]())
    row = db.get(Case, case_id)
    row.status = "reviewed"
    row.procedure_conclusion = "decided"
    row.verification_json = json.dumps({"valid": True})
    row.decision_json = json.dumps(
        {
            "framework_id": "consumer_banking_v1",
            "framework_version": "1.0.0",
            "outcome": "claimant",
            "procedure_conclusion": "decided",
            "decision": "Restituir em dobro a tarifa sem previsão contratual.",
            "confidence": 0.9,
            "remedy_calculation": {
                "formula": "refund = 2 * 9000",
                "inputs": [],
                "result_minor_units": 18000,
                "currency": "BRL",
            },
        }
    )
    row.review_json = json.dumps({"outcome": "approved", "approved": True, "confidence": 0.9})
    row.attestation_json = json.dumps(
        {
            "attestation_hash": "a" * 64,
            "contest_window_ends_utc": (
                datetime.now(timezone.utc) + timedelta(days=window_days)
            ).isoformat(),
        }
    )
    db.commit()
    db.close()


def _sign(client, case_id, headers, adopt=True):
    return client.post(
        f"/cases/{case_id}/arbitral-award",
        json={"adopt": adopt, "place": "São Paulo/SP", "statement": "Adoto os fundamentos."},
        headers=headers,
    )


def test_designation_is_frozen_in_the_manifest(client):
    case_id, _, manifest = _designated_locked_case(client)
    pathway = manifest["pathway"]
    assert pathway["resolution_track"] == "arbitration"
    assert pathway["arbitrator_designated"] is True
    assert pathway["arbitrator"]["display_name"] == "Ana Árbitra"
    events = [e["event_type"] for e in client.get(f"/cases/{case_id}/audit").json()["events"]]
    assert "arbitrator_accepted" in events
    assert events.count("arbitrator_confirmed") == 2


def test_arbitrator_adopts_and_signs_the_final_decision(client):
    case_id, arbitrator, _ = _designated_locked_case(client)
    _force_final_decision(case_id)

    before = client.post(f"/cases/{case_id}/decision-record", headers=actor_headers(case_id, "claimant")).json()
    assert before["legal_effect"]["binding"] is False
    assert "aguarda a assinatura de Ana Árbitra" in before["legal_effect"]["instrument_label"]

    signed = _sign(client, case_id, arbitrator)
    assert signed.status_code == 200, signed.text
    record = signed.json()
    effect = record["legal_effect"]
    assert effect["instrument"] == "sentenca_arbitral"
    assert effect["instrument_label"] == "Sentença arbitral"
    assert effect["binding"] is True and record["outcome"]["binding"] is True
    assert effect["pending"] == []
    assert effect["arbitral_award"]["adopted_record_hash"] == before["record_hash"]
    assert effect["arbitral_award"]["place"] == "São Paulo/SP"
    assert record["supersedes_record_hash"] == before["record_hash"]
    assert "adotou e assinou" in record["legal_notice"]
    assert client.post("/decision-records/verify", json={"record": record}).json()["valid"] is True
    docx = client.get(f"/cases/{case_id}/decision-record.docx", headers=actor_headers(case_id, "claimant"))
    assert docx.status_code == 200

    assert _sign(client, case_id, arbitrator).status_code == 409


def test_arbitrator_may_decline(client):
    case_id, arbitrator, _ = _designated_locked_case(client)
    _force_final_decision(case_id)
    record = _sign(client, case_id, arbitrator, adopt=False).json()
    assert record["legal_effect"]["binding"] is False
    assert record["legal_effect"]["instrument"] == "decisao_nao_vinculante"
    assert record["legal_effect"]["pending"]


def test_signature_waits_for_the_appeal_window(client):
    case_id, arbitrator, _ = _designated_locked_case(client)
    _force_final_decision(case_id, window_days=3)
    response = _sign(client, case_id, arbitrator)
    assert response.status_code == 409
    assert "prazo de recurso" in response.json()["detail"]


def test_parties_cannot_act_as_arbitrator_and_must_elect_first(client):
    case_id = _new_case(client)
    _consent(client, case_id, elects=False)
    arbitrator = _invite_arbitrator(client, case_id)
    assert _accept_nomination(client, case_id, arbitrator).status_code == 200
    # Sem ter escolhido a arbitragem, a parte não confirma árbitro.
    assert _confirm(client, case_id, "claimant").status_code == 409
    # Parte não assina sentença.
    assert _sign(client, case_id, actor_headers(case_id, "claimant")).status_code == 403


def test_reacceptance_resets_confirmations_and_lock_closes_designation(client):
    case_id = _new_case(client)
    _consent(client, case_id)
    arbitrator = _invite_arbitrator(client, case_id)
    _accept_nomination(client, case_id, arbitrator)
    _confirm(client, case_id, "claimant")
    _confirm(client, case_id, "respondent")
    assert client.get(f"/cases/{case_id}").json()["pathway"]["arbitrator_designated"] is True

    # Uma revelação nova exige nova confirmação das duas partes.
    _accept_nomination(client, case_id, arbitrator, disclosure="Fui colega de turma do advogado do banco.")
    pathway = client.get(f"/cases/{case_id}").json()["pathway"]
    assert pathway["arbitrator_designated"] is False

    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])
    declare_submissions_ready(client, case_id)
    assert client.post(f"/cases/{case_id}/lock", headers=steward_headers()).status_code == 200
    assert _confirm(client, case_id, "claimant").status_code == 409


def test_without_designated_arbitrator_there_is_no_award(client):
    case_id = _new_case(client)
    _consent(client, case_id)
    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])
    declare_submissions_ready(client, case_id)
    client.post(f"/cases/{case_id}/lock", headers=steward_headers())
    _force_final_decision(case_id)
    record = client.post(f"/cases/{case_id}/decision-record", headers=actor_headers(case_id, "claimant")).json()
    assert record["legal_effect"]["instrument"] == "decisao_nao_vinculante"
    assert "nenhum árbitro" in record["legal_effect"]["instrument_label"]
