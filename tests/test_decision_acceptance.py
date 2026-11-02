"""Acatamento bilateral da decisão da IA como acordo, sem árbitro humano.

Cada parte acata por ato próprio, depois do prazo de reflexão; com as duas, a
decisão vale como acordo (CC, art. 840), o auto é reemitido com esse efeito e o
pagamento opcional não espera o prazo de recurso. Acatamento e sentença
arbitral são desfechos excludentes, e quem acatou não recorre.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Case
from app.db.session import get_db
from app.domain import acceptance as acc
from app.domain.pathway import legal_effect
from app.domain.settlement import settlement_offer
from app.main import app
from tests.test_api import (  # noqa: F401  (fixture)
    actor_headers,
    add_contract,
    client,
    complete_contradictory,
    declare_submissions_ready,
    steward_headers,
)
from tests.test_arbitrator import (
    _accept_nomination,
    _confirm,
    _consent,
    _designated_locked_case,
    _force_final_decision,
    _invite_arbitrator,
    _new_case,
    _sign,
)

ATT = "a" * 64


def _attest(case_id, *, issued_hours_ago=48, window_days=5, attestation_hash=ATT):
    """Sem modelo a decisão é inconclusiva: grava uma de mérito já atestada."""
    _force_final_decision(case_id, window_days=window_days)
    db = next(app.dependency_overrides[get_db]())
    row = db.get(Case, case_id)
    row.attestation_json = json.dumps(
        {
            "attestation_hash": attestation_hash,
            "issued_at_utc": (
                datetime.now(timezone.utc) - timedelta(hours=issued_hours_ago)
            ).isoformat(),
            "contest_window_ends_utc": (
                datetime.now(timezone.utc) + timedelta(days=window_days)
            ).isoformat(),
        }
    )
    db.commit()
    db.close()


def _locked_case_without_arbitrator(client):
    case_id = _new_case(client)
    _consent(client, case_id, elects=False)
    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])
    declare_submissions_ready(client, case_id)
    assert client.post(f"/cases/{case_id}/lock", headers=steward_headers()).status_code == 200
    return case_id


def _accept(client, case_id, party, confirm=True):
    return client.post(
        f"/cases/{case_id}/accept-decision",
        json={"party": party, "confirm": confirm},
        headers=actor_headers(case_id, party),
    )


def _state(client, case_id):
    response = client.get(f"/cases/{case_id}/decision-acceptance")
    assert response.status_code == 200, response.text
    return response.json()


# --- domínio -------------------------------------------------------------------


def _data(**overrides):
    base = {
        "status": "attested",
        "attestation": {
            "attestation_hash": ATT,
            "issued_at_utc": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
        },
        "procedure_conclusion": "decided",
        "verification": {"valid": True},
        "decision": {"outcome": "claimant"},
        "appeals": [],
        "contest": {"contested": False},
        "decision_acceptances": [],
    }
    base.update(overrides)
    return base


def _accepted(party, attestation_hash=ATT):
    return {"party": party, "attestation_hash": attestation_hash, "recorded_at": "2026-11-03T10:00:00+00:00"}


def test_acceptance_needs_both_parties_for_the_current_attestation():
    assert acc.acceptance_status(_data())["complete"] is False
    one = _data(decision_acceptances=[_accepted("claimant")])
    assert acc.acceptance_status(one)["any"] is True
    assert acc.acceptance_status(one)["complete"] is False
    both = _data(decision_acceptances=[_accepted("claimant"), _accepted("respondent")])
    assert acc.acceptance_status(both)["complete"] is True


def test_acceptance_of_a_superseded_decision_does_not_count():
    stale = _data(
        decision_acceptances=[
            _accepted("claimant", "b" * 64),
            _accepted("respondent", "b" * 64),
        ]
    )
    assert acc.acceptance_status(stale)["any"] is False


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"status": "withdrawn"}, "withdrawn"),
        ({"status": "processing_review"}, "stage_running"),
        ({"attestation": None}, "attestation_not_issued"),
        ({"procedure_conclusion": "inconclusive"}, "no_merit_decision"),
        ({"verification": {"valid": False}}, "decision_not_verified"),
        ({"appeals": [{"completed_at": None}]}, "appeal_pending"),
        ({"arbitral_award": {"adopted": True}}, "arbitral_award_signed"),
        (
            {
                "attestation": {
                    "attestation_hash": ATT,
                    "issued_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            },
            "reflection_period",
        ),
    ],
)
def test_acceptance_blocked(overrides, code):
    can, blocked, reason = acc.eligibility(_data(**overrides))
    assert can is False and blocked == code and reason


def test_acceptance_open_after_the_reflection_period():
    assert acc.eligibility(_data()) == (True, None, None)


def test_accepted_decision_is_an_agreement_without_arbitrator():
    status = acc.acceptance_status(
        _data(decision_acceptances=[_accepted("claimant"), _accepted("respondent")])
    )
    effect = legal_effect({"entry_point": "pre_litigation"}, "decision", None, status)
    assert effect["binding"] is True
    assert effect["instrument"] == "termo_de_acordo_extrajudicial"
    assert "Código Civil, art. 840 (transação)" in effect["legal_basis"]
    assert effect["decision_acceptance"]["attestation_hash"] == ATT
    assert effect["arbitral_award"] is None

    pending = legal_effect(
        {
            "entry_point": "pending_lawsuit",
            "lawsuit": {"number": "0000001-00.2020.8.26.0001", "court": "1ª Vara"},
        },
        "decision",
        None,
        status,
    )
    assert pending["instrument"] == "termo_de_acordo_para_homologacao"
    assert pending["ends_lawsuit_by"] == "homologacao_de_acordo"


def test_one_acceptance_is_not_yet_an_agreement():
    status = acc.acceptance_status(_data(decision_acceptances=[_accepted("claimant")]))
    effect = legal_effect({}, "decision", None, status)
    assert effect["binding"] is False
    assert effect["decision_acceptance"] is None


def test_signed_award_prevails_over_acceptance():
    status = {"complete": True, "attestation_hash": ATT, "parties": {}}
    effect = legal_effect({}, "decision", {"adopted": True, "place": "SP"}, status)
    assert effect["decision_acceptance"] is None


def test_settlement_does_not_wait_for_the_window_once_both_accepted():
    window_open = _data(
        attestation={
            "attestation_hash": ATT,
            "contest_window_ends_utc": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
        },
        attestation_records=[{"attestation_hash": ATT}],
        decision={
            "outcome": "claimant",
            "remedy_calculation": {"result_minor_units": 18000, "currency": "BRL"},
        },
    )
    assert settlement_offer(window_open)["reason"] == "contest_window_open"
    window_open["decision_acceptances"] = [_accepted("claimant")]
    assert settlement_offer(window_open)["reason"] == "contest_window_open"
    window_open["decision_acceptances"].append(_accepted("respondent"))
    offer = settlement_offer(window_open)
    assert offer["available"] is True
    assert offer["accepted_by_both_parties"] is True
    assert offer["amount_minor_units"] == 18000


# --- API -----------------------------------------------------------------------


def test_both_parties_accept_and_the_decision_becomes_an_agreement(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)

    state = _state(client, case_id)
    assert state["can_accept"] is True
    assert state["statement"]["sha256"] == acc.STATEMENT_SHA256

    before = client.post(
        f"/cases/{case_id}/decision-record", headers=actor_headers(case_id, "claimant")
    ).json()
    assert before["legal_effect"]["binding"] is False

    first = _accept(client, case_id, "claimant")
    assert first.status_code == 200, first.text
    assert first.json()["complete"] is False
    assert first.json()["decision_record"] is None

    second = _accept(client, case_id, "respondent")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["complete"] is True
    record = body["decision_record"]
    assert record["outcome"]["binding"] is True
    effect = record["legal_effect"]
    assert effect["instrument"] == "termo_de_acordo_extrajudicial"
    assert effect["decision_acceptance"]["attestation_hash"] == ATT
    assert record["supersedes_record_hash"] == before["record_hash"]
    assert "acataram e a adotaram como seu acordo" in record["legal_notice"]
    assert client.post("/decision-records/verify", json={"record": record}).json()["valid"] is True
    docx = client.get(f"/cases/{case_id}/decision-record.docx", headers=actor_headers(case_id, "claimant"))
    assert docx.status_code == 200

    events = [e["event_type"] for e in client.get(f"/cases/{case_id}/audit").json()["events"]]
    assert events.count("decision_accepted") == 2


def test_payment_opens_before_the_appeal_window_ends(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)
    db = next(app.dependency_overrides[get_db]())
    from app.db.repository import case_to_dict, get_case

    def offer():
        data = case_to_dict(get_case(db, case_id), include_content=False)
        data["attestation_records"] = [{"attestation_hash": ATT}]
        return settlement_offer(data)

    assert offer()["reason"] == "contest_window_open"
    _accept(client, case_id, "claimant")
    _accept(client, case_id, "respondent")
    db.expire_all()
    assert offer()["available"] is True
    db.close()


def test_acceptance_is_idempotent(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)
    assert _accept(client, case_id, "claimant").status_code == 200
    assert _accept(client, case_id, "claimant").status_code == 200
    events = [e["event_type"] for e in client.get(f"/cases/{case_id}/audit").json()["events"]]
    assert events.count("decision_accepted") == 1


def test_reflection_period_blocks_early_acceptance(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id, issued_hours_ago=1)
    response = _accept(client, case_id, "claimant")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "reflection_period"
    assert _state(client, case_id)["can_accept"] is False


def test_explicit_confirmation_is_required(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)
    assert _accept(client, case_id, "claimant", confirm=False).status_code == 422


def test_a_party_cannot_accept_for_the_other(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)
    response = client.post(
        f"/cases/{case_id}/accept-decision",
        json={"party": "respondent", "confirm": True},
        headers=actor_headers(case_id, "claimant"),
    )
    assert response.status_code == 403


def test_no_acceptance_without_a_merit_decision(client):
    case_id = _locked_case_without_arbitrator(client)
    assert _accept(client, case_id, "claimant").status_code == 409


def test_who_accepted_cannot_appeal(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)
    _accept(client, case_id, "claimant")
    response = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Discordo do cálculo", "explanation": "Discordo do cálculo"},
        headers=actor_headers(case_id, "claimant"),
    )
    assert response.status_code == 409
    assert "irrevogável" in response.json()["detail"]


def test_nobody_appeals_once_both_accepted(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)
    _accept(client, case_id, "claimant")
    _accept(client, case_id, "respondent")
    response = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Discordo do cálculo", "explanation": "Discordo do cálculo"},
        headers=actor_headers(case_id, "respondent"),
    )
    assert response.status_code == 409


def test_acceptance_is_bound_to_the_attestation_that_was_read(client):
    case_id = _locked_case_without_arbitrator(client)
    _attest(case_id)
    _accept(client, case_id, "claimant")
    _attest(case_id, attestation_hash="c" * 64)  # um recurso corrigiu a decisão
    state = _state(client, case_id)
    assert state["parties"]["claimant"] is None
    assert state["complete"] is False


def test_arbitrated_case_may_still_be_accepted_without_the_arbitrator(client):
    case_id, arbitrator, _ = _designated_locked_case(client)
    _attest(case_id)
    _accept(client, case_id, "claimant")
    record = _accept(client, case_id, "respondent").json()["decision_record"]
    assert record["legal_effect"]["instrument"] == "termo_de_acordo_extrajudicial"
    assert record["legal_effect"]["arbitral_award"] is None
    # Acatamento e sentença arbitral são excludentes: o árbitro não assina mais.
    assert _sign(client, case_id, arbitrator).status_code == 409


def test_acceptance_is_refused_after_the_award_is_signed(client):
    case_id, arbitrator, _ = _designated_locked_case(client)
    _attest(case_id, window_days=-1)
    assert _sign(client, case_id, arbitrator).status_code == 200
    response = _accept(client, case_id, "claimant")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "arbitral_award_signed"


def test_one_acceptance_does_not_stop_the_arbitrator(client):
    case_id, arbitrator, _ = _designated_locked_case(client)
    _attest(case_id, window_days=-1)
    _accept(client, case_id, "claimant")
    assert _sign(client, case_id, arbitrator).status_code == 200
