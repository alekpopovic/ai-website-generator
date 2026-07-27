"""Tests for the guarded local development seed command."""

from __future__ import annotations

import pytest
from platform_api.config import clear_settings_cache
from platform_api.seed import normalize_local_email, seed_local_user


def test_local_seed_email_is_normalized_and_restricted() -> None:
    """The seed cannot create an identity that resembles a real external account."""
    assert normalize_local_email(" Developer@LOCALHOST ") == "developer@localhost"
    assert normalize_local_email("person@local.test") == "person@local.test"
    with pytest.raises(ValueError, match="local"):
        normalize_local_email("person@example.com")


@pytest.mark.anyio
async def test_seed_is_rejected_before_database_access_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production and test processes cannot invoke development data creation."""
    monkeypatch.setenv("APP_ENV", "test")
    clear_settings_cache()
    try:
        with pytest.raises(RuntimeError, match="development"):
            await seed_local_user(email="developer@localhost", display_name="Developer")
    finally:
        clear_settings_cache()
