"""Security-focused tests for first-party authentication."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi import FastAPI, Response
from platform_api.api.v1.auth import clear_refresh_cookie, set_refresh_cookie
from platform_api.auth.dependencies import authentication_service_dependency
from platform_api.auth.rate_limit import InMemoryLoginRateLimiter
from platform_api.auth.schemas import (
    AccessTokenResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from platform_api.auth.security import AccessTokenManager, PasswordManager, hash_opaque_token
from platform_api.auth.service import (
    AuthenticatedSession,
    AuthenticationService,
    PasswordManagerContract,
)
from platform_api.config import EmailSettings, SecuritySettings
from platform_api.dependencies import database_transaction_dependency
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.base import utc_now
from platform_api.persistence.models import AuditLog, AuthActionToken, RefreshToken, User
from platform_api.resources import ApplicationResources
from pydantic import SecretStr, ValidationError

TEST_SIGNING_KEY = "unit-test-access-token-secret-value-32-bytes"  # pragma: allowlist secret
CREDENTIAL_FIXTURE = "Correct-Horse-7-Battery!"  # pragma: allowlist secret
NEW_CREDENTIAL_FIXTURE = "New-Correct-Horse-8!"  # pragma: allowlist secret
SECOND_CREDENTIAL_FIXTURE = "Another-Correct-Horse-9!"  # pragma: allowlist secret
ACCESS_TOKEN_FIXTURE = "access-token-fixture"  # noqa: S105  # pragma: allowlist secret
REFRESH_TOKEN_FIXTURE = "raw-refresh-token-fixture"  # noqa: S105  # pragma: allowlist secret


class FakeAuthenticationRepository:
    """In-memory transactional repository fake retaining token state transitions."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.actions: dict[str, AuthActionToken] = {}

    def add(self, entity: User | RefreshToken | AuthActionToken) -> None:
        entity.id = uuid4()
        if isinstance(entity, User):
            entity.created_at = utc_now()
            self.users[entity.id] = entity
        elif isinstance(entity, RefreshToken):
            self.refresh_tokens[entity.token_hash] = entity
        else:
            self.actions[entity.token_hash] = entity

    async def flush(self) -> None:
        return None

    async def user_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def user_by_id(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def refresh_for_update(self, token_hash: str) -> RefreshToken | None:
        return self.refresh_tokens.get(token_hash)

    async def action_for_update(self, *, token_hash: str, purpose: str) -> AuthActionToken | None:
        action = self.actions.get(token_hash)
        return action if action is not None and action.purpose == purpose else None

    async def revoke_family(self, family_id: UUID) -> None:
        for token in self.refresh_tokens.values():
            if token.family_id == family_id and token.status == "active":
                token.status = "revoked"
                token.revoked_at = utc_now()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        for token in self.refresh_tokens.values():
            if token.user_id == user_id and token.status == "active":
                token.status = "revoked"
                token.revoked_at = utc_now()

    async def consume_pending_actions(self, *, user_id: UUID, purpose: str) -> None:
        for action in self.actions.values():
            if (
                action.user_id == user_id
                and action.purpose == purpose
                and action.consumed_at is None
            ):
                action.consumed_at = utc_now()


class FakeAuditRepository:
    """Collect audit records without a database commit."""

    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


class FastPasswordManager:
    """Deterministic service fake; Argon2id itself is tested separately."""

    async def hash(self, password: str) -> str:
        return f"fixture:{password}"

    async def verify(self, password_hash: str | None, password: str) -> bool:
        return password_hash == f"fixture:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        del password_hash
        return False


FAST_PASSWORDS = FastPasswordManager()


@pytest.fixture(scope="module")
def passwords() -> PasswordManager:
    """Share intentionally expensive Argon2id initialization within this test module."""
    return PasswordManager()


@pytest.fixture
def security() -> SecuritySettings:
    return SecuritySettings(
        access_token_secret=SecretStr(TEST_SIGNING_KEY),
        refresh_cookie_secure=True,
        login_rate_limit_attempts=3,
    )


def build_service(
    repository: FakeAuthenticationRepository,
    audits: FakeAuditRepository,
    passwords: PasswordManagerContract,
    security: SecuritySettings,
) -> AuthenticationService:
    return AuthenticationService(
        repository=repository,  # structurally implements the transaction-scoped adapter
        audit=AuditLogService(audits),
        passwords=passwords,
        access_tokens=AccessTokenManager(security),
        rate_limiter=InMemoryLoginRateLimiter(attempts=3, window_seconds=300),
        security=security,
        email=EmailSettings(),
    )


def test_passwords_use_argon2id_and_never_embed_plaintext(passwords: PasswordManager) -> None:
    password_hash = passwords.hash(CREDENTIAL_FIXTURE)

    assert password_hash.startswith("$argon2id$")
    assert CREDENTIAL_FIXTURE not in password_hash
    assert passwords.verify(password_hash, CREDENTIAL_FIXTURE)
    assert not passwords.verify(password_hash, "incorrect")
    assert not passwords.verify(None, CREDENTIAL_FIXTURE)


def test_password_policy_returns_typed_password_validation() -> None:
    with pytest.raises(ValidationError) as captured:
        RegisterRequest(
            email="person@example.com",
            display_name="Person",
            password="weak",  # pragma: allowlist secret  # noqa: S106 - invalid fixture.
        )

    assert any(error["loc"] == ("password",) for error in captured.value.errors())


def test_access_tokens_are_short_lived_and_fixed_to_expected_session(
    security: SecuritySettings,
) -> None:
    manager = AccessTokenManager(security)
    user_id, session_id = uuid4(), uuid4()
    token = manager.issue(user_id=user_id, session_id=session_id)
    claims = manager.decode(token)

    assert (claims.sub, claims.sid, claims.token_type) == (user_id, session_id, "access")
    assert 0 < claims.exp - claims.iat <= security.access_token_ttl_seconds
    with pytest.raises(ValueError, match="invalid"):
        manager.decode(token + "tampered")


@pytest.mark.anyio
async def test_refresh_rotation_stores_only_hash_and_revokes_family_on_reuse(
    security: SecuritySettings,
) -> None:
    repository = FakeAuthenticationRepository()
    audits = FakeAuditRepository()
    user = User(
        id=uuid4(),
        email="person@example.com",
        display_name="Person",
        password_hash=f"fixture:{CREDENTIAL_FIXTURE}",
        status="active",
        email_verified_at=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
        version=1,
    )
    repository.add(user)
    service = build_service(repository, audits, FAST_PASSWORDS, security)

    initial = await service.login(
        LoginRequest(email=user.email, password=CREDENTIAL_FIXTURE),
        client_ip="127.0.0.1",
        request_id="request-1",
    )
    initial_record = repository.refresh_tokens[hash_opaque_token(initial.refresh_token)]
    assert initial.refresh_token not in repository.refresh_tokens
    assert initial_record.status == "active"

    rotated = await service.refresh(initial.refresh_token, request_id="request-2")
    rotated_record = repository.refresh_tokens[hash_opaque_token(rotated.refresh_token)]
    assert initial_record.status == "revoked"
    assert initial_record.replaced_by_token_id == rotated_record.id
    assert rotated_record.family_id == initial_record.family_id

    with pytest.raises(ApiError) as reuse:
        await service.refresh(initial.refresh_token, request_id="request-3")
    assert reuse.value.status_code == 401
    assert rotated_record.status == "revoked"
    assert any(entry.action == "auth.refresh_reuse_detected" for entry in audits.entries)


@pytest.mark.anyio
async def test_rate_limiter_blocks_after_configured_attempts() -> None:
    limiter = InMemoryLoginRateLimiter(attempts=2, window_seconds=60)
    first = await limiter.check(email="person@example.com", client_ip="127.0.0.1")
    second = await limiter.check(email="person@example.com", client_ip="127.0.0.1")
    blocked = await limiter.check(email="person@example.com", client_ip="127.0.0.1")
    assert first.allowed and second.allowed
    assert not blocked.allowed and blocked.retry_after_seconds > 0


def test_refresh_cookie_is_http_only_secure_scoped_and_clearable(
    security: SecuritySettings,
) -> None:
    response = Response()
    set_refresh_cookie(response, "opaque-refresh-value", security)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "opaque-refresh-value" in cookie

    cleared = Response()
    clear_refresh_cookie(cleared, security)
    assert "Max-Age=0" in cleared.headers["set-cookie"]


@pytest.mark.anyio
async def test_expired_refresh_token_is_rejected(
    security: SecuritySettings,
) -> None:
    repository = FakeAuthenticationRepository()
    audits = FakeAuditRepository()
    user_id, family_id = uuid4(), uuid4()
    user = User(
        id=user_id,
        email="expired@example.com",
        display_name="Expired",
        status="active",
        email_verified_at=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
        version=1,
    )
    repository.add(user)
    raw = "expired-refresh-token-value-that-is-long-enough"
    token = RefreshToken(
        id=uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_opaque_token(raw),
        status="active",
        expires_at=utc_now() - timedelta(seconds=1),
        client_metadata={},
        created_at=utc_now(),
        updated_at=utc_now(),
        version=1,
    )
    repository.add(token)

    with pytest.raises(ApiError) as rejected:
        await build_service(repository, audits, FAST_PASSWORDS, security).refresh(
            raw, request_id="request-expired"
        )
    assert rejected.value.status_code == 401
    assert token.status == "expired"


@pytest.mark.anyio
async def test_security_rejection_commits_family_revocation_before_returning_401() -> None:
    class FakeDatabase:
        committed = False
        rolled_back = False

        @asynccontextmanager
        async def transaction(self) -> Any:
            try:
                yield object()
            except Exception:
                self.rolled_back = True
                raise
            else:
                self.committed = True

    database = FakeDatabase()
    resources = cast(ApplicationResources, SimpleNamespace(database=database))
    dependency = cast(AsyncGenerator[Any, None], database_transaction_dependency(resources))
    await anext(dependency)
    rejection = ApiError(
        401,
        "authentication_required",
        "Refresh session is invalid.",
        commit_transaction=True,
    )

    with pytest.raises(ApiError) as captured:
        await dependency.athrow(rejection)

    assert captured.value is rejection
    assert database.committed
    assert not database.rolled_back


@pytest.mark.anyio
async def test_password_reset_is_single_use_and_revokes_existing_sessions(
    security: SecuritySettings,
) -> None:
    repository = FakeAuthenticationRepository()
    audits = FakeAuditRepository()
    user = User(
        id=uuid4(),
        email="recovery@example.com",
        display_name="Recovery",
        password_hash=f"fixture:{CREDENTIAL_FIXTURE}",
        status="active",
        email_verified_at=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
        version=1,
    )
    repository.add(user)
    service = build_service(repository, audits, FAST_PASSWORDS, security)
    session = await service.login(
        LoginRequest(email=user.email, password=CREDENTIAL_FIXTURE),
        client_ip="127.0.0.1",
        request_id="request-login",
    )
    pending = await service.request_password_reset(user.email, request_id="request-reset")
    assert pending is not None
    raw_token = pending.message.body.split("token=", maxsplit=1)[1].splitlines()[0]

    await service.reset_password(
        ResetPasswordRequest(token=raw_token, password=NEW_CREDENTIAL_FIXTURE),
        request_id="request-complete",
    )

    assert repository.refresh_tokens[hash_opaque_token(session.refresh_token)].status == "revoked"
    assert user.password_hash == f"fixture:{NEW_CREDENTIAL_FIXTURE}"
    with pytest.raises(ApiError) as reused:
        await service.reset_password(
            ResetPasswordRequest(token=raw_token, password=SECOND_CREDENTIAL_FIXTURE),
            request_id="request-reuse",
        )
    assert reused.value.code == "invalid_or_expired_token"


@pytest.mark.anyio
async def test_unverified_user_cannot_login(
    security: SecuritySettings,
) -> None:
    repository = FakeAuthenticationRepository()
    audits = FakeAuditRepository()
    user = User(
        id=uuid4(),
        email="pending@example.com",
        display_name="Pending",
        password_hash=f"fixture:{CREDENTIAL_FIXTURE}",
        status="active",
        created_at=utc_now(),
        updated_at=utc_now(),
        version=1,
    )
    repository.add(user)

    with pytest.raises(ApiError) as rejected:
        await build_service(repository, audits, FAST_PASSWORDS, security).login(
            LoginRequest(email=user.email, password=CREDENTIAL_FIXTURE),
            client_ip="127.0.0.1",
            request_id="request-unverified",
        )

    assert rejected.value.status_code == 403
    assert rejected.value.code == "email_not_verified"


@pytest.mark.anyio
async def test_login_route_returns_access_token_and_http_only_refresh_cookie(
    app: FastAPI,
) -> None:
    user = User(
        id=uuid4(),
        email="route@example.com",
        display_name="Route",
        status="active",
        email_verified_at=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
        version=1,
    )
    service = cast(Any, SimpleNamespace())

    async def login(*args: Any, **kwargs: Any) -> AuthenticatedSession:
        del args, kwargs
        return AuthenticatedSession(
            response=AccessTokenResponse(
                access_token=ACCESS_TOKEN_FIXTURE,
                expires_in=300,
                user=AuthenticationService.user_response(user),
            ),
            refresh_token=REFRESH_TOKEN_FIXTURE,
            refresh_token_id=uuid4(),
        )

    service.login = login

    async def override_service() -> Any:
        return service

    app.dependency_overrides[authentication_service_dependency] = override_service
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="https://testserver") as client,
    ):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": CREDENTIAL_FIXTURE},
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == ACCESS_TOKEN_FIXTURE
    assert REFRESH_TOKEN_FIXTURE not in response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
