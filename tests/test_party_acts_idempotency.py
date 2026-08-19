"""Os atos das partes são únicos, e repeti-los não reescreve o procedimento.

O rito já era idempotente: `advance` pode ser chamado à vontade sem repetir
nada. Os atos das partes não eram — reenviar consentimento, ciência ou resposta
gravava evento novo a cada vez, e a segunda resposta ainda reescrevia uma
manifestação sobre material que já tinha sido admitido por causa dela.

O caso da resposta é o mais grave, e não por incoerência de registro: quem
reescreve a própria manifestação contorna o contraditório, porque a contraparte
não é notificada nem ganha prazo sobre o teor novo.
"""

from tests.test_api import (  # noqa: F401 - a fixture `client` vem daqui
    accept_procedure,
    actor_headers,
    add_contract,
    client,
    create_case,
)


def _events_of(client, case_id, event_type):
    audit = client.get(f"/cases/{case_id}/audit").json()
    assert audit["valid"] is True
    return [item for item in audit["events"] if item["event_type"] == event_type]


def _prepared(client):
    """Caso com consentimento das duas partes e um documento do reclamante."""
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]
    return case_id, document["id"]


def test_repeating_consent_does_not_grow_the_audit_chain(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    assert len(_events_of(client, case_id, "consent_accepted")) == 2

    for _ in range(3):
        again = client.post(
            f"/cases/{case_id}/consent",
            json={"party": "claimant", "accepted": True},
            headers=actor_headers(case_id, "claimant"),
        )
        assert again.status_code == 200
        assert again.json()["claimant"]["accepted"] is True

    # Reafirmar o mesmo aceite é o mesmo aceite.
    assert len(_events_of(client, case_id, "consent_accepted")) == 2

    # Mas retirar o consentimento continua sendo um ato, e volta a registrar.
    withdrawn = client.post(
        f"/cases/{case_id}/consent",
        json={"party": "claimant", "accepted": False},
        headers=actor_headers(case_id, "claimant"),
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["claimant"]["accepted"] is False
    assert len(_events_of(client, case_id, "consent_withdrawn")) == 1


def test_repeating_the_acknowledgement_keeps_a_single_record(client):
    case_id, document_id = _prepared(client)

    for _ in range(3):
        response = client.post(
            f"/cases/{case_id}/documents/{document_id}/acknowledge",
            json={"party": "respondent"},
            headers=actor_headers(case_id, "respondent"),
        )
        assert response.status_code == 200

    events = _events_of(client, case_id, "notice_acknowledged")
    assert len(events) == 1
    # E a data da ciência é a da primeira, não a da última tentativa.
    documento = client.get(f"/cases/{case_id}").json()["documents"][0]
    assert documento["acknowledged_at"] == events[0]["payload"].get(
        "acknowledged_at", documento["acknowledged_at"]
    )


def test_a_response_cannot_be_rewritten_after_it_is_given(client):
    """O ponto central: reescrever a resposta contornaria o contraditório."""
    case_id, document_id = _prepared(client)
    client.post(
        f"/cases/{case_id}/documents/{document_id}/acknowledge",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "respondent"),
    )
    primeira = client.post(
        f"/cases/{case_id}/documents/{document_id}/respond",
        json={
            "party": "respondent",
            "response_status": "answered",
            "response_text": "Houve entrega parcial, documentada em anexo.",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    assert primeira.status_code == 200

    # O material foi admitido como consequência dessa manifestação.
    documento = client.get(f"/cases/{case_id}").json()["documents"][0]
    assert documento["admitted"] is True
    admitido_em = documento["admitted_at"]

    # Mudar de posição depois disso é recusado.
    mudanca = client.post(
        f"/cases/{case_id}/documents/{document_id}/respond",
        json={
            "party": "respondent",
            "response_status": "challenged",
            "response_text": "Repensei: contesto integralmente.",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    assert mudanca.status_code == 409
    assert "apresente material novo" in mudanca.json()["detail"]

    # O registro segue coerente: a resposta e a admissão continuam as mesmas.
    documento = client.get(f"/cases/{case_id}").json()["documents"][0]
    assert documento["response_status"] == "answered"
    assert documento["admitted_at"] == admitido_em
    assert len(_events_of(client, case_id, "response_submitted")) == 1


def test_resending_the_identical_response_is_a_harmless_retry(client):
    """Rede instável não pode virar erro na cara da parte."""
    case_id, document_id = _prepared(client)
    client.post(
        f"/cases/{case_id}/documents/{document_id}/acknowledge",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "respondent"),
    )
    corpo = {
        "party": "respondent",
        "response_status": "answered",
        "response_text": "Houve entrega parcial, documentada em anexo.",
    }
    for _ in range(3):
        response = client.post(
            f"/cases/{case_id}/documents/{document_id}/respond",
            json=corpo,
            headers=actor_headers(case_id, "respondent"),
        )
        assert response.status_code == 200

    assert len(_events_of(client, case_id, "response_submitted")) == 1


def test_the_party_can_still_bring_a_new_position_through_new_material(client):
    """A recusa não emudece ninguém: há um canal que preserva o contraditório.

    Material novo é disponibilizado, abre prazo para a contraparte e volta ao
    rito normal — que é exatamente o que a reescrita silenciosa pulava.
    """
    case_id, document_id = _prepared(client)
    client.post(
        f"/cases/{case_id}/documents/{document_id}/acknowledge",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "respondent"),
    )
    client.post(
        f"/cases/{case_id}/documents/{document_id}/respond",
        json={
            "party": "respondent",
            "response_status": "answered",
            "response_text": "Houve entrega parcial.",
        },
        headers=actor_headers(case_id, "respondent"),
    )

    novo = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "retificacao.txt",
            "content": "Complemento: a entrega foi integral, conforme aceite anexo.",
            "submitted_by": "respondent",
            "material_type": "argument",
            "purpose": "Corrigir e complementar a manifestação anterior.",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    assert novo.status_code == 201
    novo_id = novo.json()["document"]["id"]

    # A contraparte é notificada e ganha prazo — o que a reescrita não fazia.
    deadlines = client.get(f"/cases/{case_id}/deadlines").json()
    aberto = [
        item
        for item in deadlines
        if item["reference_id"] == novo_id and item["status"] == "open"
    ]
    assert len(aberto) == 1
    assert aberto[0]["assigned_to"] == "claimant"

    pendencias = client.get(f"/cases/{case_id}/procedure").json()["pending"]
    assert any(
        item["party"] == "claimant" and item["reference_id"] == novo_id
        for item in pendencias
    )
