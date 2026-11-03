"""O texto público da política é lido por titulares, não por desenvolvedores.

A política é servida com os valores da configuração no lugar dos marcadores. Estes
testes reprovam a versão vigente se ela voltar a mostrar nome de variável de
ambiente, rota de API, marcador sem preencher ou jargão que os Termos já evitam.
"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from app.core import privacy
from app.core.config import DEFAULT_PRIVACY_CONTACT_EMAIL, get_settings
from app.core.hashing import sha256_text
from app.core.terms import current_terms, list_versions as terms_versions
from app.core.versioned_docs import normalize
from tests.test_api import client  # noqa: F401

# DATA_CONTROLLER_NAME, PRIVACY_CONTACT_EMAIL, DOCUMENT_RETENTION_DAYS...
ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
API_ROUTE = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE) /")

CONFIGURED = replace(
    get_settings(),
    data_controller_name="Alugaí Tecnologia Ltda.",
    privacy_contact_email="privacidade@alugai.example",
    document_retention_days=180,
)
UNCONFIGURED = replace(
    get_settings(), data_controller_name="", privacy_contact_email="", document_retention_days=0
)


@pytest.mark.parametrize("settings", [CONFIGURED, UNCONFIGURED], ids=["configurada", "sem-configuracao"])
def test_rendered_policy_has_no_variable_names_routes_or_open_markers(settings):
    text = privacy.current_policy(settings).text
    assert ENV_NAME.findall(text) == []
    assert API_ROUTE.findall(text) == []
    assert "{{" not in text and "}}" not in text


def test_policy_uses_plain_language():
    text = privacy.current_policy(CONFIGURED).text
    lowered = text.lower()
    # Sem jargão do código e sem marcas de provedor: o texto diz o que o provedor é.
    for forbidden in ("attestation", "openai", "openrouter", "residual_identifiers", "valinor_session", "/account/"):
        assert forbidden not in lowered, forbidden
    assert "provedor de modelo de ia contratado pela plataforma" in lowered
    # A pendência jurídica é lembrete interno (README), não texto público.
    assert "pendência" not in lowered
    assert "validação jurídica" not in lowered
    # Os dois pontos que o titular não descobriria sozinho continuam presentes.
    assert "transferência internacional" in lowered
    assert "nostr" in lowered


def test_policy_explains_how_to_ask_for_access_copy_and_deletion():
    text = privacy.current_policy(CONFIGURED).text
    assert "Baixar meus dados" in text
    assert "Anonimizar conta" in text
    assert "por e-mail" in text.lower()
    assert "privacidade@alugai.example" in text


def test_configured_values_are_rendered():
    text = privacy.current_policy(CONFIGURED).text
    assert "Alugaí Tecnologia Ltda." in text
    assert "[privacidade@alugai.example](mailto:privacidade@alugai.example)" in text
    assert "180 dias depois do encerramento do caso" in text


def test_controller_name_ending_in_a_period_does_not_double_it():
    text = privacy.current_policy(CONFIGURED).text  # "Alugaí Tecnologia Ltda."
    assert "é Alugaí Tecnologia Ltda." in text
    assert ".." not in text


def test_missing_values_become_neutral_text_not_variable_names():
    text = privacy.current_policy(UNCONFIGURED).text
    assert privacy.NEUTRAL_CONTROLLER in text
    assert privacy.NEUTRAL_RETENTION in text
    # Sem PRIVACY_CONTACT_EMAIL vale o contato padrão do site.
    assert DEFAULT_PRIVACY_CONTACT_EMAIL == "alugai.adm@gmail.com"
    assert f"[{DEFAULT_PRIVACY_CONTACT_EMAIL}](mailto:{DEFAULT_PRIVACY_CONTACT_EMAIL})" in text


def test_retention_of_one_day_is_singular():
    text = privacy.current_policy(replace(CONFIGURED, document_retention_days=1)).text
    assert "1 dia depois do encerramento do caso" in text


def test_hash_is_of_the_rendered_text_and_changes_with_the_values():
    a = privacy.current_policy(CONFIGURED)
    assert a.sha256 == sha256_text(a.text)
    assert privacy.current_policy(CONFIGURED).sha256 == a.sha256  # estável
    assert privacy.current_policy(UNCONFIGURED).sha256 != a.sha256
    assert privacy.current_policy(replace(CONFIGURED, document_retention_days=90)).sha256 != a.sha256


def test_current_version_is_the_new_one_and_the_old_one_is_untouched():
    assert privacy.current_version() == "2026-11-03"
    old = privacy.get_policy("2026-09-12", CONFIGURED)
    raw = (Path(privacy.PRIVACY_DIR) / "2026-09-12.md").read_text(encoding="utf-8")
    # Versão publicada não se edita: o hash é o do arquivo original.
    assert old.sha256 == sha256_text(normalize(raw))


def test_endpoint_serves_the_rendered_text_with_its_hash(client, monkeypatch):
    from app.api.routes import meta

    monkeypatch.setattr(meta, "get_settings", lambda: CONFIGURED)
    body = client.get("/privacy").json()
    assert body["version"] == "2026-11-03"
    assert "Alugaí Tecnologia Ltda." in body["text"]
    assert "{{" not in body["text"]
    assert body["sha256"] == sha256_text(body["text"])
    assert body["controller"]["contact_email"] == "privacidade@alugai.example"
    by_version = client.get("/privacy/2026-11-03").json()
    assert by_version["text"] == body["text"] and by_version["current"] is True


def test_endpoint_defaults_the_contact_when_not_configured(client, monkeypatch):
    from app.api.routes import meta

    monkeypatch.setattr(meta, "get_settings", lambda: UNCONFIGURED)
    body = client.get("/privacy").json()
    assert body["controller"]["contact_email"] == DEFAULT_PRIVACY_CONTACT_EMAIL
    assert body["controller"]["name"] is None
    assert body["controller"]["declared"] is False
    assert privacy.NEUTRAL_CONTROLLER in body["text"]


def test_terms_name_the_privacy_contact_directly():
    terms = current_terms()
    assert terms.version == "2026-11-03"
    assert "alugai.adm@gmail.com" in terms.text
    assert "canais indicados na política de privacidade" not in terms.text
    # A versão anterior continua como foi aceita pelos casos que a usam.
    assert "2026-11-02" in terms_versions()


def test_only_the_controller_is_required_in_production(monkeypatch):
    """O contato tem padrão; o controlador, não: sem ele a política fica sem nome."""
    assert replace(get_settings(), data_controller_name="X").privacy_contacts_declared is True
    assert replace(get_settings(), data_controller_name="").privacy_contacts_declared is False
