"""Validated authentication HTTP contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

COMMON_PASSWORDS = frozenset(
    {
        "123456789012",
        "letmein123456",
        "password123!",
        "qwerty123456!",
    }
)


class AuthModel(BaseModel):
    """Strict base for every authentication payload."""

    model_config = ConfigDict(extra="forbid")


def validate_password_strength(value: str) -> str:
    """Enforce a bounded, non-common password with diverse character classes."""
    failures: list[str] = []
    if len(value) < 12:
        failures.append("at least 12 characters")
    if not re.search(r"[a-z]", value):
        failures.append("a lowercase letter")
    if not re.search(r"[A-Z]", value):
        failures.append("an uppercase letter")
    if not re.search(r"[0-9]", value):
        failures.append("a number")
    if not re.search(r"[^A-Za-z0-9]", value):
        failures.append("a symbol")
    if value.lower() in COMMON_PASSWORDS:
        failures.append("a password that is not commonly used")
    if failures:
        raise ValueError("Password must contain " + ", ".join(failures) + ".")
    return value


class RegisterRequest(AuthModel):
    """New user registration payload."""

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=128, repr=False)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Display name must not be blank.")
        return value.strip()

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return validate_password_strength(value)

    @model_validator(mode="after")
    def password_does_not_contain_email_identity(self) -> Self:
        local_part = str(self.email).partition("@")[0].lower()
        if len(local_part) >= 4 and local_part in self.password.lower():
            raise ValueError("Password must not contain the email address.")
        return self


class LoginRequest(AuthModel):
    """Email and password login payload."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128, repr=False)


class PasswordResetRequest(AuthModel):
    """Enumeration-resistant reset email request."""

    email: EmailStr


class ResetPasswordRequest(AuthModel):
    """Single-use reset token and replacement password."""

    token: str = Field(min_length=32, max_length=256, repr=False)
    password: str = Field(min_length=12, max_length=128, repr=False)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return validate_password_strength(value)


class VerifyEmailRequest(AuthModel):
    """Single-use email verification token."""

    token: str = Field(min_length=32, max_length=256, repr=False)


class UserResponse(AuthModel):
    """Safe current-user representation."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    email_verified: bool
    created_at: datetime


class AccessTokenResponse(AuthModel):
    """Short-lived access token plus current-user state."""

    access_token: str = Field(repr=False)
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a credential.
    expires_in: int = Field(gt=0)
    user: UserResponse


class MessageResponse(AuthModel):
    """Non-enumerating acknowledgement."""

    message: str
