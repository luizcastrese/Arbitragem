"""O caso precisa ser percorrível por duas pessoas reais.

Dois pontos travavam o piloto: a contraparte não lia o teor do material
antes de responder, e um convite perdido não tinha reemissão. Sem isso o
rito corre no vazio.
"""

from dataclasses import replace

from tests.test_api import (  # noqa: F401 - a fixture `client` vem daqui
    CASE_CREDENTIALS,
    add_contract,
    accept_procedure,
    client,
    create_case,
    register_user,
)

import app.main as main


def open_case_between(client, claimant, respondent_email):
    """Caso aberto pelo reclamante, com convite pendente para a contraparte."""
    created = client.post(
        "/cases",
        headers={"X-Session-Token": claimant["session_token"]},
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    )
    assert created.status_code == 201
    case = created.json()
    CASE_CREDENTIALS[case["id"]] = case.get("access_credentials") or {}
    invite = client.post(
        f"/cases/{case['id']}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": respondent_email, "role": "respondent"},
    )
    assert invite.status_code == 201
    return case["id"], invite.json()


def test_invitation_token_stays_off_the_api_in_production(client, monkeypatch):
    """Em produção o convite chega só por e-mail; a API não devolve o token."""
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, app_env="production", auth_required=True),
    )
    assert main.settings.allow_role_tokens is False

    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    _, invitation = open_case_between(client, claimant, "empresa@example.com")

    assert invitation["email_delivery"] == {"delivered": False, "transport": "log"}
    assert "acceptance_token" not in invitation
    assert "acceptance_path" not in invitation


def test_invitation_can_be_reissued_when_the_link_is_lost(client):
    """Quem convidou e perdeu o link não pode ficar preso.

    Um novo convite para o mesmo papel colide com o pendente. A reemissão
    revoga o token anterior para nunca existirem duas entradas válidas.
    """
    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    case_id, invitation = open_case_between(client, claimant, "empresa@example.com")
    old_token = invitation["acceptance_token"]

    duplicate = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "empresa@example.com", "role": "respondent"},
    )
    assert duplicate.status_code == 409

    resent = client.post(
        f"/cases/{case_id}/invitations/{invitation['id']}/resend",
        headers={"X-Actor-Token": claimant["session_token"]},
    )
    assert resent.status_code == 200
    new_token = resent.json()["acceptance_token"]
    assert new_token != old_token
    assert resent.json()["email_delivery"]["delivered"] is False

    company = register_user(client, "Empresa Delta", "empresa@example.com")
    stale = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": company["session_token"]},
        json={"token": old_token},
    )
    assert stale.status_code == 409

    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": company["session_token"]},
        json={"token": new_token},
    )
    assert accepted.status_code == 200

    assert client.post(
        f"/cases/{case_id}/invitations/{invitation['id']}/resend",
        headers={"X-Actor-Token": claimant["session_token"]},
    ).status_code == 409

    events = client.get(
        f"/cases/{case_id}/audit",
        headers={"X-Session-Token": claimant["session_token"]},
    ).json()["events"]
    reissues = [item for item in events if item["event_type"] == "invitation_reissued"]
    assert len(reissues) == 1
    assert reissues[0]["payload"]["actor"] == "claimant"


def test_resend_is_limited_to_the_counterparty_invitation(client):
    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    case_id, invitation = open_case_between(client, claimant, "empresa@example.com")

    outsider = register_user(client, "Alguém", "estranho@example.com")
    assert client.post(
        f"/cases/{case_id}/invitations/{invitation['id']}/resend",
        headers={"X-Actor-Token": outsider["session_token"]},
    ).status_code == 403

    assert client.post(
        f"/cases/{case_id}/invitations/nao-existe/resend",
        headers={"X-Actor-Token": claimant["session_token"]},
    ).status_code == 404


def test_counterparty_can_read_the_material_it_must_answer(client):
    """A parte lê o teor do material antes de dar ciência e responder."""
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]

    read = client.get(f"/cases/{case_id}/documents/{document['id']}/content")
    assert read.status_code == 200
    body = read.json()
    assert "A Fornecedora entregará o sistema até 30 de junho." in body["content"]
    assert body["sha256"] == document["sha256"]
    assert body["submitted_by"] == "claimant"
    assert body["purpose"] == document["purpose"]
    assert body["has_original"] is False


def test_material_content_is_restricted_to_the_case(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, app_env="production", auth_required=True),
    )
    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    case_id, _invitation = open_case_between(client, claimant, "empresa@example.com")
    client.post(
        f"/cases/{case_id}/consent",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"party": "claimant", "accepted": True},
    )
    document = client.post(
        f"/cases/{case_id}/documents/text",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={
            "name": "recibo.txt",
            "content": "Comprovante de pagamento da fatura de março.",
            "submitted_by": "claimant",
            "material_type": "evidence",
            "purpose": "Comprovar o pagamento.",
        },
    ).json()["document"]

    outsider = register_user(client, "Alguém", "estranho@example.com")
    denied = client.get(
        f"/cases/{case_id}/documents/{document['id']}/content",
        headers={"X-Session-Token": outsider["session_token"]},
    )
    assert denied.status_code == 403

    anonymous = client.get(f"/cases/{case_id}/documents/{document['id']}/content")
    assert anonymous.status_code == 401
