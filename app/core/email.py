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
    "manager": "gestor do procedimento",
}


def build_accept_url(base_url: str, token: str) -> str:
    return f"{base_url}/ui/?invite={token}"


def build_verification_url(base_url: str, token: str) -> str:
    return f"{base_url}/ui/?verify={token}"


def build_password_reset_url(base_url: str, token: str) -> str:
    return f"{base_url}/ui/?reset={token}"


def _deliver(message: EmailMessage, *, kind: str, to_email: str) -> Dict[str, object]:
    """Envia a mensagem ou apenas registra no log quando não há SMTP.

    Nunca levanta exceção: uma falha de entrega não pode derrubar a operação
    que originou o e-mail, cujo token continua válido para reenvio.
    """
    settings = get_settings()
    if not settings.email_enabled:
        logger.info("%s transport=log to=%s", kind, to_email)
        return {"delivered": False, "transport": "log"}

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


def build_verification_message(
    *,
    to_email: str,
    display_name: str,
    verification_url: str,
    sender: str,
    ttl_hours: int,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Confirme seu e-mail na Valinor"
    message["From"] = sender
    message["To"] = to_email
    message.set_content(
        f"Olá, {display_name}.\n\n"
        "Sua conta na Valinor foi criada. Para praticar atos em um "
        "procedimento — aceitar os termos, apresentar documentos ou "
        "responder à contraparte — é preciso confirmar que este endereço de "
        "e-mail é seu.\n\n"
        f"{verification_url}\n\n"
        f"O link é de uso único e expira em {ttl_hours} horas.\n\n"
        "Se você não criou esta conta, ignore esta mensagem."
    )
    return message


def build_password_reset_message(
    *,
    to_email: str,
    display_name: str,
    reset_url: str,
    sender: str,
    ttl_minutes: int,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Redefinição de senha na Valinor"
    message["From"] = sender
    message["To"] = to_email
    message.set_content(
        f"Olá, {display_name}.\n\n"
        "Recebemos um pedido de redefinição de senha para esta conta. "
        "Use o link abaixo para escolher uma nova senha:\n\n"
        f"{reset_url}\n\n"
        f"O link é de uso único e expira em {ttl_minutes} minutos. Ao "
        "concluir a redefinição, todas as sessões abertas são encerradas.\n\n"
        "Se você não pediu a redefinição, ignore esta mensagem: sua senha "
        "atual continua valendo."
    )
    return message


def deliver_verification_email(
    *,
    to_email: str,
    display_name: str,
    token: str,
) -> Dict[str, object]:
    settings = get_settings()
    message = build_verification_message(
        to_email=to_email,
        display_name=display_name,
        verification_url=build_verification_url(settings.public_base_url, token),
        sender=settings.smtp_from,
        ttl_hours=settings.email_verification_ttl_hours,
    )
    return _deliver(message, kind="verification_email", to_email=to_email)


def deliver_password_reset_email(
    *,
    to_email: str,
    display_name: str,
    token: str,
) -> Dict[str, object]:
    settings = get_settings()
    message = build_password_reset_message(
        to_email=to_email,
        display_name=display_name,
        reset_url=build_password_reset_url(settings.public_base_url, token),
        sender=settings.smtp_from,
        ttl_minutes=settings.password_reset_ttl_minutes,
    )
    return _deliver(message, kind="password_reset_email", to_email=to_email)


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
    message = build_invitation_message(
        to_email=to_email,
        role=role,
        case_title=case_title,
        accept_url=build_accept_url(settings.public_base_url, token),
        sender=settings.smtp_from,
    )
    return _deliver(message, kind="invitation_email", to_email=to_email)
