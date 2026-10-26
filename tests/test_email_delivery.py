from unittest.mock import MagicMock, patch

import pytest

from xibalba_cortex.email_delivery import EmailDeliveryError, send_email


def test_send_email_requires_delivery_configuration(monkeypatch):
    monkeypatch.delenv("CORTEX_SMTP_HOST", raising=False)
    monkeypatch.delenv("CORTEX_SMTP_FROM", raising=False)
    with pytest.raises(EmailDeliveryError, match="required"):
        send_email("operator@example.com", "Reset", "body")


def test_send_email_uses_starttls_and_optional_authentication(monkeypatch):
    monkeypatch.setenv("CORTEX_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("CORTEX_SMTP_PORT", "2525")
    monkeypatch.setenv("CORTEX_SMTP_FROM", "security@example.com")
    monkeypatch.setenv("CORTEX_SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("CORTEX_SMTP_PASSWORD", "smtp-password")
    client = MagicMock()
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value = client
    with patch("xibalba_cortex.email_delivery.smtplib.SMTP", smtp):
        send_email("operator@example.com", "Reset", "body")
    smtp.assert_called_once_with("smtp.example.com", 2525, timeout=15)
    client.starttls.assert_called_once()
    client.login.assert_called_once_with("smtp-user", "smtp-password")
    client.send_message.assert_called_once()


def test_send_email_uses_resend(monkeypatch):
    monkeypatch.setenv("CORTEX_EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("CORTEX_EMAIL_FROM", "security@example.com")
    response = MagicMock()
    with patch("xibalba_cortex.email_delivery.requests.post", return_value=response) as post:
        send_email("operator@example.com", "Verify", "body")
    post.assert_called_once_with(
        "https://api.resend.com/emails",
        headers={"Authorization": "Bearer re_test_key", "Content-Type": "application/json"},
        json={"from": "security@example.com", "to": ["operator@example.com"], "subject": "Verify", "text": "body"},
        timeout=15,
    )
    response.raise_for_status.assert_called_once_with()
