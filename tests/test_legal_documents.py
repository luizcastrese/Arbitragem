"""Os documentos legais precisam existir, ser legíveis e amarrar o aceite.

Antes havia só uma frase-resumo na interface e uma versão fixa no código — que
vinha no corpo da requisição de aceite. A cadeia de auditoria registrava,
portanto, a versão que o cliente dissesse ter aceitado.
"""

from tests.test_api import (  # noqa: F401 - a fixture `client` vem daqui
    accept_procedure,
    actor_headers,
    client,
    create_case,
)

from app.core.legal import TERMS_VERSION


def test_the_documents_are_served_and_declare_themselves_a_draft(client):
    indice = client.get("/legal")
    assert indice.status_code == 200
    corpo = indice.json()
    assert corpo["version"] == TERMS_VERSION
    assert {item["kind"] for item in corpo["documents"]} == {"terms", "privacy"}

    for item in corpo["documents"]:
        documento = client.get(item["url"])
        assert documento.status_code == 200
        conteudo = documento.json()
        assert conteudo["version"] == TERMS_VERSION
        assert len(conteudo["content"]) > 2000
        # Enquanto forem minutas, a API tem de dizer isso — a interface não
        # pode apresentar como vinculante um texto que ainda não é.
        assert conteudo["draft"] is True

    assert client.get("/legal/inexistente").status_code == 404


def test_the_documents_describe_what_the_system_actually_does(client):
    """Documento legal que descreve outro sistema é pior que nenhum."""
    termos = client.get("/legal/terms").json()["content"]
    privacidade = client.get("/legal/privacy").json()["content"]

    # O que o rito de fato faz, e que uma minuta genérica não diria.
    assert "preclus" in termos.lower()
    assert "não significa concordância" in termos
    assert "Silêncio não vale como aceite" in termos
    assert "ocupar os dois polos" in termos

    # O que o sistema de fato faz com os dados, incluindo o desconfortável.
    assert "AES-256-GCM" in privacidade
    assert "inteligência artificial" in privacidade.lower()
    assert "irrevers" in privacidade.lower()  # hashes públicos não voltam
    assert "apaga nada automaticamente" in privacidade


def test_the_accepted_version_comes_from_the_server_not_from_the_client(client):
    """O registro tem de dizer o que a plataforma apresentou.

    Se a versão viesse do corpo da requisição, a cadeia de auditoria guardaria
    a afirmação do cliente sobre o que ele aceitou — que é justamente o que um
    registro auditável não pode fazer.
    """
    case_id = create_case(client)["id"]

    aceite = client.post(
        f"/cases/{case_id}/consent",
        json={
            "party": "claimant",
            "accepted": True,
            # Um cliente malicioso alegando ter aceitado outra coisa.
            "terms_version": "versao-inventada-pelo-cliente",
        },
        headers=actor_headers(case_id, "claimant"),
    )
    assert aceite.status_code == 200

    eventos = [
        item
        for item in client.get(f"/cases/{case_id}/audit").json()["events"]
        if item["event_type"] == "consent_accepted"
    ]
    assert len(eventos) == 1
    assert eventos[0]["payload"]["terms_version"] == TERMS_VERSION
    assert "inventada" not in str(eventos[0])
