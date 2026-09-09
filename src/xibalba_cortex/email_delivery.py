import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")

def send_email(to_email: str, subject: str, body: str) -> None:
    if not resend.api_key:
        print(f"WARN: RESEND_API_KEY not set. Would have sent email to {to_email} with subject '{subject}'")
        return

    try:
        resend.Emails.send({
            "from": "noreply@xibalba.local", # Replace with verified domain in production
            "to": to_email,
            "subject": subject,
            "text": body
        })
    except Exception as e:
        print(f"WARN: Failed to send email via Resend: {e}")
