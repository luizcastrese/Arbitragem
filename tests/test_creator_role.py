"""O criador escolhe a parte em que atua; o advogado é só um registro (OAB)."""

import pytest

from app.domain.pathway import PathwayError, build_pathway, normalize_bar_number
from tests.test_api import (  # noqa: F401 - a fixture `client` vem daqui
    client,
    register_user,
)


def _open(client, user, **extra):
    return client.post(
        "/cases",
        headers={"X-Session-Token": user["session_token"]},
        json={
            "title": "Revisional de empréstimo",
            "claimant": "Maria da Silva",
            "respondent": "Banco Exemplo S.A.",
            **extra,
        },
    )


def test_default_creator_is_the_claimant(client):
    user = register_user(client, "Maria", "maria@example.com")
    created = _open(client, user)
    assert created.status_code == 201
    roles = [item["role"] for item in created.json()["participants"]]
    assert roles == ["claimant"]
    assert created.json()["pathway"]["creator_role"] == "claimant"


def test_creator_can_act_for_the_respondent(client):
    user = register_user(client, "Banco", "banco@example.com")
    created = _open(client, user, creator_role="respondent")
    assert created.status_code == 201
    body = created.json()
    assert [item["role"] for item in body["participants"]] == ["respondent"]
    assert body["pathway"]["creator_role"] == "respondent"
    # Quem entra na reclamada pode convidar a reclamante (papel oposto).
    invite = client.post(
        f"/cases/{body['id']}/invitations",
        headers={"X-Actor-Token": user["session_token"]},
        json={"email": "maria@example.com", "role": "claimant"},
    )
    assert invite.status_code == 201


def test_unknown_creator_role_is_rejected(client):
    user = register_user(client, "Maria", "maria@example.com")
    assert _open(client, user, creator_role="arbitrator").status_code == 422
    assert _open(client, user, creator_role="manager").status_code == 422


def test_counsel_is_a_record_not_a_new_role(client):
    user = register_user(client, "Dra. Ana", "ana@example.com")
    created = _open(
        client, user, creator_role="claimant", acting_as_counsel=True,
        counsel_bar_number="oab/sp 123.456",
    )
    assert created.status_code == 201
    body = created.json()
    assert [item["role"] for item in body["participants"]] == ["claimant"]
    assert body["pathway"]["counsel"] == {"claimant": {"bar_number": "OAB/SP 123456"}}


def test_counsel_requires_a_valid_bar_number(client):
    user = register_user(client, "Dra. Ana", "ana@example.com")
    assert _open(client, user, acting_as_counsel=True).status_code == 422
    assert _open(
        client, user, acting_as_counsel=True, counsel_bar_number="sem número"
    ).status_code == 422
    # Sem a indicação de advogado, a OAB enviada é ignorada.
    plain = _open(client, user, counsel_bar_number="OAB/SP 123456")
    assert plain.status_code == 201
    assert plain.json()["pathway"]["counsel"] == {}


@pytest.mark.parametrize(
    "raw,expected",
    [("OAB/SP 123456", "OAB/SP 123456"), ("sp 123.456", "OAB/SP 123456"), ("RJ12345", "OAB/RJ 12345")],
)
def test_bar_number_normalization(raw, expected):
    assert normalize_bar_number(raw) == expected


def test_bar_number_rejects_garbage():
    with pytest.raises(PathwayError):
        normalize_bar_number("123")
    with pytest.raises(PathwayError):
        build_pathway(
            entry_point="pre_litigation",
            matter_framework_id="consumer_banking_v1",
            consumer_relation=True,
            creator_role="lawyer",
        )
