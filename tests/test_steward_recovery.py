"""Encadeamento do gestor gravado no banco e retomada depois de um reinício.

O gestor abre uma etapa de modelo e pede para seguir quando ela concluir.
Essa intenção ficava num `set` em memória: um reinício no meio da etapa a
apagava e o caso parava, porque as partes não acionam as etapas de modelo.
Estes testes protegem:

- a tomada da marca é única (UPDATE condicional), mesmo com duas chamadas;
- a varredura retoma um caso cuja marca venceu o TTL, devolve o status
  anterior à etapa abandonada e registra o fato na trilha de auditoria;
- uma reivindicação recente não é tocada: a etapa pode estar rodando em
  outra réplica.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api import steward
from app.db.models import Case
from app.domain.concurrency import PROCESSING_TTL
from app.domain.steward_chain import arm_steward_chain, take_steward_chain
from app.main import stage_runner
from tests.test_api import prepare_locked_case
from tests.test_async_stages import client, poll_until_done, session_factory  # noqa: F401


def _expired() -> datetime:
    return datetime.now(timezone.utc) - PROCESSING_TTL - timedelta(minutes=1)


def _set_case(session_factory, case_id: str, **fields) -> None:  # noqa: F811
    db = session_factory()
    try:
        db.query(Case).filter(Case.id == case_id).update(fields)
        db.commit()
    finally:
        db.close()


def _read_case(session_factory, case_id: str) -> Case:  # noqa: F811
    db = session_factory()
    try:
        return db.query(Case).filter(Case.id == case_id).one()
    finally:
        db.close()


def test_a_marca_so_e_tomada_uma_vez(client, session_factory):  # noqa: F811
    case_id, _document, _ = prepare_locked_case(client)
    db = session_factory()
    try:
        arm_steward_chain(db, case_id)
        assert take_steward_chain(db, case_id) is True
        assert take_steward_chain(db, case_id) is False
    finally:
        db.close()
    assert _read_case(session_factory, case_id).steward_chain_armed_at is None


def test_tomada_restrita_a_marca_observada(client, session_factory):  # noqa: F811
    """A varredura não toma uma marca que o gestor acabou de rearmar."""
    case_id, _document, _ = prepare_locked_case(client)
    old = _expired()
    db = session_factory()
    try:
        arm_steward_chain(db, case_id, now=old)
        arm_steward_chain(db, case_id)  # rearmada depois da leitura
        assert take_steward_chain(db, case_id, armed_at=old) is False
        assert _read_case(session_factory, case_id).steward_chain_armed_at is not None
    finally:
        db.close()


def test_etapa_abandonada_volta_ao_status_anterior_e_o_gestor_segue(
    client, session_factory, monkeypatch  # noqa: F811
):
    case_id, _document, _ = prepare_locked_case(client)
    _set_case(
        session_factory,
        case_id,
        status="processing_decision",
        processing_started_at=_expired(),
        steward_chain_armed_at=_expired(),
    )
    stage_runner.reset()

    conducted = []
    monkeypatch.setattr(
        steward,
        "_conduct_steward",
        lambda db, case, **kwargs: conducted.append((case.id, case.status, kwargs)),
    )

    db = session_factory()
    try:
        resumed = steward.recover_abandoned_steward_chains(db)
    finally:
        db.close()

    assert resumed == [case_id]
    assert conducted == [
        (case_id, "organized", {"wait": 0, "run_model_stages": True})
    ]
    case = _read_case(session_factory, case_id)
    assert case.status == "organized"
    assert case.processing_started_at is None
    assert case.steward_chain_armed_at is None

    audit = client.get(f"/cases/{case_id}/audit").json()
    events = [event for event in audit["events"] if event["event_type"] == "steward_chain_recovered"]
    assert len(events) == 1
    assert events[0]["payload"]["abandoned_status"] == "processing_decision"
    assert events[0]["payload"]["restored_status"] == "organized"


def test_reivindicacao_recente_nao_e_tocada(client, session_factory, monkeypatch):  # noqa: F811
    case_id, _document, _ = prepare_locked_case(client)
    _set_case(
        session_factory,
        case_id,
        status="processing_decision",
        processing_started_at=datetime.now(timezone.utc),
        steward_chain_armed_at=_expired(),
    )
    monkeypatch.setattr(
        steward,
        "_conduct_steward",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deveria conduzir")),
    )

    db = session_factory()
    try:
        assert steward.recover_abandoned_steward_chains(db) == []
    finally:
        db.close()

    case = _read_case(session_factory, case_id)
    assert case.status == "processing_decision"
    assert case.steward_chain_armed_at is not None


def test_marca_recente_nao_e_retomada(client, session_factory):  # noqa: F811
    case_id, _document, _ = prepare_locked_case(client)
    _set_case(session_factory, case_id, steward_chain_armed_at=datetime.now(timezone.utc))
    db = session_factory()
    try:
        assert steward.recover_abandoned_steward_chains(db) == []
    finally:
        db.close()


def test_retomada_de_ponta_a_ponta_roda_a_conciliacao(client, session_factory):  # noqa: F811
    """Caso travado cuja conciliação morreu com o processo: a varredura
    devolve a condução ao gestor, que abre a conciliação de novo."""
    case_id, _document, _ = prepare_locked_case(client)
    assert _read_case(session_factory, case_id).manifest_locked
    # O preparo pausa as etapas de modelo: a conciliação nunca começou.
    pending = client.get(f"/cases/{case_id}/stage/conciliation").json()
    assert pending["state"] == "pending"
    _set_case(session_factory, case_id, steward_chain_armed_at=_expired())
    stage_runner.reset()

    loop = steward.StewardRecoveryLoop(interval=0, session_factory=session_factory)
    assert loop.run_once() == [case_id]

    body = poll_until_done(client, case_id, "conciliation")
    assert body["state"] == "completed"
