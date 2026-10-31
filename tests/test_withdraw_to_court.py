"""Opção pela via judicial: qualquer parte sai antes do desfecho, e as duas
recebem o auto com o histórico completo até ali para auditar."""

from __future__ import annotations

from tests.test_api import (  # noqa: F401  (fixture)
    accept_procedure,
    actor_headers,
    add_contract,
    client,
    create_case,
    prepare_locked_case,
    steward_headers,
)


def _withdraw(client, case_id, party="respondent", reason="Prefiro discutir no juizado."):
    return client.post(
        f"/cases/{case_id}/withdraw-to-court",
        json={"party": party, "reason": reason},
        headers=actor_headers(case_id, party),
    )


def test_party_leaves_before_lock_and_both_get_the_full_history(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]

    response = _withdraw(client, case_id)
    assert response.status_code == 200, response.text
    record = response.json()["decision_record"]

    assert record["outcome"]["kind"] == "withdrawn"
    assert record["outcome"]["procedure_conclusion"] == "withdrawn"
    assert record["outcome"]["binding"] is False
    assert "Fornecedor Beta optou pela via judicial" in record["outcome"]["summary"]
    assert "juizado" in record["outcome"]["summary"]
    assert record["withdrawal"]["party"] == "respondent"
    assert record["withdrawal"]["previous_status"] == "draft"
    assert record["decision"] is None and record["review"] is None
    assert "13.140/2015" in record["legal_notice"]
    assert record["legal_effect"]["instrument"] == "auto_de_encerramento_pela_via_judicial"

    # Histórico: o material e a trilha completa, encadeada até o topo.
    assert record["procedure"]["documents"][0]["sha256"] == document["sha256"]
    trail = record["audit_trail"]
    assert trail[0]["event_type"] == "case_created"
    assert trail[-1]["event_type"] == "withdrawn_to_court"
    assert trail[-1]["event_hash"] == record["integrity"]["audit_chain_head"]
    for previous, current in zip(trail, trail[1:]):
        assert current["previous_hash"] == previous["event_hash"]
    assert client.post("/decision-records/verify", json={"record": record}).json()["valid"] is True

    # As duas partes leem o mesmo auto, em JSON e em Word.
    for party in ("claimant", "respondent"):
        assert client.get(
            f"/cases/{case_id}/decision-record", headers=actor_headers(case_id, party)
        ).json()["record_hash"] == record["record_hash"]
    docx = client.get(
        f"/cases/{case_id}/decision-record.docx", headers=actor_headers(case_id, "claimant")
    )
    assert docx.status_code == 200

    audit = client.get(f"/cases/{case_id}/audit").json()
    assert audit["valid"] is True
    assert client.get(f"/cases/{case_id}/report").status_code == 200
    assert client.get(f"/cases/{case_id}/report.docx").status_code == 200


def test_closed_case_accepts_no_more_acts_and_withdrawal_is_idempotent(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    first = _withdraw(client, case_id, party="claimant").json()["decision_record"]

    blocked = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "novo.txt",
            "content": "Documento tardio.",
            "submitted_by": "claimant",
            "material_type": "evidence",
        },
        headers=actor_headers(case_id, "claimant"),
    )
    assert blocked.status_code == 409
    consent = client.post(
        f"/cases/{case_id}/consent",
        json={"party": "respondent", "accepted": False},
        headers=actor_headers(case_id, "respondent"),
    )
    assert consent.status_code == 409
    assert client.post(f"/cases/{case_id}/lock", headers=steward_headers()).status_code == 409

    again = _withdraw(client, case_id, party="respondent").json()["decision_record"]
    assert again["record_hash"] == first["record_hash"]
    assert again["record_number"] == 1


def test_party_can_leave_after_lock(client):
    case_id, _, _ = prepare_locked_case(client)
    response = _withdraw(client, case_id, party="claimant", reason="")
    assert response.status_code == 200, response.text
    record = response.json()["decision_record"]
    assert record["withdrawal"]["party"] == "claimant"
    assert record["integrity"]["manifest_hash"]
    assert client.post(
        f"/cases/{case_id}/conciliation", headers=steward_headers()
    ).status_code == 409


def test_only_the_party_itself_can_leave(client):
    case_id = create_case(client)["id"]
    response = client.post(
        f"/cases/{case_id}/withdraw-to-court",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "claimant"),
    )
    assert response.status_code == 403


def test_case_with_an_outcome_already_has_its_record(client):
    case_id, _, _ = prepare_locked_case(client)
    for stage in ("conciliation", "organize", "decide", "review"):
        assert client.post(
            f"/cases/{case_id}/{stage}?wait=120", headers=steward_headers()
        ).status_code == 200
    assert client.get(f"/cases/{case_id}").json()["status"] == "reviewed"
    assert _withdraw(client, case_id).status_code == 409
