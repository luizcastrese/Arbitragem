"""Leads do piloto: gravam no banco e avisam o time por e-mail."""

from dataclasses import replace

from app.api import context
from app.core import email as email_module
from app.db.models import PilotLead
from tests.test_api import client  # noqa: F401 - fixture


LEAD = {
    "name": "Carla Souza",
    "company": "Banco Exemplo S.A.",
    "email": "Carla@Exemplo.com",
    "monthly_volume": 250,
}


def _leads(client):
    from app.db.session import get_db
    from app.main import app

    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        return db.query(PilotLead).all()
    finally:
        db.close()


def test_lead_is_stored_and_the_team_is_notified(client, monkeypatch):
    sent = []

    def fake_deliver(message, *, kind, to_email):
        sent.append((kind, to_email, message))
        return {"delivered": True, "transport": "smtp"}

    monkeypatch.setattr(email_module, "_deliver", fake_deliver)
    monkeypatch.setattr(
        email_module,
        "get_settings",
        lambda: replace(
            context.settings,
            lead_notification_email="piloto@valinor.example",
            smtp_from="no-reply@valinor.example",
        ),
    )
    response = client.post("/leads", json=LEAD)
    assert response.status_code == 201
    assert response.json() == {"received": True}

    [lead] = _leads(client)
    assert lead.email == "carla@exemplo.com"
    assert lead.monthly_volume == 250
    assert lead.notification_status == "delivered"
    kind, to_email, message = sent[0]
    assert (kind, to_email) == ("lead_notification", "piloto@valinor.example")
    assert message["Reply-To"] == "carla@exemplo.com"
    body = message.get_content()
    assert "Banco Exemplo S.A." in body and "250" in body


def test_lead_is_stored_even_without_a_recipient(client, monkeypatch):
    monkeypatch.setattr(
        email_module,
        "get_settings",
        lambda: replace(context.settings, lead_notification_email="", privacy_contact_email=""),
    )
    assert client.post("/leads", json=LEAD).status_code == 201
    [lead] = _leads(client)
    assert lead.notification_status == "logged"


def test_failed_notification_does_not_lose_the_lead(client, monkeypatch):
    monkeypatch.setattr(
        email_module,
        "_deliver",
        lambda message, *, kind, to_email: {"delivered": False, "error": "SMTPException"},
    )
    monkeypatch.setattr(
        email_module,
        "get_settings",
        lambda: replace(context.settings, lead_notification_email="piloto@valinor.example"),
    )
    assert client.post("/leads", json=LEAD).status_code == 201
    [lead] = _leads(client)
    assert lead.notification_status == "failed"
    assert lead.notified_at is None


def test_honeypot_is_accepted_but_not_stored(client):
    response = client.post("/leads", json={**LEAD, "website": "http://spam.example"})
    assert response.status_code == 201
    assert _leads(client) == []


def test_invalid_lead_is_rejected(client):
    assert client.post("/leads", json={**LEAD, "email": "sem-arroba"}).status_code == 422
    assert client.post("/leads", json={**LEAD, "monthly_volume": -1}).status_code == 422
    assert client.post("/leads", json={**LEAD, "name": ""}).status_code == 422
    assert _leads(client) == []


def test_lead_form_shares_the_credential_rate_limit(client):
    assert "/leads" in context.AUTH_RATE_LIMITED_PATHS
