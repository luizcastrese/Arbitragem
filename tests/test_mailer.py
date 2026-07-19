import os
from unittest.mock import MagicMock, patch

from app.core import mailer
from app.core.config import get_settings


def _reload_settings():
    get_settings.cache_clear()
    return get_settings()


def test_logged_mode_without_smtp(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    _reload_settings()

    result = mailer.send_email("alguem@example.com", "Assunto", "Corpo")

    assert result.status == "logged"
    assert result.provider == "log"
    get_settings.cache_clear()


def test_missing_recipient_fails_gracefully(monkeypatch):
    _reload_settings()
    result = mailer.send_email("", "Assunto", "Corpo")
    assert result.status == "failed"
    get_settings.cache_clear()


def test_smtp_send_uses_starttls(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@valinor.example")
    monkeypatch.setenv("SMTP_STARTTLS", "true")
    monkeypatch.setenv("SMTP_USE_SSL", "false")
    _reload_settings()

    server = MagicMock()
    context = server.__enter__.return_value
    with patch.object(mailer.smtplib, "SMTP", return_value=server) as smtp_cls:
        result = mailer.send_email(
            "destino@example.com",
            "Assunto",
            "Corpo",
            html_body="<p>Corpo</p>",
        )

    assert result.status == "sent"
    smtp_cls.assert_called_once()
    context.starttls.assert_called_once()
    context.login.assert_called_once_with("user", "secret")
    context.send_message.assert_called_once()
    get_settings.cache_clear()


def test_smtp_failure_is_best_effort(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@valinor.example")
    _reload_settings()

    with patch.object(mailer.smtplib, "SMTP", side_effect=OSError("connection refused")):
        result = mailer.send_email("destino@example.com", "Assunto", "Corpo")

    assert result.status == "failed"
    assert result.provider == "smtp"
    get_settings.cache_clear()


def test_build_invitation_email_includes_link():
    email = mailer.build_invitation_email(
        case_title="Disputa X",
        role="claimant",
        acceptance_url="http://host/ui/?invite=abc",
        inviter_name="Gestor",
    )
    assert "Disputa X" in email["subject"]
    assert "http://host/ui/?invite=abc" in email["text"]
    assert "http://host/ui/?invite=abc" in email["html"]
    assert "cliente reclamante" in email["text"]
