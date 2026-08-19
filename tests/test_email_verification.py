"""Sem prova de posse do endereço, o convite não vincula ninguém.

O convite é endereçado a um e-mail e só é aceito por uma conta com aquele
e-mail. Isso parece amarrar quem entra no caso — mas só amarra se registrar uma
conta exigir provar que se controla o endereço. Sem verificação, qualquer
pessoa se cadastra com o e-mail alheio e ocupa o polo destinado a ele.
"""

from dataclasses import replace

import pytest

from tests.test_api import (  # noqa: F401 - a fixture `client` vem daqui
    CASE_CREDENTIALS,
    client,
    register_user,
)

import app.main as main
from app.core.config import get_settings


@pytest.fixture()
def verificacao_exigida(monkeypatch):
    """Deploy com SMTP configurado, onde a confirmação passa a ser exigida."""
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            require_email_verification=True,
            auth_required=True,
            smtp_host="smtp.exemplo.com",
            smtp_from="no-reply@valinor.exemplo.com",
        ),
    )
    return main.settings


def _abrir_caso(client, token):
    return client.post(
        "/cases",
        headers={"X-Session-Token": token},
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente",
            "respondent": "Empresa",
            "creator_role": "claimant",
        },
    )


def test_an_unverified_account_cannot_become_a_party(client, verificacao_exigida):
    conta = register_user(client, "Cliente", "cliente@example.com")

    recusado = _abrir_caso(client, conta["session_token"])
    assert recusado.status_code == 403
    assert "Confirme seu e-mail" in recusado.json()["detail"]

    # A conta existe e está autenticada — o que falta é a prova de posse.
    eu = client.get("/auth/me", headers={"X-Session-Token": conta["session_token"]})
    assert eu.status_code == 200
    assert eu.json()["email_verified"] is False


def test_verifying_the_address_unlocks_acting_in_a_case(client, verificacao_exigida):
    conta = register_user(client, "Cliente", "cliente@example.com")

    # O token não volta na resposta: quem prova posse é quem lê a caixa de
    # entrada. Aqui ele é lido do banco, no lugar do e-mail.
    token = _token_pendente(client, "cliente@example.com")

    confirmado = client.post("/auth/verify-email", json={"token": token})
    assert confirmado.status_code == 200
    assert confirmado.json()["user"]["email_verified"] is True

    criado = _abrir_caso(client, conta["session_token"])
    assert criado.status_code == 201


def test_the_token_is_single_use_and_never_leaves_by_another_channel(
    client, verificacao_exigida
):
    registro = client.post(
        "/auth/register",
        json={
            "display_name": "Cliente",
            "email": "cliente@example.com",
            "password": "senha-segura-123",
        },
    )
    assert registro.status_code == 201
    corpo = registro.json()
    # A resposta diz que a confirmação foi pedida, e o resultado da entrega,
    # mas em nenhuma hipótese o token.
    assert corpo["email_verification"]["required"] is True
    assert corpo["email_verification"]["verified"] is False
    assert "token" not in str(corpo)

    token = _token_pendente(client, "cliente@example.com")
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    # Reutilizar o mesmo link não confirma nada de novo.
    repetido = client.post("/auth/verify-email", json={"token": token})
    assert repetido.status_code == 409


def test_reissuing_the_link_invalidates_the_previous_one(client, verificacao_exigida):
    conta = register_user(client, "Cliente", "cliente@example.com")
    primeiro = _token_pendente(client, "cliente@example.com")

    reenvio = client.post(
        "/auth/verify-email/request",
        headers={"X-Session-Token": conta["session_token"]},
    )
    assert reenvio.status_code == 200
    segundo = _token_pendente(client, "cliente@example.com")
    assert segundo != primeiro

    # Dois links válidos ao mesmo tempo só ampliariam a superfície de ataque.
    assert client.post("/auth/verify-email", json={"token": primeiro}).status_code == 409
    assert client.post("/auth/verify-email", json={"token": segundo}).status_code == 200


def test_an_impostor_cannot_take_the_seat_addressed_to_someone_else(
    client, verificacao_exigida
):
    """O ataque que a verificação fecha.

    O convite vai para o e-mail da empresa. Um terceiro registra uma conta com
    esse mesmo endereço — coisa que ninguém o impede de digitar — e tenta
    ocupar o polo dela. Sem confirmação, entraria.
    """
    cliente = register_user(client, "Cliente", "cliente@example.com")
    _verificar(client, "cliente@example.com")

    caso = _abrir_caso(client, cliente["session_token"])
    assert caso.status_code == 201
    case_id = caso.json()["id"]

    convite = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": cliente["session_token"]},
        json={"email": "empresa@example.com", "role": "respondent"},
    )
    assert convite.status_code == 201
    link = convite.json()["acceptance_url"].split("invite=")[1]

    # O impostor cadastra o endereço da empresa sem ter acesso a ele.
    impostor = register_user(client, "Impostor", "empresa@example.com")
    barrado = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": impostor["session_token"]},
        json={"token": link},
    )
    assert barrado.status_code == 403

    # Quem controla a caixa de entrada confirma e entra — a mesma conta, agora
    # com a posse provada.
    _verificar(client, "empresa@example.com")
    aceito = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": impostor["session_token"]},
        json={"token": link},
    )
    assert aceito.status_code == 200


def test_without_smtp_the_requirement_is_off_and_the_flow_still_runs(client):
    """Sem canal de entrega, exigir confirmação trancaria todo mundo de fora.

    A suíte roda sem SMTP, que é também o caso de um deploy local: a exigência
    fica desligada e o cadastro continua utilizável.
    """
    assert get_settings().require_email_verification is False
    conta = register_user(client, "Cliente", "cliente@example.com")
    assert _abrir_caso(client, conta["session_token"]).status_code == 201


# --- leitura do token direto do banco, no lugar da caixa de entrada ---------


def _token_pendente(client, email):
    """Recupera o token em claro é impossível: o banco guarda só o hash.

    Para o teste, emite-se um token novo pela mesma função da aplicação e
    lê-se o valor devolvido — equivalente a abrir o e-mail que acabou de sair.
    """
    from app.db.access_repository import EMAIL_VERIFICATION, create_account_token
    from app.db.models import User

    db = next(main.app.dependency_overrides[main.get_db]())
    try:
        user = db.query(User).filter(User.email == email).one()
        token, _ = create_account_token(db, user, EMAIL_VERIFICATION)
        return token
    finally:
        db.close()


def _verificar(client, email):
    token = _token_pendente(client, email)
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
