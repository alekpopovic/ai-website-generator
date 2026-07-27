"""Password, access-token, and opaque-token security primitives."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from jwt import InvalidTokenError
from pydantic import BaseModel, ConfigDict

from platform_api.config import SecuritySettings
from platform_api.persistence.base import utc_now


class AccessTokenClaims(BaseModel):
    """Strict validated claims accepted from an access token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sub: UUID
    sid: UUID
    jti: UUID
    iss: str
    aud: str
    token_type: str
    iat: int
    exp: int


class PasswordManager:
    """Argon2id password hashing with a reusable enumeration-resistant dummy hash."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65_536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        """Hash a validated password using Argon2id."""
        return self._hasher.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        """Verify without revealing whether an account or password hash exists."""
        candidate = password_hash or self._dummy_hash
        try:
            verified = self._hasher.verify(candidate, password)
        except (InvalidHashError, VerificationError):
            return False
        return bool(verified and password_hash is not None)

    def needs_rehash(self, password_hash: str) -> bool:
        """Return whether current Argon2id policy should replace an old hash."""
        return self._hasher.check_needs_rehash(password_hash)


class AsyncPasswordManager:
    """Keep CPU-bound Argon2id work off the event-loop thread."""

    def __init__(self, manager: PasswordManager | None = None) -> None:
        self._manager = manager or PasswordManager()

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._manager.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        return await asyncio.to_thread(self._manager.verify, password_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._manager.needs_rehash(password_hash)


class AccessTokenManager:
    """Issue and validate short-lived, fixed-algorithm access JWTs."""

    def __init__(self, settings: SecuritySettings) -> None:
        if settings.access_token_secret is None:
            raise ValueError("SECURITY_ACCESS_TOKEN_SECRET is required for authentication")
        self._secret = settings.access_token_secret.get_secret_value()
        self._issuer = settings.access_token_issuer
        self._audience = settings.access_token_audience
        self.ttl_seconds = settings.access_token_ttl_seconds

    def issue(self, *, user_id: UUID, session_id: UUID) -> str:
        """Create a signed token containing only identifiers and standard claims."""
        now = utc_now()
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "sid": str(session_id),
            "jti": str(uuid4()),
            "iss": self._issuer,
            "aud": self._audience,
            "token_type": "access",
            "iat": now,
            "exp": now + timedelta(seconds=self.ttl_seconds),
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def decode(self, token: str) -> AccessTokenClaims:
        """Verify signature, algorithm, issuer, audience, time, and claim shape."""
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "sid", "jti", "iss", "aud", "iat", "exp"]},
            )
            claims = AccessTokenClaims.model_validate(payload)
        except (InvalidTokenError, ValueError) as error:
            raise ValueError("invalid access token") from error
        if claims.token_type != "access":  # noqa: S105 - claim discriminator.
            raise ValueError("invalid access token type")
        return claims


@dataclass(frozen=True, slots=True)
class OpaqueToken:
    """One raw high-entropy token and its one-way database representation."""

    raw: str
    digest: str


def issue_opaque_token() -> OpaqueToken:
    """Create an unguessable token and SHA-256 digest for indexed lookup."""
    raw = secrets.token_urlsafe(48)
    return OpaqueToken(raw=raw, digest=hash_opaque_token(raw))


def hash_opaque_token(raw: str) -> str:
    """Hash a high-entropy token without logging or retaining plaintext."""
    return hashlib.sha256(raw.encode()).hexdigest()
