"""First-party email and password authentication routes."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, BackgroundTasks, Request, Response, status

from platform_api.auth.dependencies import AuthenticationServiceDependency, CurrentUserDependency
from platform_api.auth.schemas import (
    AccessTokenResponse,
    LoginRequest,
    MessageResponse,
    PasswordResetRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserResponse,
    VerifyEmailRequest,
)
from platform_api.config import SecuritySettings
from platform_api.dependencies import ResourcesDependency, SettingsDependency
from platform_api.errors import ApiError, problem_responses, request_id_from

router = APIRouter(prefix="/auth")


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="register",
    responses=problem_responses(409, 422, 503),
)
async def register(
    payload: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: AuthenticationServiceDependency,
    resources: ResourcesDependency,
) -> UserResponse:
    user, pending = await service.register(payload, request_id=request_id_from(request))
    background_tasks.add_task(resources.authentication_mailer.send, pending.message)
    return user


@router.post(
    "/login",
    response_model=AccessTokenResponse,
    operation_id="login",
    responses=problem_responses(401, 403, 422, 429, 503),
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthenticationServiceDependency,
    settings: SettingsDependency,
) -> AccessTokenResponse:
    client_ip = request.client.host if request.client is not None else "unknown"
    session = await service.login(payload, client_ip=client_ip, request_id=request_id_from(request))
    set_refresh_cookie(response, session.refresh_token, settings.security)
    return session.response


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    operation_id="refreshAccessToken",
    responses=problem_responses(401, 503),
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthenticationServiceDependency,
    settings: SettingsDependency,
) -> AccessTokenResponse:
    refresh_token = request.cookies.get(settings.security.refresh_cookie_name)
    if refresh_token is None:
        raise AuthenticationServiceError.missing_refresh(settings.security)
    try:
        session = await service.refresh(refresh_token, request_id=request_id_from(request))
    except ApiError as error:
        error.headers = {
            **(error.headers or {}),
            "Set-Cookie": cleared_cookie_header(settings.security),
        }
        raise
    set_refresh_cookie(response, session.refresh_token, settings.security)
    return session.response


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logout",
    responses=problem_responses(503),
)
async def logout(
    request: Request,
    response: Response,
    service: AuthenticationServiceDependency,
    settings: SettingsDependency,
) -> None:
    refresh_token = request.cookies.get(settings.security.refresh_cookie_name)
    await service.logout(refresh_token, request_id=request_id_from(request))
    clear_refresh_cookie(response, settings.security)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logoutAll",
    responses=problem_responses(401, 503),
)
async def logout_all(
    request: Request,
    response: Response,
    service: AuthenticationServiceDependency,
    user: CurrentUserDependency,
    settings: SettingsDependency,
) -> None:
    await service.logout_all(user, request_id=request_id_from(request))
    clear_refresh_cookie(response, settings.security)


@router.get(
    "/me",
    response_model=UserResponse,
    operation_id="getCurrentUser",
    responses=problem_responses(401, 503),
)
async def current_user(
    user: CurrentUserDependency, service: AuthenticationServiceDependency
) -> UserResponse:
    return service.user_response(user)


@router.post(
    "/request-password-reset",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestPasswordReset",
    responses=problem_responses(422, 503),
)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: AuthenticationServiceDependency,
    resources: ResourcesDependency,
) -> MessageResponse:
    pending = await service.request_password_reset(
        str(payload.email), request_id=request_id_from(request)
    )
    if pending is not None:
        background_tasks.add_task(resources.authentication_mailer.send, pending.message)
    return MessageResponse(message="If the account exists, a password reset email has been sent.")


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="resetPassword",
    responses=problem_responses(400, 422, 503),
)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    service: AuthenticationServiceDependency,
) -> None:
    await service.reset_password(payload, request_id=request_id_from(request))


@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="verifyEmail",
    responses=problem_responses(400, 422, 503),
)
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    service: AuthenticationServiceDependency,
) -> None:
    await service.verify_email(payload.token, request_id=request_id_from(request))


class AuthenticationServiceError:
    """Route-level cookie-aware authentication errors."""

    @staticmethod
    def missing_refresh(settings: SecuritySettings) -> ApiError:
        return ApiError(
            HTTPStatus.UNAUTHORIZED,
            "authentication_required",
            "Refresh session is required.",
            headers={"Set-Cookie": cleared_cookie_header(settings)},
        )


def set_refresh_cookie(response: Response, value: str, settings: SecuritySettings) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=value,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain,
        path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response, settings: SecuritySettings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain,
        path="/api/v1/auth",
    )


def cleared_cookie_header(settings: SecuritySettings) -> str:
    response = Response()
    clear_refresh_cookie(response, settings)
    return response.headers["set-cookie"]
