"""Authentication orchestration inside caller-owned database transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID, uuid4

from platform_api.auth.mail import AuthenticationEmail
from platform_api.auth.rate_limit import LoginRateLimiter
from platform_api.auth.schemas import (
    AccessTokenResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserResponse,
)
from platform_api.auth.security import (
    AccessTokenClaims,
    AccessTokenManager,
    hash_opaque_token,
    issue_opaque_token,
)
from platform_api.config import EmailSettings, SecuritySettings
from platform_api.errors import ApiError, DependencyUnavailableError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.base import utc_now
from platform_api.persistence.models import AuthActionToken, RefreshToken, User


class AuthenticationRepositoryContract(Protocol):
    """Transaction-scoped persistence surface required by authentication."""

    def add(self, entity: User | RefreshToken | AuthActionToken) -> None: ...

    async def flush(self) -> None: ...

    async def user_by_email(self, email: str) -> User | None: ...

    async def user_by_id(self, user_id: UUID) -> User | None: ...

    async def refresh_for_update(self, token_hash: str) -> RefreshToken | None: ...

    async def action_for_update(
        self, *, token_hash: str, purpose: str
    ) -> AuthActionToken | None: ...

    async def revoke_family(self, family_id: UUID) -> None: ...

    async def revoke_all_for_user(self, user_id: UUID) -> None: ...

    async def consume_pending_actions(self, *, user_id: UUID, purpose: str) -> None: ...


class PasswordManagerContract(Protocol):
    """CPU-bound password boundary, replaceable by deterministic unit fakes."""

    async def hash(self, password: str) -> str: ...

    async def verify(self, password_hash: str | None, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Access response and raw rotating cookie value returned only to the route."""

    response: AccessTokenResponse
    refresh_token: str
    refresh_token_id: UUID


@dataclass(frozen=True, slots=True)
class PendingAuthenticationEmail:
    """Message scheduled only after the request transaction completes."""

    message: AuthenticationEmail


