"""Fail-closed transactional email delivery for account recovery messages."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

import requests


class EmailDeliveryError(RuntimeError):
    """Raised when email delivery is not configured or does not complete."""


def send_email(to_email: str, subject: str, body: str) -> None:
    provider = os.environ.get("CORTEX_EMAIL_PROVIDER", "").strip().lower()
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("CORTEX_EMAIL_FROM", os.environ.get("CORTEX_SMTP_FROM", "")).strip()
    if provider == "resend" or resend_key:
        if not resend_key or not sender:
            raise EmailDeliveryError("RESEND_API_KEY and CORTEX_EMAIL_FROM are required")
        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json={"from": sender, "to": [to_email], "subject": subject, "text": body},
                timeout=15,
            )
            response.raise_for_status()
        except (requests.RequestException, ValueError) as exc:
            raise EmailDeliveryError("Resend delivery failed") from exc
        return

    host = os.environ.get("CORTEX_SMTP_HOST", "").strip()
    sender = os.environ.get("CORTEX_SMTP_FROM", "").strip()
    if not host or not sender:
        raise EmailDeliveryError("CORTEX_SMTP_HOST and CORTEX_SMTP_FROM are required")

    try:
        port = int(os.environ.get("CORTEX_SMTP_PORT", "587"))
    except ValueError as exc:
        raise EmailDeliveryError("CORTEX_SMTP_PORT must be an integer") from exc

    username = os.environ.get("CORTEX_SMTP_USERNAME", "").strip()
    password = os.environ.get("CORTEX_SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise EmailDeliveryError("CORTEX_SMTP_USERNAME and CORTEX_SMTP_PASSWORD must be configured together")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=15) as client:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
            if username:
                client.login(username, password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("SMTP delivery failed") from exc
