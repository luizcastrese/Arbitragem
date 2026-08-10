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

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        logger.info(
            "invitation_email transport=smtp to=%s role=%s case=%s",
            to_email,
            role,
            case_title,
        )
        return {"delivered": True, "transport": "smtp"}
    except Exception as exc:  # pragma: no cover - depende de rede/SMTP externo
        logger.warning(
            "invitation_email_failed transport=smtp to=%s error=%s",
            to_email,
            type(exc).__name__,
        )
        return {"delivered": False, "transport": "smtp", "error": type(exc).__name__}
