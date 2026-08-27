from __future__ import annotations

import asyncio
from datetime import datetime
from email.message import EmailMessage
import smtplib
import ssl
from urllib.parse import quote

from app.config import Settings


class InvitationDeliveryError(RuntimeError):
    pass


def invitation_accept_url(settings: Settings, token: str) -> str:
    assert settings.guest_invitation_public_base_url is not None
    base_url = settings.guest_invitation_public_base_url.rstrip("/")
    return f"{base_url}/invitations/accept#token={quote(token, safe='')}"


def invitation_message(
    *,
    settings: Settings,
    recipient: str,
    token: str,
    token_expires_at: datetime,
) -> EmailMessage:
    assert settings.smtp_username is not None
    message = EmailMessage()
    message["From"] = settings.smtp_from_email or settings.smtp_username
    message["To"] = recipient
    message["Subject"] = "Hermes Platform guest invitation"
    message.set_content(
        "You have been invited to access shared knowledge in Hermes Platform.\n\n"
        f"Accept the invitation: {invitation_accept_url(settings, token)}\n\n"
        f"This one-time invitation expires at {token_expires_at.isoformat()}.\n"
        "If you did not expect this invitation, ignore this email.\n"
    )
    return message


def _send_smtp_message(settings: Settings, message: EmailMessage) -> None:
    assert settings.smtp_host is not None
    assert settings.smtp_username is not None
    assert settings.smtp_password is not None
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout_seconds,
        context=context,
    ) as smtp:
        smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


async def deliver_invitation(
    *,
    settings: Settings,
    recipient: str,
    token: str,
    token_expires_at: datetime,
) -> None:
    if settings.guest_invitation_delivery_adapter != "smtp":
        return
    message = invitation_message(
        settings=settings,
        recipient=recipient,
        token=token,
        token_expires_at=token_expires_at,
    )
    try:
        await asyncio.to_thread(_send_smtp_message, settings, message)
    except (OSError, TimeoutError, smtplib.SMTPException) as exc:
        raise InvitationDeliveryError("SMTP invitation delivery failed") from exc
