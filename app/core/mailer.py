"""Entrega de e-mail transacional (convites e notificações).

O envio é sempre *best-effort*: uma falha de SMTP nunca deve derrubar o fluxo
da API. Sem SMTP configurado, o sistema entra em modo `logged` — a mensagem é
registrada no log em vez de enviada, espelhando a filosofia de fallback seguro
do resto da plataforma. Assim o produto continua operável em desenvolvimento e
o gestor ainda consegue recuperar o link do convite pelo próprio endpoint.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Dict, Optional

from app.core.config import get_settings


logger = logging.getLogger("valinor.mailer")


@dataclass(frozen=True)
class EmailResult:
    status: str  # "sent" | "logged" | "failed"
    provider: str  # "smtp" | "log" | "none"
    detail: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"status": self.status, "provider": self.provider, "detail": self.detail}


def email_enabled() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.email_from)


def _login_and_send(server: smtplib.SMTP, settings, message: EmailMessage) -> None:
    if settings.smtp_user:
        server.login(settings.smtp_user, settings.smtp_password)
    server.send_message(message)


def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> EmailResult:
    """Envia um e-mail e devolve o resultado sem nunca lançar exceção."""

    recipient = (to or "").strip()
    if not recipient:
        return EmailResult("failed", "none", "destinatário ausente")

    settings = get_settings()

    if not email_enabled():
        logger.info(
            "[EMAIL:logged] para=%s assunto=%s\n%s",
            recipient,
            subject,
            text_body,
        )
        return EmailResult(
            "logged",
            "log",
            "SMTP não configurado; mensagem registrada no log",
        )

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        if settings.smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout,
                context=context,
            ) as server:
                _login_and_send(server, settings, message)
        else:
            with smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout,
            ) as server:
                if settings.smtp_starttls:
                    server.starttls(context=ssl.create_default_context())
                _login_and_send(server, settings, message)
    except Exception as exc:  # noqa: BLE001 - entrega é best-effort
        logger.warning(
            "[EMAIL:failed] para=%s assunto=%s erro=%s",
            recipient,
            subject,
            type(exc).__name__,
        )
        return EmailResult("failed", "smtp", type(exc).__name__)

    logger.info("[EMAIL:sent] para=%s assunto=%s", recipient, subject)
    return EmailResult("sent", "smtp", "")


def build_invitation_email(
    *,
    case_title: str,
    role: str,
    acceptance_url: str,
    inviter_name: Optional[str] = None,
) -> Dict[str, str]:
    """Monta assunto e corpos (texto e HTML) do e-mail de convite."""

    role_label = {
        "claimant": "cliente reclamante",
        "respondent": "empresa reclamada",
        "manager": "gestor do procedimento",
    }.get(role, role)

    origin = f" por {inviter_name}" if inviter_name else ""
    subject = f"[Valinor] Convite para o caso: {case_title}"

    text_body = (
        f"Você foi convidado{origin} para atuar como {role_label} no "
        f"procedimento \"{case_title}\" na Valinor.\n\n"
        "A participação é voluntária. Você terá acesso a todo o material do "
        "caso e oportunidade de se manifestar antes de qualquer decisão.\n\n"
        f"Para aceitar o convite, entre ou crie sua conta com este mesmo "
        f"e-mail e acesse:\n{acceptance_url}\n\n"
        "Este convite é de uso único e expira em 7 dias.\n"
    )

    html_body = (
        "<div style=\"font-family:system-ui,Arial,sans-serif;line-height:1.5;"
        "color:#1a1a1a\">"
        f"<p>Você foi convidado{origin} para atuar como <strong>{role_label}"
        f"</strong> no procedimento <strong>{case_title}</strong> na Valinor.</p>"
        "<p>A participação é voluntária. Você terá acesso a todo o material do "
        "caso e oportunidade de se manifestar antes de qualquer decisão.</p>"
        "<p>Para aceitar, entre ou crie sua conta com este mesmo e-mail e "
        f"acesse:</p><p><a href=\"{acceptance_url}\" style=\"display:inline-block;"
        "padding:10px 18px;background:#1a1a1a;color:#fff;text-decoration:none;"
        "border-radius:8px\">Aceitar convite</a></p>"
        f"<p style=\"color:#666;font-size:13px\">Ou copie este endereço: "
        f"{acceptance_url}</p>"
        "<p style=\"color:#666;font-size:13px\">Este convite é de uso único e "
        "expira em 7 dias.</p></div>"
    )

    return {"subject": subject, "text": text_body, "html": html_body}