class AuthenticationService:
    """Implement registration, session rotation, recovery, and verification policies."""

    def __init__(
        self,
        *,
        repository: AuthenticationRepositoryContract,
        audit: AuditLogService,
        passwords: PasswordManagerContract,
        access_tokens: AccessTokenManager,
        rate_limiter: LoginRateLimiter,
        security: SecuritySettings,
        email: EmailSettings,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._passwords = passwords
        self._access_tokens = access_tokens
        self._rate_limiter = rate_limiter
        self._security = security
        self._email = email

    async def register(
        self, payload: RegisterRequest, *, request_id: str
    ) -> tuple[UserResponse, PendingAuthenticationEmail]:
        email = str(payload.email).lower()
        if await self._repository.user_by_email(email) is not None:
            raise ApiError(HTTPStatus.CONFLICT, "email_already_registered", "Unable to register.")
        password_hash = await self._passwords.hash(payload.password)
        user = User(
            email=email,
            display_name=payload.display_name,
            password_hash=password_hash,
            password_changed_at=utc_now(),
            status="active",
        )
        self._repository.add(user)
        await self._repository.flush()
        pending_email = await self._create_action_email(
            user=user,
            purpose="email_verification",
            ttl_seconds=self._security.email_verification_ttl_seconds,
            route="verify-email",
            subject="Verify your Website Generator email",
        )
        self._audit.record(
            action="auth.user_registered",
            resource_type="user",
            resource_id=user.id,
            request_id=request_id,
        )
        return self.user_response(user), pending_email

    async def login(
        self, payload: LoginRequest, *, client_ip: str, request_id: str
    ) -> AuthenticatedSession:
        email = str(payload.email).lower()
        try:
            decision = await self._rate_limiter.check(email=email, client_ip=client_ip)
        except Exception as error:  # Redis and fake adapters expose unrelated failure types.
            raise DependencyUnavailableError("login rate limiter") from error
        if not decision.allowed:
            raise ApiError(
                HTTPStatus.TOO_MANY_REQUESTS,
                "login_rate_limited",
                "Too many login attempts. Try again later.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        user = await self._repository.user_by_email(email)
        password_hash = user.password_hash if user is not None else None
        valid = await self._passwords.verify(password_hash, payload.password)
        if not valid or user is None or user.status != "active":
            self._audit.record(
                action="auth.login_failed",
                resource_type="authentication",
                request_id=request_id,
                details={"reason": "invalid_credentials"},
            )
            raise self.unauthorized("Invalid email or password.")
        if user.email_verified_at is None:
            self._audit.record(
                action="auth.login_failed",
                resource_type="user",
                resource_id=user.id,
                request_id=request_id,
                details={"reason": "email_unverified"},
            )
            raise ApiError(
                HTTPStatus.FORBIDDEN,
                "email_not_verified",
                "Verify your email address before signing in.",
            )
        await self._rate_limiter.reset(email=email, client_ip=client_ip)
        if user.password_hash is not None and self._passwords.needs_rehash(user.password_hash):
            user.password_hash = await self._passwords.hash(payload.password)
            user.password_changed_at = utc_now()
        session = await self._new_session(user=user, family_id=uuid4())
        self._audit.record(
            action="auth.login_succeeded",
            resource_type="user",
            resource_id=user.id,
            request_id=request_id,
            details={"session_id": str(session.refresh_token_id)},
        )
        return session

    async def refresh(self, raw_token: str, *, request_id: str) -> AuthenticatedSession:
        token = await self._repository.refresh_for_update(hash_opaque_token(raw_token))
        if token is None:
            raise self.unauthorized("Refresh session is invalid.", commit_transaction=True)
        if token.status != "active":
            await self._repository.revoke_family(token.family_id)
            self._audit.record(
                action="auth.refresh_reuse_detected",
                resource_type="refresh_token_family",
                actor_user_id=token.user_id,
                resource_id=token.family_id,
                request_id=request_id,
            )
            raise self.unauthorized("Refresh session is invalid.")
        if token.expires_at <= utc_now():
            token.status = "expired"
            raise self.unauthorized("Refresh session has expired.", commit_transaction=True)
        user = await self._repository.user_by_id(token.user_id)
        if user is None or user.status != "active":
            await self._repository.revoke_family(token.family_id)
            raise self.unauthorized("Refresh session is invalid.", commit_transaction=True)

        next_token = await self._new_session(user=user, family_id=token.family_id)
        token.status = "revoked"
        token.revoked_at = utc_now()
        token.replaced_by_token_id = next_token.refresh_token_id
        self._audit.record(
            action="auth.refresh_rotated",
            resource_type="refresh_token_family",
            actor_user_id=user.id,
            resource_id=token.family_id,
            request_id=request_id,
        )
        return next_token

    async def logout(self, raw_token: str | None, *, request_id: str) -> None:
        if raw_token is None:
            return
        token = await self._repository.refresh_for_update(hash_opaque_token(raw_token))
        if token is None:
            return
        await self._repository.revoke_family(token.family_id)
        self._audit.record(
            action="auth.session_logged_out",
            resource_type="refresh_token_family",
            actor_user_id=token.user_id,
            resource_id=token.family_id,
            request_id=request_id,
        )

    async def logout_all(self, user: User, *, request_id: str) -> None:
        await self._repository.revoke_all_for_user(user.id)
        self._audit.record(
            action="auth.all_sessions_logged_out",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            request_id=request_id,
        )

    async def request_password_reset(
        self, email: str, *, request_id: str
    ) -> PendingAuthenticationEmail | None:
        user = await self._repository.user_by_email(email.lower())
        if user is None or user.status != "active":
            return None
        await self._repository.consume_pending_actions(user_id=user.id, purpose="password_reset")
        pending = await self._create_action_email(
            user=user,
            purpose="password_reset",
            ttl_seconds=self._security.password_reset_ttl_seconds,
            route="reset-password",
            subject="Reset your Website Generator password",
        )
        self._audit.record(
            action="auth.password_reset_requested",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            request_id=request_id,
        )
        return pending

    async def reset_password(self, payload: ResetPasswordRequest, *, request_id: str) -> None:
        action = await self._valid_action(payload.token, "password_reset")
        user = await self._repository.user_by_id(action.user_id)
        if user is None or user.status != "active":
            raise self._invalid_action()
        user.password_hash = await self._passwords.hash(payload.password)
        user.password_changed_at = utc_now()
        action.consumed_at = utc_now()
        await self._repository.revoke_all_for_user(user.id)
        self._audit.record(
            action="auth.password_reset_completed",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            request_id=request_id,
        )

    async def verify_email(self, raw_token: str, *, request_id: str) -> None:
        action = await self._valid_action(raw_token, "email_verification")
        user = await self._repository.user_by_id(action.user_id)
        if user is None or user.status != "active":
            raise self._invalid_action()
        if user.email_verified_at is None:
            user.email_verified_at = utc_now()
        await self._repository.consume_pending_actions(
            user_id=user.id, purpose="email_verification"
        )
        self._audit.record(
            action="auth.email_verified",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            request_id=request_id,
        )

    async def current_user(self, claims: AccessTokenClaims) -> User:
        user = await self._repository.user_by_id(claims.sub)
        if user is None or user.status != "active":
            raise self.unauthorized("Access token is invalid.")
        return user

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            return self._access_tokens.decode(token)
        except ValueError as error:
            raise self.unauthorized("Access token is invalid.") from error

    async def _new_session(self, *, user: User, family_id: UUID) -> AuthenticatedSession:
        opaque = issue_opaque_token()
        record = RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=opaque.digest,
            status="active",
            expires_at=utc_now() + timedelta(seconds=self._security.refresh_token_ttl_seconds),
            client_metadata={},
        )
        self._repository.add(record)
        await self._repository.flush()
        access_token = self._access_tokens.issue(user_id=user.id, session_id=record.id)
        return AuthenticatedSession(
            response=AccessTokenResponse(
                access_token=access_token,
                expires_in=self._access_tokens.ttl_seconds,
                user=self.user_response(user),
            ),
            refresh_token=opaque.raw,
            refresh_token_id=record.id,
        )

    async def _valid_action(self, raw_token: str, purpose: str) -> AuthActionToken:
        action = await self._repository.action_for_update(
            token_hash=hash_opaque_token(raw_token), purpose=purpose
        )
        if action is None or action.consumed_at is not None or action.expires_at <= utc_now():
            raise self._invalid_action()
        return action

    async def _create_action_email(
        self,
        *,
        user: User,
        purpose: str,
        ttl_seconds: int,
        route: str,
        subject: str,
    ) -> PendingAuthenticationEmail:
        opaque = issue_opaque_token()
        self._repository.add(
            AuthActionToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=opaque.digest,
                expires_at=utc_now() + timedelta(seconds=ttl_seconds),
            )
        )
        base_url = str(self._email.public_web_url).rstrip("/")
        # Fragments stay out of HTTP request targets, proxy logs, and Referrer headers.
        url = f"{base_url}/{route}#{urlencode({'token': opaque.raw})}"
        return PendingAuthenticationEmail(
            AuthenticationEmail(
                recipient=user.email,
                subject=subject,
                body=f"Open this one-time link to continue:\n\n{url}\n\nIf you did not request this, ignore this email.",
            )
        )

    @staticmethod
    def user_response(user: User) -> UserResponse:
        return UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_verified_at is not None,
            created_at=user.created_at,
        )

    @staticmethod
    def unauthorized(detail: str, *, commit_transaction: bool = False) -> ApiError:
        return ApiError(
            HTTPStatus.UNAUTHORIZED,
            "authentication_required",
            detail,
            headers={"WWW-Authenticate": "Bearer"},
            commit_transaction=commit_transaction,
        )

    @staticmethod
    def _invalid_action() -> ApiError:
        return ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_or_expired_token",
            "The token is invalid or expired.",
        )
