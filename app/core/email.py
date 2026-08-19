"""Entrega de e-mail transacional para convites.

Quando o SMTP não está configurado, o sistema não falha: registra o convite
no log e devolve `transport="log"`. Isso mantém o fluxo local operável e, em
produção, basta configurar as variáveis SMTP_* para ativar o envio real.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Dict

from app.core.config import get_settings


logger = logging.getLogger("valinor.email")


ROLE_LABELS = {
    "claimant": "parte reclamante",
    "respondent": "empresa reclamada",
}


def build_accept_url(base_url: str, token: str) -> str:
    return f"{base_url}/ui/?invite={token}"


def build_verification_url(base_url: str, token: str) -> str:
    return f"{base_url}/ui/?verify={token}"


def build_password_reset_url(base_url: str, token: str) -> str:
    return f"{base_url}/ui/?reset={token}"


def build_invitation_message(
    *,
    to_email: str,
    role: str,
    case_title: str,
    accept_url: str,
    sender: str,
) -> EmailMessage:
    role_label = ROLE_LABELS.get(role, role)
    message = EmailMessage()
    message["Subject"] = f"Convite para o procedimento: {case_title}"
    message["From"] = sender
    message["To"] = to_email
    message.set_content(
        "Você foi convidado a participar de um procedimento de resolução de "
        "disputa na plataforma Valinor.\n\n"
        f"Caso: {case_title}\n"
        f"Papel: {role_label}\n\n"
        "Para aceitar o convite, entre ou crie sua conta com este mesmo "
        "e-mail e acesse o link abaixo:\n"
        f"{accept_url}\n\n"
        "O convite é de uso único, vinculado a este endereço, e expira em 7 "
        "dias.\n\n"
        "Se você não reconhece este convite, ignore esta mensagem."
    )
    return message


def build_deadline_message(
    *,
    to_email: str,
    case_title: str,
    label: str,
    due_at: str,
    sender: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"Prazo aberto no procedimento: {case_title}"
    message["From"] = sender
    message["To"] = to_email
    message.set_content(
        "Um prazo foi aberto para você em um procedimento na plataforma "
        "Valinor.\n\n"
        f"Caso: {case_title}\n"
        f"Ato esperado: {label}\n"
        f"Vencimento: {due_at}\n\n"
        "Se o prazo vencer sem manifestação, a oportunidade é encerrada por "
        "preclusão e o procedimento segue sem ela. Isso não presume "
        "concordância com o material da outra parte: apenas encerra a chance "
        "de responder.\n\n"
        "Acesse a plataforma para se manifestar."
    )
    return message


def _send(message: EmailMessage, *, kind: str, to_email: str) -> Dict[str, object]:
    settings = get_settings()
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        logger.info("%s transport=smtp to=%s", kind, to_email)
        return {"delivered": True, "transport": "smtp"}
    except Exception as exc:  # pragma: no cover - depende de rede/SMTP externo
        logger.warning(
            "%s_failed transport=smtp to=%s error=%s",
            kind,
            to_email,
            type(exc).__name__,
        )
        return {"delivered": False, "transport": "smtp", "error": type(exc).__name__}


def deliver_deadline_email(
    *,
    to_email: str,
    case_title: str,
    label: str,
    due_at: str,
) -> Dict[str, object]:
    """Avisa a parte do prazo aberto. Nunca levanta exceção: uma falha de
    entrega não pode derrubar o andamento do procedimento.

    O resultado da entrega vai para a cadeia de auditoria, porque a preclusão
    só se sustenta se a oportunidade tiver sido efetivamente comunicada.
    """
    settings = get_settings()
    if not settings.email_enabled:
        logger.info(
            "deadline_email transport=log to=%s case=%s label=%s due=%s",
            to_email,
            case_title,
            label,
            due_at,
        )
        return {"delivered": False, "transport": "log"}

    message = build_deadline_message(
        to_email=to_email,
        case_title=case_title,
        label=label,
        due_at=due_at,
        sender=settings.smtp_from,
    )
    return _send(message, kind="deadline_email", to_email=to_email)


def deliver_invitation_email(
    *,
    to_email: str,
    role: str,
    case_title: str,
    token: str,
) -> Dict[str, object]:
    """Envia (ou registra) o convite. Nunca levanta exceção: uma falha de
    entrega não deve derrubar a criação do convite, cujo token permanece
    válido para reenvio."""
    settings = get_settings()
    accept_url = build_accept_url(settings.public_base_url, token)

    if not settings.email_enabled:
        logger.info(
            "invitation_email transport=log to=%s role=%s case=%s",
            to_email,
            role,
            case_title,
        )
        return {"delivered": False, "transport": "log"}

    message = build_invitation_message(
        to_email=to_email,
        role=role,
        case_title=case_title,
        accept_url=accept_url,
        sender=settings.smtp_from,
    )
    return _send(message, kind="invitation_email", to_email=to_email)


def build_account_message(
    *,
    to_email: str,
    subject: str,
    body: str,
    sender: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_email
    message.set_content(body)
    return message


def deliver_verification_email(*, to_email: str, token: str) -> Dict[str, object]:
    """Envia o link de confirmação do endereço. Nunca levanta exceção."""
    settings = get_settings()
    url = build_verification_url(settings.public_base_url, token)
    body = (
        "Confirme seu endereço de e-mail para poder atuar em um procedimento "
        "na plataforma Valinor.\n\n"
        f"{url}\n\n"
        "A confirmação é o que garante à outra parte que quem entrou no caso "
        "controla de fato este endereço. O link vale por 24 horas.\n\n"
        "Se não foi você que criou esta conta, ignore esta mensagem."
    )
    if not settings.email_enabled:
        # Sem SMTP não há como provar posse de endereço nenhum. O log serve
        # para diagnóstico; nunca leva o token, que daria acesso à conta a
        # quem tiver acesso aos logs.
        logger.info("verification_email transport=log to=%s", to_email)
        return {"delivered": False, "transport": "log"}
    return _send(
        build_account_message(
            to_email=to_email,
            subject="Confirme seu e-mail — Valinor",
            body=body,
            sender=settings.smtp_from,
        ),
        kind="verification_email",
        to_email=to_email,
    )


def deliver_password_reset_email(*, to_email: str, token: str) -> Dict[str, object]:
    """Envia o link de redefinição de senha. Nunca levanta exceção."""
    settings = get_settings()
    url = build_password_reset_url(settings.public_base_url, token)
    body = (
        "Recebemos um pedido para redefinir a senha da sua conta na plataforma "
        "Valinor.\n\n"
        f"{url}\n\n"
        "O link vale por 1 hora e só pode ser usado uma vez. Ao redefinir, "
        "todas as sessões abertas na sua conta são encerradas.\n\n"
        "Se não foi você que pediu, ignore esta mensagem: sua senha continua a "
        "mesma."
    )
    if not settings.email_enabled:
        logger.info("password_reset_email transport=log to=%s", to_email)
        return {"delivered": False, "transport": "log"}
    return _send(
        build_account_message(
            to_email=to_email,
            subject="Redefinição de senha — Valinor",
            body=body,
            sender=settings.smtp_from,
        ),
        kind="password_reset_email",
        to_email=to_email,
    )
