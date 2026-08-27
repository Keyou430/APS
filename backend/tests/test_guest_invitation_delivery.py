from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from app.config import Settings
from app.services.guest_invitation_delivery import deliver_invitation


class FakeSmtp:
    def __init__(self) -> None:
        self.login_args: tuple[str, str] | None = None
        self.message: EmailMessage | None = None

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.message = message


@pytest.mark.asyncio
async def test_smtp_delivery_uses_ssl_and_fragment_link_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp = FakeSmtp()
    factory_calls: list[tuple[str, int, float]] = []

    def smtp_factory(host: str, port: int, *, timeout: float, context: object) -> FakeSmtp:
        assert context is not None
        factory_calls.append((host, port, timeout))
        return smtp

    monkeypatch.setattr("app.services.guest_invitation_delivery.smtplib.SMTP_SSL", smtp_factory)
    settings = Settings(
        guest_invitation_delivery_adapter="smtp",
        guest_invitation_public_base_url="https://platform.example",
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_username="sender@example.com",
        smtp_password="smtp-authorization-code",
        guest_invitation_recipient_allowlist="recipient@example.com",
    )

    await deliver_invitation(
        settings=settings,
        recipient="recipient@example.com",
        token="one-time-token",
        token_expires_at=datetime(2026, 8, 5, tzinfo=UTC),
    )

    assert factory_calls == [("smtp.qq.com", 465, 10.0)]
    assert smtp.login_args == ("sender@example.com", "smtp-authorization-code")
    assert smtp.message is not None
    assert smtp.message["To"] == "recipient@example.com"
    assert "one-time-token" not in str(smtp.message["Subject"])
    assert (
        "https://platform.example/invitations/accept#token=one-time-token"
        in smtp.message.get_content()
    )
