"""Deterministic test application factory and settings helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import FastAPI
from pydantic import AnyHttpUrl

from platform_api.application import create_app
from platform_api.config import ApplicationSettings, SecuritySettings, Settings
from platform_api.telemetry import NoopTelemetry


def test_settings() -> Settings:
    """Return settings that never contact real infrastructure."""
    return Settings(
        application=ApplicationSettings(
            environment="test",
            debug=False,
            fake_dependencies=True,
            cors_allowed_origins=(AnyHttpUrl("http://localhost:4200"),),
        ),
        security=SecuritySettings(
            trusted_hosts=("testserver", "localhost", "127.0.0.1"),
            force_https=False,
            enable_docs=True,
        ),
    )


def create_test_app(
    *,
    settings: Settings | None = None,
    dependency_overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
) -> FastAPI:
    """Build a fake-mode app and apply explicit dependency overrides."""
    resolved_settings = settings or test_settings()
    if not resolved_settings.application.fake_dependencies:
        resolved_settings = resolved_settings.model_copy(
            update={
                "application": resolved_settings.application.model_copy(
                    update={"fake_dependencies": True}
                )
            }
        )
    app = create_app(resolved_settings, telemetry=NoopTelemetry())
    if dependency_overrides:
        app.dependency_overrides.update(dependency_overrides)
    return app
