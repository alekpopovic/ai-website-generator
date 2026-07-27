"""Explicit FastAPI authentication service and principal dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.auth.service import AuthenticationService
from platform_api.dependencies import (
    DatabaseTransactionDependency,
    ResourcesDependency,
    SettingsDependency,
)
from platform_api.errors import ApiError, DependencyUnavailableError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import User
from platform_api.persistence.repositories import (
    AuthenticationRepository,
    SqlAlchemyAuditLogRepository,
)

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="bearer")


async def authentication_service_dependency(
    session: DatabaseTransactionDependency,
    resources: ResourcesDependency,
    settings: SettingsDependency,
) -> AuthenticationService:
    """Compose authentication against the current request transaction."""
    if resources.access_tokens is None:
        raise DependencyUnavailableError("authentication configuration")
    return AuthenticationService(
        repository=AuthenticationRepository(session),
        audit=AuditLogService(SqlAlchemyAuditLogRepository(session)),
        passwords=resources.password_manager,
        access_tokens=resources.access_tokens,
        rate_limiter=resources.login_rate_limiter,
        security=settings.security,
        email=settings.email,
    )


async def current_user_dependency(
    service: Annotated[AuthenticationService, Depends(authentication_service_dependency)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Validate a bearer access token and load its active user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationService.unauthorized("Access token is required.")
    claims = service.decode_access_token(credentials.credentials)
    return await service.current_user(claims)


AuthenticationServiceDependency = Annotated[
    AuthenticationService, Depends(authentication_service_dependency)
]
CurrentUserDependency = Annotated[User, Depends(current_user_dependency)]


async def administrator_user_dependency(
    user: CurrentUserDependency,
    settings: SettingsDependency,
) -> User:
    """Require membership in the explicit fail-closed administrator allowlist."""
    administrators = {str(email).casefold() for email in settings.security.administrator_emails}
    if user.email.casefold() not in administrators:
        raise ApiError(403, "administrator_required", "Administrator access is required.")
    return user


AdministratorUserDependency = Annotated[User, Depends(administrator_user_dependency)]
