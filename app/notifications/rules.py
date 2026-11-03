"""Quais atos do procedimento viram e-mail, para quem e com que texto.

Há um único ponto de entrada, `on_audit_event`, chamado por `append_audit`. A
trilha de auditoria já registra todo ato do procedimento; ligar o aviso a ela
garante que nenhum ato novo deixe de avisar a outra parte por esquecimento, e
que o aviso e o ato entrem na mesma transação.

O e-mail nunca leva o teor do caso: nem texto de peça, nem valores, nem o
resultado da decisão. Ele diz o que aconteceu, o que a pessoa deve fazer, até
quando, e leva ao painel, onde a autenticação protege o conteúdo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditEvent, Case, CaseMember, SettlementPayment, User
from app.notifications.outbox import enqueue

logger = logging.getLogger("valinor.notifications")

PARTIES = ("claimant", "respondent")
ROLE_LABELS = {
    "claimant": "parte reclamante",
    "respondent": "parte reclamada",
    "arbitrator": "árbitro",
    "manager": "gestor do procedimento",
}
ANONYMIZED_DOMAIN = "anonimizado.invalid"


def other_party(party: Optional[str]) -> Optional[str]:
    return {"claimant": "respondent", "respondent": "claimant"}.get(party or "")


@dataclass
class Notice:
    """Um aviso a ser entregue a um ou mais papéis do caso."""

    roles: Iterable[str]
    subject: str
    headline: str
    action: str = ""
    deadline: str = ""
    details: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Destinatários e texto
# ---------------------------------------------------------------------------


def case_link(case_id: str) -> str:
    return f"{get_settings().public_base_url}/ui/?case={case_id}"


def format_deadline(value: Any) -> str:
    """Data legível, em horário de Brasília, a partir de ISO 8601."""
    from datetime import datetime, timedelta, timezone

    if not value:
        return ""
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(timezone(timedelta(hours=-3)))
    return local.strftime("%d/%m/%Y às %H:%M") + " (Brasília)"


def render_body(case: Case, user: User, role: str, notice: Notice) -> str:
    lines = [f"Olá, {user.display_name}.", "", notice.headline]
    for detail in notice.details:
        lines.append(detail)
    if notice.action:
        lines += ["", f"O que fazer: {notice.action}"]
    if notice.deadline:
        lines.append(f"Prazo: {notice.deadline}")
    lines += [
        "",
        f"Abrir o caso: {case_link(case.id)}",
        "",
        "—",
        f"Caso: {case.title}",
        f"Você recebe este aviso porque atua neste procedimento como "
        f"{ROLE_LABELS.get(role, role)}. Os avisos de ato e de prazo não "
        "podem ser desativados: são o que garante que ninguém perca a vez "
        "de se manifestar.",
    ]
    contact = get_settings().privacy_contact
    if contact:
        lines.append(f"Dúvidas: {contact}")
    return "\n".join(lines)


def _recipients(db: Session, case_id: str, roles: Iterable[str]) -> List[tuple]:
    """Pares (papel, usuário) com e-mail utilizável. Conta anonimizada, inativa
    ou sem e-mail confirmado (quando a confirmação é exigida) não recebe: o
    endereço pode não ser da pessoa."""
    settings = get_settings()
    wanted = list(dict.fromkeys(roles))
    if not wanted:
        return []
    rows = (
        db.query(CaseMember.role, User)
        .join(User, User.id == CaseMember.user_id)
        .filter(CaseMember.case_id == case_id, CaseMember.role.in_(wanted))
        .all()
    )
    result = []
    for role, user in rows:
        if not user.active or not user.email:
            continue
        if user.email.endswith("@" + ANONYMIZED_DOMAIN):
            continue
        if settings.email_verification_required and not user.email_verified_at:
            continue
        result.append((role, user))
    return result


def deliver_notice(
    db: Session,
    case: Case,
    notice: Notice,
    *,
    kind: str,
    key: str,
) -> int:
    """Enfileira o aviso para cada destinatário. `key` identifica o fato: o
    mesmo fato nunca gera dois e-mails para a mesma pessoa."""
    queued = 0
    for role, user in _recipients(db, case.id, notice.roles):
        row = enqueue(
            db,
            to_email=user.email,
            kind=kind,
            subject=notice.subject,
            body=render_body(case, user, role, notice),
            case_id=case.id,
            user_id=user.id,
            dedupe_key=f"{key}:{user.id}:{role}",
        )
        if row is not None:
            queued += 1
    return queued


# ---------------------------------------------------------------------------
# Regras por evento
# ---------------------------------------------------------------------------

Rule = Callable[[Session, Case, Dict[str, Any]], List[Notice]]


def _invitation_accepted(db, case, p):
    role = p.get("role")
    if role not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(role)],
            subject="A outra parte entrou no procedimento",
            headline="A outra parte aceitou o convite e agora participa do caso.",
            action="Leia e aceite os termos, se ainda não o fez, e apresente seus documentos.",
        )
    ]


def _consent_accepted(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    if case.claimant_consent and case.respondent_consent:
        return [
            Notice(
                roles=PARTIES,
                subject="Procedimento formado: as duas partes aceitaram os termos",
                headline="As duas partes aceitaram os termos. O procedimento está formado.",
                action=(
                    "Apresente seus documentos e argumentos. Quando terminar, "
                    "declare encerrada a sua apresentação."
                ),
            )
        ]
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte aceitou os termos",
            headline="A outra parte aceitou os termos do procedimento.",
            action="Leia e aceite os termos para o procedimento poder seguir.",
        )
    ]


def _consent_withdrawn(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte retirou o aceite dos termos",
            headline="A outra parte retirou o aceite dos termos. O procedimento não pode avançar até um novo aceite.",
        )
    ]


def _evidence_disclosed(db, case, p):
    target = p.get("disclosed_to")
    if target not in PARTIES:
        return []
    return [
        Notice(
            roles=[target],
            subject="Novo material para sua manifestação",
            headline="A outra parte apresentou um material que precisa da sua manifestação.",
            action=(
                "Leia o material, confirme a ciência e registre sua resposta "
                "(ou renuncie expressamente a responder)."
            ),
        )
    ]


def _response_submitted(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte respondeu ao seu material",
            headline="A outra parte registrou a resposta a um material que você apresentou.",
            action="Leia a resposta. Se não houver mais nada a apresentar, declare encerrada a sua apresentação.",
        )
    ]


def _submission_ready(db, case, p):
    party = p.get("party")
    if party not in PARTIES or not p.get("ready"):
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte encerrou a apresentação",
            headline="A outra parte declarou encerrada a sua apresentação de material.",
            action=(
                "Se você também não tem mais o que apresentar, declare encerrada "
                "a sua apresentação: o conjunto só é travado quando as duas partes o fizerem."
            ),
        )
    ]


def _manifest_locked(db, case, p):
    return [
        Notice(
            roles=PARTIES,
            subject="Material travado: começa a conciliação",
            headline=(
                "O conjunto de documentos foi travado. A partir de agora a "
                "plataforma conduz a conciliação."
            ),
            action="Acompanhe o caso: você será avisado a cada rodada em que precisar se manifestar.",
        )
    ]


def _conciliation_round(db, case, p):
    number = p.get("round_number")
    return [
        Notice(
            roles=PARTIES,
            subject=f"Nova rodada de conciliação disponível (rodada {number})",
            headline="Há uma nova proposta de composição para a sua análise.",
            action="Leia a proposta e registre sua posição: aceitar, recusar ou contrapropor.",
        )
    ]


def _conciliation_position(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte registrou sua posição na conciliação",
            headline="A outra parte registrou a posição dela na rodada de conciliação.",
            action="Se ainda não registrou a sua posição, faça-o para a rodada poder avançar.",
        )
    ]


def _conciliation_response(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte respondeu à proposta de acordo",
            headline="A outra parte respondeu à proposta de acordo da rodada.",
            action="Se ainda não respondeu, acesse o caso e registre a sua resposta.",
        )
    ]


def _conciliation_completed(db, case, p):
    return [
        Notice(
            roles=PARTIES,
            subject="Acordo fechado",
            headline="As duas partes aceitaram a proposta: há acordo no procedimento.",
            action="O auto do acordo será emitido e ficará disponível no caso.",
        )
    ]


def _attestation_issued(db, case, p):
    from app.core.config import get_settings as _settings

    window = format_deadline(p.get("contest_window_ends_utc"))
    reflection = _settings().acceptance_reflection_hours
    return [
        Notice(
            roles=PARTIES,
            subject="Decisão emitida: prazo de recurso em curso",
            headline="A decisão do procedimento foi emitida e assinada.",
            details=[
                "Leia a decisão, o raciocínio e os cálculos no painel.",
                f"Depois de {reflection} horas de reflexão, as duas partes podem "
                "acatar a decisão como acordo. Quem acata não recorre.",
            ],
            action="Leia a decisão e decida se vai recorrer, acatá-la ou seguir pela via judicial.",
            deadline=f"recurso até {window}" if window else "",
        )
    ]


def _decision_record_issued(db, case, p):
    # Com decisão, o aviso é o da attestation (que traz o prazo de recurso);
    # na saída para a Justiça, o aviso é o da própria saída.
    kind = p.get("outcome_kind")
    labels = {
        "agreement": "Auto do acordo emitido",
        "no_merit_decision": "Procedimento encerrado sem decisão de mérito",
    }
    if kind not in labels:
        return []
    return [
        Notice(
            roles=PARTIES,
            subject=labels[kind],
            headline="O auto do procedimento foi emitido e está disponível para download.",
            action="Baixe o auto (Word ou JSON assinado) e guarde uma cópia.",
        )
    ]


def _contest_registered(db, case, p):
    by = p.get("contested_by")
    roles = [other_party(by)] if by in PARTIES else list(PARTIES)
    return [
        Notice(
            roles=roles,
            subject="Recurso apresentado contra a decisão",
            headline="A outra parte apresentou recurso contra a decisão. O recurso é analisado automaticamente.",
            action="Acompanhe o caso: você será avisado quando o resultado do recurso sair.",
        )
    ]


def _appeal_completed(db, case, p):
    return [
        Notice(
            roles=PARTIES,
            subject="Recurso concluído",
            headline="O recurso foi analisado e o resultado está disponível no caso.",
            action="Leia o resultado. Se a decisão foi corrigida, um novo auto é emitido.",
        )
    ]


def _decision_accepted(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte acatou a decisão",
            headline="A outra parte acatou a decisão como acordo.",
            action=(
                "Você pode acatar também, quando o prazo de reflexão terminar "
                "(o ato é irrevogável e afasta o recurso), ou aguardar o fim do prazo de recurso."
            ),
        )
    ]


def _arbitrator_accepted(db, case, p):
    return [
        Notice(
            roles=PARTIES,
            subject="O árbitro indicado aceitou a nomeação",
            headline="O árbitro aceitou a nomeação e apresentou sua declaração de independência.",
            action="Leia a declaração e, se concordar, confirme o árbitro. Sem a confirmação das partes que escolheram a arbitragem, a decisão segue não vinculante.",
        )
    ]


def _arbitrator_confirmed(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte confirmou o árbitro",
            headline="A outra parte confirmou o árbitro nomeado.",
            action="Se ainda não confirmou, leia a declaração do árbitro e registre sua confirmação.",
        )
    ]


def _award_signed(db, case, p):
    return [
        Notice(
            roles=PARTIES,
            subject="Sentença arbitral assinada",
            headline="O árbitro adotou e assinou a decisão como sentença arbitral.",
            action="Baixe o auto reemitido, que passa a ter efeito vinculante.",
        )
    ]


def _award_declined(db, case, p):
    return [
        Notice(
            roles=PARTIES,
            subject="O árbitro recusou assinar a decisão",
            headline="O árbitro não adotou a decisão como sentença arbitral.",
            action="A decisão permanece não vinculante. Acesse o caso para ver os motivos e os caminhos que restam.",
        )
    ]


def _withdrawn(db, case, p):
    party = p.get("party")
    if party not in PARTIES:
        return []
    return [
        Notice(
            roles=[other_party(party)],
            subject="A outra parte optou pela via judicial",
            headline="A outra parte saiu do procedimento e optou pela via judicial. O caso foi encerrado.",
            action="Baixe o auto de encerramento: ele traz todo o histórico e a trilha de auditoria para juntar ao processo.",
        )
    ]


def _deadline_created(db, case, p):
    assigned = p.get("assigned_to")
    roles = list(PARTIES) if assigned == "all" else [assigned]
    roles = [role for role in roles if role in PARTIES or role == "arbitrator"]
    due = format_deadline(p.get("due_at"))
    return [
        Notice(
            roles=roles,
            subject="Novo prazo no procedimento",
            headline="Foi registrado um novo prazo para você no procedimento.",
            deadline=due,
            action="Abra o caso para ver o que precisa ser feito até o vencimento.",
        )
    ]


def _payment_paid(db, case, p):
    payment = db.get(SettlementPayment, p.get("payment_id")) if p.get("payment_id") else None
    if payment is None:
        return []
    return [
        Notice(
            roles=[payment.payee_role],
            subject="Pagamento da decisão recebido",
            headline="A outra parte pagou o valor da decisão pela plataforma.",
            action="Acompanhe o repasse no painel.",
        )
    ]


RULES: Dict[str, Rule] = {
    "invitation_accepted": _invitation_accepted,
    "consent_accepted": _consent_accepted,
    "consent_withdrawn": _consent_withdrawn,
    "evidence_disclosed": _evidence_disclosed,
    "response_submitted": _response_submitted,
    "submission_ready": _submission_ready,
    "manifest_locked": _manifest_locked,
    "conciliation_screened": _conciliation_round,
    "conciliation_round_generated": _conciliation_round,
    "conciliation_position_recorded": _conciliation_position,
    "conciliation_agreement_response": _conciliation_response,
    "conciliation_agreement_completed": _conciliation_completed,
    "attestation_issued": _attestation_issued,
    "decision_record_issued": _decision_record_issued,
    "contest_registered": _contest_registered,
    "appeal_completed": _appeal_completed,
    "decision_accepted": _decision_accepted,
    "arbitrator_accepted": _arbitrator_accepted,
    "arbitrator_confirmed": _arbitrator_confirmed,
    "arbitral_award_signed": _award_signed,
    "arbitral_award_declined": _award_declined,
    "withdrawn_to_court": _withdrawn,
    "deadline_created": _deadline_created,
    "settlement_payment_paid": _payment_paid,
}


# Eventos que a operação precisa saber na hora, não só pelo painel.
OPS_EVENTS = {
    "stage_failed": "Etapa de modelo falhou",
    "contest_attempt_failed": "Recurso automático falhou",
    "decision_verification_failed": "Decisão reprovada na verificação determinística",
    "steward_chain_recovered": "Condução retomada depois de reinício",
}


def _ops_alert(db: Session, case: Case, event: AuditEvent, payload: Dict[str, Any]) -> None:
    recipients = get_settings().ops_recipients
    if not recipients:
        return
    label = OPS_EVENTS[event.event_type]
    detail = payload.get("error") or ", ".join(payload.get("codes") or []) or ""
    base = get_settings().public_base_url
    body = "\n".join(
        [
            f"{label}.",
            "",
            f"Caso: {case.title} ({case.id})",
            f"Situação do caso: {case.status}",
            f"Evento: {event.event_type}",
            *([f"Etapa: {payload['stage']}"] if payload.get("stage") else []),
            *([f"Detalhe: {str(detail)[:300]}"] if detail else []),
            "",
            f"Painel de operação: {base}/ui/admin?case={case.id}",
        ]
    )
    for address in recipients:
        enqueue(
            db,
            to_email=address,
            kind=f"ops_{event.event_type}",
            subject=f"[Valinor] {label} — {case.title}"[:200],
            body=body,
            case_id=case.id,
            audience="ops",
            dedupe_key=f"evt:{event.id}:ops:{address}",
        )


def on_audit_event(
    db: Session,
    case: Case,
    event: AuditEvent,
    payload: Dict[str, Any],
) -> None:
    """Gera os avisos de um evento recém-registrado na trilha.

    Roda dentro da transação do ato. Uma falha aqui nunca pode impedir o ato
    nem quebrar a cadeia de auditoria: o erro é registrado e o ato segue.
    """
    settings = get_settings()
    if not settings.notifications_enabled:
        return
    try:
        if event.event_type in OPS_EVENTS:
            _ops_alert(db, case, event, payload)
            return
        rule = RULES.get(event.event_type)
        if rule is None:
            return
        for index, notice in enumerate(rule(db, case, payload)):
            deliver_notice(
                db,
                case,
                notice,
                kind=event.event_type,
                key=f"evt:{event.id}:{index}",
            )
    except Exception:
        logger.exception(
            "notification_rule_failed case=%s event=%s", case.id, event.event_type
        )
