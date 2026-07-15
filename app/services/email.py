from email.message import EmailMessage
import smtplib

from app.core.config import get_settings


def send_email(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTP não configurado")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            client.starttls()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError("Falha ao enviar e-mail transacional") from exc


def send_verification_email(recipient: str, token: str) -> None:
    settings = get_settings()
    link = f"{settings.public_base_url}/ui/?verify={token}"
    send_email(
        recipient,
        "Confirme seu e-mail na Valinor",
        f"Confirme seu endereço para ativar a conta:\n\n{link}\n\nO link expira em 30 minutos.",
    )


def send_password_reset_email(recipient: str, token: str) -> None:
    settings = get_settings()
    link = f"{settings.public_base_url}/ui/?reset={token}"
    send_email(
        recipient,
        "Redefinição de senha da Valinor",
        f"Use o link abaixo para redefinir sua senha:\n\n{link}\n\nO link expira em 30 minutos.",
    )


def send_invitation_email(recipient: str, token: str, case_title: str, role: str) -> None:
    settings = get_settings()
    link = f"{settings.public_base_url}/ui/?invite={token}"
    send_email(
        recipient,
        f"Convite para o procedimento Valinor: {case_title}",
        (
            f"Você foi convidado para participar como {role} no caso {case_title}.\n\n"
            f"Acesse o link protegido:\n{link}\n\nO convite expira em 7 dias."
        ),
    )
