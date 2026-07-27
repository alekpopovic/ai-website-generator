"""Central exception mapping to non-leaking problem responses."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from platform_api.constants import PROBLEM_MEDIA_TYPE
from platform_api.logging import get_logger
from platform_api.models.problem import InvalidParameter, ProblemDetail


class ApiError(Exception):
    """Expected API failure with a stable public code and safe detail."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class DependencyUnavailableError(ApiError):
    """Raised when a route requires an unavailable infrastructure dependency."""

    def __init__(self, dependency: str) -> None:
        super().__init__(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            code="dependency_unavailable",
            detail=f"The {dependency} dependency is unavailable.",
        )


def request_id_from(request: Request) -> str:
    """Retrieve the middleware-generated request ID without trusting request headers."""
    return str(getattr(request.state, "request_id", "unknown"))


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    detail: str | None,
    invalid_parameters: list[InvalidParameter] | None = None,
) -> JSONResponse:
    """Build the one canonical problem response shape."""
    try:
        title = HTTPStatus(status).phrase
    except ValueError:
        title = "Request failed"
    problem = ProblemDetail(
        type=f"urn:ai-website-generator:problem:{code}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=request_id_from(request),
        invalid_parameters=invalid_parameters,
    )
    return JSONResponse(
        problem.model_dump(mode="json", by_alias=True, exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Map expected application failures."""
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        detail=exc.detail,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Map validation failures without serializing rejected input values."""
    invalid_parameters = [
        InvalidParameter(
            name=".".join(str(part) for part in error["loc"][1:]) or "request",
            location=str(error["loc"][0]),
            reason=str(error["msg"]),
        )
        for error in exc.errors()
    ]
    return problem_response(
        request,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="request_validation_failed",
        detail="The request did not satisfy the API contract.",
        invalid_parameters=invalid_parameters,
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Map framework HTTP failures to problem details."""
    detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return problem_response(
        request,
        status=exc.status_code,
        code="http_error",
        detail=detail,
    )


async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Hide database implementation details while logging the original failure."""
    get_logger().exception("database_error", request_id=request_id_from(request), exc_info=exc)
    return problem_response(
        request,
        status=HTTPStatus.SERVICE_UNAVAILABLE,
        code="database_unavailable",
        detail="A required data service is unavailable.",
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a stable error contract without exposing internals."""
    get_logger().exception("unhandled_error", request_id=request_id_from(request), exc_info=exc)
    return problem_response(
        request,
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="internal_server_error",
        detail="An unexpected error occurred.",
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Register exception mappings in one explicit composition function."""
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, database_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)


def problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Build reusable OpenAPI response metadata for problem responses."""
    return {
        status: {
            "model": ProblemDetail,
            "content": {PROBLEM_MEDIA_TYPE: {}},
            "description": HTTPStatus(status).phrase,
        }
        for status in status_codes
    }
