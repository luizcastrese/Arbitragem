"""Perder a senha não pode significar perder o caso.

A conta é o único caminho de acesso a um procedimento em produção: sem ela não
se lê material, não se cumpre prazo e não se responde. Sem redefinição, um
esquecimento equivale a abandonar a disputa — e o rito, que corre sozinho,
segue precluindo prazos de quem não consegue mais entrar.
"""

from dataclasses import replace

import pytest

from tests.test_api import (  # noqa: F401 - a fixture `client` vem daqui
    client,
    register_user,
)

import app.main as main


@pytest.fixture()
def com_smtp(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            auth_required=True,
            smtp_host="smtp.exemplo.com",
            smtp_from="no-reply@valinor.exemplo.com",
        ),
    )
    return main.settings


def _token_de_redefinicao(email):
    """No lugar de abrir a caixa de entrada: emite pelo mesmo caminho da
    aplicação e lê o valor, já que o banco guarda apenas o hash."""
    from app.db.access_repository import (
        PASSWORD_RESET,
        create_account_token,
        get_user_by_email,
    )

    db = next(main.app.dependency_overrides[main.get_db]())
    try:
        token, _ = create_account_token(
            db, get_user_by_email(db, email), PASSWORD_RESET, duration_hours=1
        )
        return token
    finally:
        db.close()


def _login(client, email, senha):
    return client.post("/auth/login", json={"email": email, "password": senha})


def test_the_password_can_be_reset_and_the_old_one_stops_working(client, com_smtp):
    register_user(client, "Cliente", "cliente@example.com")

    pedido = client.post(
        "/auth/password/forgot", json={"email": "cliente@example.com"}
    )
    assert pedido.status_code == 202

    token = _token_de_redefinicao("cliente@example.com")
    redefinido = client.post(
        "/auth/password/reset",
        json={"token": token, "password": "outra-senha-longa-999"},
    )
    assert redefinido.status_code == 200
    assert redefinido.json()["user"]["email"] == "cliente@example.com"

    assert _login(client, "cliente@example.com", "senha-segura-123").status_code == 401
    assert _login(client, "cliente@example.com", "outra-senha-longa-999").status_code == 200


def test_resetting_drops_every_open_session(client, com_smtp):
    """Quem redefine ou perdeu o acesso, ou suspeita de acesso alheio.

    Nos dois casos, manter sessões antigas de pé preservaria exatamente o
    acesso que a redefinição pretende cortar.
    """
    conta = register_user(client, "Cliente", "cliente@example.com")
    antiga = {"X-Session-Token": conta["session_token"]}
    assert client.get("/auth/me", headers=antiga).status_code == 200

    token = _token_de_redefinicao("cliente@example.com")
    client.post(
        "/auth/password/reset",
        json={"token": token, "password": "outra-senha-longa-999"},
    )

    assert client.get("/auth/me", headers=antiga).status_code == 401


def test_the_reset_link_is_single_use(client, com_smtp):
    register_user(client, "Cliente", "cliente@example.com")
    token = _token_de_redefinicao("cliente@example.com")

    assert client.post(
        "/auth/password/reset",
        json={"token": token, "password": "outra-senha-longa-999"},
    ).status_code == 200
    repetido = client.post(
        "/auth/password/reset",
        json={"token": token, "password": "terceira-senha-longa-1"},
    )
    assert repetido.status_code == 409
    # E a senha continua sendo a da primeira redefinição.
    assert _login(client, "cliente@example.com", "outra-senha-longa-999").status_code == 200


def test_asking_for_an_unknown_account_answers_exactly_the_same(client, com_smtp):
    """A rota não pode virar um oráculo de quem tem conta na plataforma.

    As contas aqui são de partes em disputas: confirmar que um endereço está
    cadastrado já é informação sobre a pessoa.
    """
    register_user(client, "Cliente", "cliente@example.com")

    existente = client.post(
        "/auth/password/forgot", json={"email": "cliente@example.com"}
    )
    inexistente = client.post(
        "/auth/password/forgot", json={"email": "ninguem@example.com"}
    )

    assert existente.status_code == inexistente.status_code == 202
    assert existente.json() == inexistente.json()


def test_resetting_through_the_inbox_also_proves_the_address(client, com_smtp):
    """Chegar ao link é a mesma prova que a confirmação de e-mail pede.

    Pedir a confirmação de novo depois disso seria exigir duas vezes a mesma
    demonstração de posse.
    """
    register_user(client, "Cliente", "cliente@example.com")
    assert client.get(
        "/auth/me",
        headers={"X-Session-Token": _login(
            client, "cliente@example.com", "senha-segura-123"
        ).cookies.get("valinor_session")},
    ).json()["email_verified"] is False

    token = _token_de_redefinicao("cliente@example.com")
    redefinido = client.post(
        "/auth/password/reset",
        json={"token": token, "password": "outra-senha-longa-999"},
    )
    assert redefinido.json()["user"]["email_verified"] is True


def test_a_short_password_is_refused_before_the_token_is_burned(client, com_smtp):
    """Recusar depois de queimar o token deixaria a pessoa sem link e sem senha."""
    register_user(client, "Cliente", "cliente@example.com")
    token = _token_de_redefinicao("cliente@example.com")

    curta = client.post(
        "/auth/password/reset", json={"token": token, "password": "curta"}
    )
    assert curta.status_code == 422

    # O mesmo link continua valendo para uma senha aceitável.
    assert client.post(
        "/auth/password/reset",
        json={"token": token, "password": "outra-senha-longa-999"},
    ).status_code == 200
