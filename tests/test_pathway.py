"""Via do caso, escolha pela arbitragem e efeito jurídico do resultado.

A Valinor atua antes do processo e em processo já ajuizado. Sem acordo, só há
arbitragem quando as duas partes a escolhem dentro do caso, depois do
conflito; em consumo, a escolha do consumidor é indispensável.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.domain.frameworks import get_framework, framework_kind
from app.domain.pathway import (
    ARBITRATION,
    NON_BINDING,
    PathwayError,
    build_pathway,
    legal_effect,
    normalize_lawsuit_number,
    record_election,
    resolution_track,
)
from app.reports.decision_record import build_decision_record
from app.reports.decision_record_docx import build_decision_record_docx
from tests.test_api import (  # noqa: F401  (fixture)
    CASE_CREDENTIALS,
    actor_headers,
    client,
    prepare_locked_case,
)
from tests.test_decision_record import _decided_case_data

LAWSUIT = "0001234-71.2024.8.26.0100"
TERMS = ("2026-10-31", "f" * 64)


def _pathway(entry="pre_litigation", consumer=True, **kwargs):
    if entry == "pending_lawsuit":
        kwargs.setdefault("lawsuit_number", LAWSUIT)
        kwargs.setdefault("court", "1ª Vara Cível de São Paulo")
    return build_pathway(
        entry_point=entry,
        matter_framework_id="consumer_banking_v1",
        consumer_relation=consumer,
        **kwargs,
    )


def _designate(pathway):
    from app.domain.arbitration import record_acceptance, record_confirmation

    pathway = record_acceptance(
        pathway, user_id="u-arb", display_name="Ana Árbitra", tax_id="52998224725",
        qualification="Advogada", disclosure="",
    )
    for party in ("claimant", "respondent"):
        pathway = record_confirmation(pathway, party=party, terms_version="2026-11-02")
    return pathway


def _elect(pathway, *parties):
    for party in parties:
        pathway = record_election(
            pathway, party=party, elected=True, terms_version=TERMS[0], terms_sha256=TERMS[1]
        )
    return pathway


# ---------------------------------------------------------------- domínio


def test_banking_is_a_consumer_matter_and_old_hashes_are_untouched():
    banking = get_framework("consumer_banking_v1")
    assert framework_kind(banking.id) == "matter"
    assert banking.consumer_relation is True
    assert banking.as_dict()["consumer_relation"] is True
    # Matéria antiga não ganha a chave: o hash travado nos manifestos não muda.
    assert "consumer_relation" not in get_framework("digital_services_b2b_v1").as_dict()


def test_lawsuit_number_follows_cnj_check_digit():
    assert normalize_lawsuit_number("00012347120248260100") == LAWSUIT
    with pytest.raises(PathwayError):
        normalize_lawsuit_number("0001234-72.2024.8.26.0100")
    with pytest.raises(PathwayError):
        normalize_lawsuit_number("123")


def test_pending_lawsuit_requires_number_and_court():
    with pytest.raises(PathwayError):
        build_pathway(
            entry_point="pending_lawsuit",
            matter_framework_id="consumer_banking_v1",
            consumer_relation=True,
            lawsuit_number=LAWSUIT,
        )
    with pytest.raises(PathwayError):
        _pathway(entry="pre_litigation", lawsuit_number=LAWSUIT)


def test_arbitration_needs_both_parties():
    pathway = _pathway()
    assert resolution_track(pathway) == NON_BINDING
    assert resolution_track(_elect(pathway, "respondent")) == NON_BINDING
    both = _elect(pathway, "claimant", "respondent")
    assert resolution_track(both) == ARBITRATION
    assert both["arbitration_elections"]["claimant"]["by_consumer"] is True
    assert both["arbitration_elections"]["claimant"]["after_dispute_arose"] is True


def test_election_under_old_terms_is_refused():
    with pytest.raises(PathwayError):
        record_election(
            _pathway(), party="claimant", elected=True,
            terms_version="2026-10-11", terms_sha256="a" * 64,
        )


def test_agreement_in_pending_lawsuit_goes_to_homologation():
    effect = legal_effect(_pathway(entry="pending_lawsuit"), "agreement")
    assert effect["instrument"] == "termo_de_acordo_para_homologacao"
    assert effect["ends_lawsuit_by"] == "homologacao_de_acordo"
    assert effect["binding"] is True
    assert any("487, III" in item for item in effect["legal_basis"])
    assert LAWSUIT in effect["next_steps"][0]


def test_arbitral_decision_waits_for_the_human_arbitrator_signature():
    effect = legal_effect(
        _designate(_elect(_pathway(entry="pending_lawsuit"), "claimant", "respondent")),
        "decision",
    )
    assert effect["instrument"] == "sentenca_arbitral"
    assert effect["ends_lawsuit_by"] == "sentenca_arbitral"
    assert effect["binding"] is False
    assert effect["pending"]
    assert any("485, VII" in item for item in effect["legal_basis"])
    assert any("51, VII" in item for item in effect["legal_basis"])


def test_without_both_elections_the_decision_does_not_bind():
    effect = legal_effect(_elect(_pathway(), "respondent"), "decision")
    assert effect["instrument"] == "decisao_nao_vinculante"
    assert effect["binding"] is False


def test_abstention_returns_the_conflict_to_court():
    effect = legal_effect(_pathway(entry="pending_lawsuit"), "no_merit_decision")
    assert effect["instrument"] == "auto_sem_merito"
    assert any("313, II" in step for step in effect["next_steps"])


def test_record_carries_legal_effect_and_matching_notice():
    case_data = _decided_case_data()
    case_data["pathway"] = _designate(
        _elect(_pathway(entry="pending_lawsuit"), "claimant", "respondent")
    )
    record = build_decision_record(case_data, audit_chain_head="e" * 64, audit_chain_length=3)
    assert record["legal_effect"]["instrument"] == "sentenca_arbitral"
    assert record["outcome"]["binding"] is False
    assert "arts. 13 e 26" in record["legal_notice"]
    with zipfile.ZipFile(io.BytesIO(build_decision_record_docx(record).getvalue())) as docx:
        xml = docx.read("word/document.xml").decode("utf-8")
    assert "Efeito jurídico e próximos passos" in xml
    assert LAWSUIT in xml


# ---------------------------------------------------------------- API


def _create(client, **extra):
    response = client.post(
        "/cases",
        json={
            "title": "Desconto de consignado não reconhecido",
            "claimant": "Maria Consumidora",
            "respondent": "Banco Exemplo S.A.",
            **extra,
        },
    )
    return response


def _consent(client, case_id, party, **extra):
    return client.post(
        f"/cases/{case_id}/consent",
        json={"party": party, "accepted": True, **extra},
        headers=actor_headers(case_id, party),
    )


def test_api_opens_pending_lawsuit_case_and_tracks_elections(client):
    response = _create(
        client,
        entry_point="pending_lawsuit",
        lawsuit_number="00012347120248260100",
        court="1ª Vara Cível de São Paulo",
    )
    assert response.status_code == 201, response.text
    case = response.json()
    CASE_CREDENTIALS[case["id"]] = case.pop("access_credentials")
    assert case["pathway"]["lawsuit"]["number"] == LAWSUIT
    assert case["pathway"]["consumer_party"] == "claimant"
    assert case["pathway"]["resolution_track"] == NON_BINDING

    assert _consent(client, case["id"], "claimant", elects_arbitration=True).status_code == 200
    assert _consent(client, case["id"], "respondent", elects_arbitration=True).status_code == 200
    pathway = client.get(f"/cases/{case['id']}").json()["pathway"]
    assert pathway["resolution_track"] == ARBITRATION

    withdrawn = client.post(
        f"/cases/{case['id']}/consent",
        json={"party": "claimant", "accepted": False},
        headers=actor_headers(case["id"], "claimant"),
    )
    assert withdrawn.status_code == 200
    pathway = client.get(f"/cases/{case['id']}").json()["pathway"]
    assert pathway["resolution_track"] == NON_BINDING


def test_api_rejects_invalid_pathway(client):
    assert _create(client, entry_point="pending_lawsuit", lawsuit_number=LAWSUIT).status_code == 422
    assert _create(client, matter_framework_id="commercial_balanced_v1").status_code == 422
    assert _create(client, matter_framework_id="digital_services_b2b_v1", consumer_party="claimant").status_code == 422


def test_api_refuses_election_under_old_terms(client):
    case = _create(client).json()
    CASE_CREDENTIALS[case["id"]] = case.pop("access_credentials")
    refused = _consent(client, case["id"], "claimant", elects_arbitration=True, terms_version="2026-10-11")
    assert refused.status_code == 422


def test_manifest_freezes_the_pathway(client):
    _, _, locked = prepare_locked_case(client)
    manifest = locked.json()["manifest"]
    assert manifest["pathway"]["entry_point"] == "pre_litigation"
    assert manifest["pathway"]["resolution_track"] == NON_BINDING
