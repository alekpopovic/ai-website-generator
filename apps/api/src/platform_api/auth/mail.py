"""First-party authentication email delivery boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from platform_api.config import EmailSettings


@dataclass(frozen=True, slots=True)
class AuthenticationEmail:
    """A bounded plain-text authentication email."""

    recipient: str
    subject: str
    body: str = field(repr=False)


class AuthenticationMailer(Protocol):
    """Delivery interface implemented by SMTP and deterministic tests."""

    async def send(self, message: AuthenticationEmail) -> None: ...


class SmtpAuthenticationMailer:
    """Deliver authentication messages through configured SMTP, including Mailpit locally."""

    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    async def send(self, message: AuthenticationEmail) -> None:
        email = EmailMessage()
        email["From"] = self._settings.from_address
        email["To"] = message.recipient
        email["Subject"] = message.subject
        email.set_content(message.body)
        await aiosmtplib.send(
            email,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_username,
            password=(
                self._settings.smtp_password.get_secret_value()
                if self._settings.smtp_password is not None
                else None
            ),
            start_tls=self._settings.smtp_start_tls,
            use_tls=self._settings.smtp_use_tls,
            timeout=self._settings.smtp_timeout_seconds,
        )


class InMemoryAuthenticationMailer:
    """Non-networked fake mail delivery for CI and unit tests."""

    def __init__(self) -> None:
        self.messages: list[AuthenticationEmail] = []

    async def send(self, message: AuthenticationEmail) -> None:
        self.messages.append(message)
