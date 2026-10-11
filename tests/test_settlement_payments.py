"""Pagamento opcional da decisão: oferta, Checkout (Stripe Connect) e webhook.

O Stripe é trocado na fronteira (`app.core.payments`); a validação de assinatura
do webhook usa a biblioteca de verdade.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import payments as gateway
from app.core.config import get_settings
from app.db.models import AttestationRecord, Base, Case, CaseMember, SettlementPayment, User
from app.db.session import get_db
from app.domain.settlement import platform_fee, settlement_offer
from app.main import app

WEBHOOK_SECRET = "whsec_test"
ATT_HASH = "a" * 64


def _case_data(**overrides):
    base = {
        "attestation": {
            "contest_window_ends_utc": (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat()
        },
        "attestation_records": [{"attestation_hash": ATT_HASH}],
        "procedure_conclusion": "decided",
        "verification": {"valid": True},
        "decision": {
            "outcome": "claimant",
            "remedy_calculation": {"result_minor_units": 100_000, "currency": "brl"},
        },
        "appeals": [],
    }
    base.update(overrides)
    return base


def test_platform_fee_is_ten_percent_rounded_down():
    assert platform_fee(100_000, 1000) == 10_000
    assert platform_fee(999, 1000) == 99
    assert platform_fee(5, 1000) == 0


def test_offer_splits_ninety_ten():
    offer = settlement_offer(_case_data())
    assert offer["available"] is True
    assert offer["amount_minor_units"] == 100_000
    assert offer["platform_fee_minor_units"] == 10_000
    assert offer["net_to_payee_minor_units"] == 90_000
    assert offer["currency"] == "BRL"
    assert offer["payer_role"] == "respondent"
    assert offer["payee_role"] == "claimant"
    assert offer["attestation_hash"] == ATT_HASH


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"attestation": None, "attestation_records": []}, "attestation_not_issued"),
        ({"procedure_conclusion": "inconclusive"}, "no_merit_decision"),
        ({"verification": {"valid": False}}, "decision_not_verified"),
        ({"decision": {"outcome": "respondent"}}, "no_amount_owed"),
        ({"decision": {"outcome": "claimant"}}, "no_verified_amount"),
        (
            {
                "decision": {
                    "outcome": "claimant",
                    "remedy_calculation": {"result_minor_units": 0, "currency": "BRL"},
                }
            },
            "no_verified_amount",
        ),
        (
            {"appeals": [{"status": "filed", "completed_at": None}]},
            "appeal_pending",
        ),
    ],
)
def test_offer_unavailable(overrides, reason):
    offer = settlement_offer(_case_data(**overrides))
    assert offer["available"] is False
    assert offer["reason"] == reason


def test_offer_waits_for_contest_window():
    open_window = {
        "contest_window_ends_utc": (
            datetime.now(timezone.utc) + timedelta(days=2)
        ).isoformat()
    }
    offer = settlement_offer(_case_data(attestation=open_window))
    assert offer["available"] is False
    assert offer["reason"] == "contest_window_open"
    # Recurso concluído antecipa a oferta mesmo com a janela ainda aberta.
    done = [{"status": "upheld", "completed_at": "2026-10-11T00:00:00+00:00"}]
    assert settlement_offer(_case_data(attestation=open_window, appeals=done))[
        "available"
    ]


# --- API ---------------------------------------------------------------------


class FakeStripe:
    def __init__(self):
        self.accounts_ready = True
        self.sessions = {}
        self.created = []

    def account_ready(self, account_id):
        return self.accounts_ready

    def create_checkout_session(self, **kwargs):
        sid = f"cs_test_{len(self.created) + 1}"
        self.created.append(kwargs)
        self.sessions[sid] = {"id": sid, "status": "open", "url": f"https://stripe/{sid}"}
        return sid, f"https://stripe/{sid}"

    def retrieve_checkout_session(self, session_id):
        return self.sessions[session_id]


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()
    fake = FakeStripe()
    monkeypatch.setattr(gateway, "account_ready", fake.account_ready)
    monkeypatch.setattr(gateway, "create_checkout_session", fake.create_checkout_session)
    monkeypatch.setattr(gateway, "retrieve_checkout_session", fake.retrieve_checkout_session)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, factory, fake
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    get_settings.cache_clear()


def _make_case(client, factory, *, outcome="claimant", window_days=-1, payee_account="acct_1"):
    response = client.post(
        "/cases",
        json={"title": "Site", "claimant": "Alfa", "respondent": "Beta"},
    )
    assert response.status_code == 201
    case = response.json()
    case_id = case["id"]
    with factory() as db:
        payee = User(
            id="u-payee", email="payee@example.com", display_name="Payee",
            password_hash="x", stripe_account_id=payee_account,
        )
        db.add(payee)
        db.flush()
        db.add(CaseMember(id="m1", case_id=case_id, user_id=payee.id, role="claimant"))
        row = db.get(Case, case_id)
        row.procedure_conclusion = "decided"
        row.verification_json = json.dumps({"valid": True})
        row.decision_json = json.dumps(
            {
                "outcome": outcome,
                "remedy_calculation": {"result_minor_units": 100_000, "currency": "BRL"},
            }
        )
        row.attestation_json = json.dumps(
            {
                "contest_window_ends_utc": (
                    datetime.now(timezone.utc) + timedelta(days=window_days)
                ).isoformat()
            }
        )
        db.add(
            AttestationRecord(
                id="att1", case_id=case_id, version=1, payload_json="{}",
                attestation_hash=ATT_HASH,
            )
        )
        db.commit()
    return case_id, case["access_credentials"]


def _sign(payload: bytes) -> dict:
    ts = int(time.time())
    digest = hmac.new(
        WEBHOOK_SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={digest}"}


def _event(event_type, session_id, *, payment_status="paid", amount=100_000, currency="brl"):
    return json.dumps(
        {
            "id": "evt_1",
            "object": "event",
            "type": event_type,
            "data": {
                "object": {
                    "id": session_id,
                    "object": "checkout.session",
                    "payment_status": payment_status,
                    "amount_total": amount,
                    "currency": currency,
                    "payment_intent": "pi_1",
                }
            },
        }
    ).encode()


def test_checkout_uses_destination_charge_with_ten_percent_fee(env):
    client, factory, fake = env
    case_id, creds = _make_case(client, factory)
    response = client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkout_url"].startswith("https://stripe/")
    assert body["payment"]["status"] == "pending"
    sent = fake.created[0]
    assert sent["amount_minor_units"] == 100_000
    assert sent["fee_minor_units"] == 10_000
    assert sent["currency"] == "BRL"
    assert sent["destination_account_id"] == "acct_1"

    # Repetir devolve a mesma sessão aberta, sem cobrar duas vezes.
    again = client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    assert again.json()["checkout_url"] == body["checkout_url"]
    assert len(fake.created) == 1


def test_only_respondent_can_open_checkout(env):
    client, factory, _ = env
    case_id, creds = _make_case(client, factory)
    for token in (creds["claimant"], "", "bogus"):
        response = client.post(
            f"/cases/{case_id}/settlement/checkout", headers={"X-Actor-Token": token}
        )
        assert response.status_code == 403


@pytest.mark.parametrize(
    "kwargs,detail",
    [
        ({"outcome": "respondent"}, "no_amount_owed"),
        ({"window_days": 2}, "contest_window_open"),
        ({"payee_account": None}, "payee_not_onboarded"),
    ],
)
def test_checkout_refused_when_not_offered(env, kwargs, detail):
    client, factory, fake = env
    case_id, creds = _make_case(client, factory, **kwargs)
    response = client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == detail
    assert fake.created == []


def test_checkout_refused_when_payee_account_not_ready(env):
    client, factory, fake = env
    fake.accounts_ready = False
    case_id, creds = _make_case(client, factory)
    response = client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "payee_not_onboarded"


def test_disabled_without_stripe_keys(env, monkeypatch):
    client, factory, _ = env
    case_id, creds = _make_case(client, factory)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    get_settings.cache_clear()
    response = client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    assert response.status_code == 503
    assert client.post("/stripe/webhook", content=b"{}").status_code == 503


def test_webhook_marks_paid_and_is_idempotent(env):
    client, factory, _ = env
    case_id, creds = _make_case(client, factory)
    client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    payload = _event("checkout.session.completed", "cs_test_1")
    for _ in range(2):
        response = client.post("/stripe/webhook", content=payload, headers=_sign(payload))
        assert response.status_code == 200

    view = client.get(f"/cases/{case_id}/settlement").json()
    assert view["payment"]["status"] == "paid"
    assert view["payment"]["paid_at"]
    with factory() as db:
        events = [e.event_type for e in db.get(Case, case_id).audit_events]
    assert events.count("settlement_payment_paid") == 1
    assert "settlement_checkout_created" in events

    again = client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "already_paid"


def test_webhook_rejects_bad_signature_and_amount_mismatch(env):
    client, factory, _ = env
    case_id, creds = _make_case(client, factory)
    client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    payload = _event("checkout.session.completed", "cs_test_1")
    assert (
        client.post(
            "/stripe/webhook", content=payload, headers={"Stripe-Signature": "t=1,v1=00"}
        ).status_code
        == 400
    )
    assert client.post("/stripe/webhook", content=payload).status_code == 400

    wrong = _event("checkout.session.completed", "cs_test_1", amount=1)
    assert client.post("/stripe/webhook", content=wrong, headers=_sign(wrong)).status_code == 200
    assert client.get(f"/cases/{case_id}/settlement").json()["payment"]["status"] == "pending"


def test_async_payment_waits_for_confirmation(env):
    client, factory, _ = env
    case_id, creds = _make_case(client, factory)
    client.post(
        f"/cases/{case_id}/settlement/checkout",
        headers={"X-Actor-Token": creds["respondent"]},
    )
    unpaid = _event("checkout.session.completed", "cs_test_1", payment_status="unpaid")
    client.post("/stripe/webhook", content=unpaid, headers=_sign(unpaid))
    assert client.get(f"/cases/{case_id}/settlement").json()["payment"]["status"] == "pending"
    ok = _event("checkout.session.async_payment_succeeded", "cs_test_1")
    client.post("/stripe/webhook", content=ok, headers=_sign(ok))
    assert client.get(f"/cases/{case_id}/settlement").json()["payment"]["status"] == "paid"


def test_expired_session_allows_a_new_checkout(env):
    client, factory, fake = env
    case_id, creds = _make_case(client, factory)
    headers = {"X-Actor-Token": creds["respondent"]}
    client.post(f"/cases/{case_id}/settlement/checkout", headers=headers)
    expired = _event("checkout.session.expired", "cs_test_1", payment_status="unpaid")
    client.post("/stripe/webhook", content=expired, headers=_sign(expired))
    fake.sessions["cs_test_1"]["status"] = "expired"
    response = client.post(f"/cases/{case_id}/settlement/checkout", headers=headers)
    assert response.status_code == 200
    assert len(fake.created) == 2
    assert response.json()["payment"]["status"] == "pending"
    with factory() as db:
        assert db.query(SettlementPayment).count() == 1


def test_paid_event_issues_a_new_record_version_and_blocks_a_second_charge(env, monkeypatch):
    from app import main

    client, factory, fake = env
    case_id, creds = _make_case(client, factory)
    issued = []
    monkeypatch.setattr(
        main, "_issue_decision_record_safely", lambda db, cid: issued.append(cid)
    )
    headers = {"X-Actor-Token": creds["respondent"]}
    client.post(f"/cases/{case_id}/settlement/checkout", headers=headers)
    paid = _event("checkout.session.completed", "cs_test_1")
    client.post("/stripe/webhook", content=paid, headers=_sign(paid))
    assert issued == [case_id]

    with factory() as db:
        db.add(
            AttestationRecord(
                id="att2", case_id=case_id, version=2, payload_json="{}",
                attestation_hash="b" * 64,
            )
        )
        db.commit()
    again = client.post(f"/cases/{case_id}/settlement/checkout", headers=headers)
    assert again.status_code == 409
    assert again.json()["detail"] == "already_paid"
    assert client.get(f"/cases/{case_id}/settlement").json()["payment"]["status"] == "paid"
