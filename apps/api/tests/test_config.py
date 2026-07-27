"""Unit tests for typed sectioned configuration."""

from __future__ import annotations

import pytest
from platform_api.config import (
    ApplicationSettings,
    DatabaseSettings,
    SecuritySettings,
    Settings,
)
from pydantic import SecretStr, ValidationError


def test_settings_are_divided_and_immutable() -> None:
    """The root graph exposes strongly typed configuration sections."""
    settings = Settings()

    assert isinstance(settings.application, ApplicationSettings)
    assert isinstance(settings.database, DatabaseSettings)
    assert isinstance(settings.security, SecuritySettings)
    with pytest.raises(ValidationError):
        settings.application.environment = "production"


def test_environment_values_load_into_their_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each section owns a documented environment prefix."""
    monkeypatch.setenv("APP_FAKE_DEPENDENCIES", "true")
    monkeypatch.setenv("DATABASE_POOL_SIZE", "17")
    monkeypatch.setenv("SECURITY_TRUSTED_HOSTS", '["api.example.test"]')

    settings = Settings()

    assert settings.application.fake_dependencies is True
    assert settings.database.pool_size == 17
    assert settings.security.trusted_hosts == ("api.example.test",)


def test_blank_database_url_is_explicitly_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committed example files never create a malformed engine from a blank secret."""
    monkeypatch.setenv("DATABASE_URL", "")

    assert DatabaseSettings().url is None


def test_database_rejects_a_synchronous_driver_url() -> None:
    """The API cannot accidentally construct a blocking SQLAlchemy engine."""
    with pytest.raises(ValidationError):
        DatabaseSettings(
            url=SecretStr("postgresql://user:password@database/app")  # pragma: allowlist secret
        )


def test_security_rejects_unrestricted_hosts() -> None:
    """A wildcard Host policy cannot be enabled accidentally."""
    with pytest.raises(ValidationError):
        SecuritySettings(trusted_hosts=("*",))
