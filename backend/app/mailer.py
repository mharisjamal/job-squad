"""Delivery of signup verification codes: Resend HTTP API, else SMTP.

Blocking by design (smtplib and a sync httpx call); callers must run
send_otp_email off the event loop via anyio.to_thread.run_sync. The code
itself is never logged.
"""

import smtplib
from email.message import EmailMessage

import httpx

from .config import Settings

SMTP_TIMEOUT_SECONDS = 15
RESEND_TIMEOUT_SECONDS = 15
RESEND_ENDPOINT = "https://api.resend.com/emails"
OTP_TTL_MINUTES = 10
SUBJECT = "Your JobSquad verification code"


class MailError(RuntimeError):
    """Raised when the verification email could not be delivered."""


def _body_text(code: str, display_name: str) -> str:
    greeting = f"Hi {display_name}," if display_name else "Hi,"
    return (
        f"{greeting}\n\n"
        f"Your JobSquad verification code is: {code}\n\n"
        f"Enter it on the signup screen to finish creating your account. "
        f"The code expires in {OTP_TTL_MINUTES} minutes.\n\n"
        "If you did not sign up for JobSquad, you can ignore this email "
        "and no account will be created.\n"
    )


def _sender(settings: Settings) -> str:
    return (
        settings.mail_from
        or settings.smtp_from
        or settings.smtp_user
        or "jobsquad@localhost"
    )


def send_otp_email(settings: Settings, to_email: str, code: str, display_name: str) -> None:
    if settings.resend_api_key:
        _send_via_resend(settings, to_email, code, display_name)
        return
    _send_via_smtp(settings, to_email, code, display_name)


def _send_via_resend(
    settings: Settings, to_email: str, code: str, display_name: str
) -> None:
    payload = {
        "from": _sender(settings),
        "to": [to_email],
        "subject": SUBJECT,
        "text": _body_text(code, display_name),
    }
    try:
        response = httpx.post(
            RESEND_ENDPOINT,
            json=payload,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            timeout=RESEND_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise MailError(f"Resend request failed: {exc}") from exc
    if response.status_code >= 300:
        # Body goes to the caller's log only, never to the API response.
        raise MailError(
            f"Resend returned {response.status_code}: {response.text[:500]}"
        )


def _build_message(settings: Settings, to_email: str, code: str, display_name: str):
    message = EmailMessage()
    message["Subject"] = SUBJECT
    message["From"] = _sender(settings)
    message["To"] = to_email
    message.set_content(_body_text(code, display_name))
    return message


def _send_via_smtp(
    settings: Settings, to_email: str, code: str, display_name: str
) -> None:
    if not settings.smtp_host:
        raise MailError("No mail transport is configured")
    message = _build_message(settings, to_email, code, display_name)
    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        ) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
                smtp.ehlo()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        # The exception text may name the server or recipient, never the code.
        raise MailError(str(exc)) from exc
