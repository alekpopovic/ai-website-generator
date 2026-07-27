"""FastAPI application factory and composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from platform_api.api.router import router
from platform_api.config import Settings, get_settings
from platform_api.errors import install_exception_handlers
from platform_api.logging import configure_logging, get_logger
from platform_api.middleware import (
    RequestBodyLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from platform_api.openapi import install_openapi_schema
from platform_api.resources import ApplicationResources
from platform_api.telemetry import OpenTelemetryBoundary, Telemetry


def create_app(
    settings: Settings | None = None,
    *,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    """Create a fully isolated FastAPI application instance."""
    resolved_settings = settings or get_settings()
    resolved_telemetry = telemetry or OpenTelemetryBoundary()
    configure_logging(resolved_settings.application.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        get_logger().info(
            "application_starting",
            environment=resolved_settings.application.environment,
            fake_dependencies=resolved_settings.application.fake_dependencies,
        )
        resources = await ApplicationResources.create(resolved_settings, resolved_telemetry)
        app.state.resources = resources
        try:
            get_logger().info("application_started")
            yield
        finally:
            await resources.close()
            app.state.resources = None
            get_logger().info("application_stopped")

    docs_enabled = resolved_settings.security.enable_docs
    app = FastAPI(
        title=resolved_settings.application.name,
        version=resolved_settings.application.version,
        debug=resolved_settings.application.debug,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.telemetry = resolved_telemetry
    app.include_router(router)
    install_exception_handlers(app)
    install_openapi_schema(app)
    _install_middleware(app, resolved_settings, resolved_telemetry)
    return app


def _install_middleware(app: FastAPI, settings: Settings, telemetry: Telemetry) -> None:
    """Install middleware from innermost to outermost ASGI wrapper."""
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=settings.security.max_request_body_bytes,
        request_id_header=settings.security.request_id_header,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1_000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).rstrip("/") for origin in settings.application.cors_allowed_origins
        ],
        allow_credentials=True,
        allow_methods=["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            settings.security.request_id_header,
        ],
        expose_headers=[settings.security.request_id_header],
        max_age=600,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(settings.security.trusted_hosts),
    )
    if settings.security.force_https:
        app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RequestContextMiddleware,
        header_name=settings.security.request_id_header,
        telemetry=telemetry,
    )
