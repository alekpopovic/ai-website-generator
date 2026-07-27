"""Explicit, development-only local account seed command."""

from __future__ import annotations

import argparse
import asyncio
from typing import cast
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from platform_api.config import get_settings
from platform_api.database import DatabaseManager
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import User
from platform_api.persistence.repositories import SqlAlchemyAuditLogRepository


def parse_args() -> argparse.Namespace:
    """Parse the intentionally small local seed surface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="developer@localhost")
    parser.add_argument("--display-name", default="Local Developer")
    return parser.parse_args()


def normalize_local_email(value: str) -> str:
    """Normalize and restrict seeded identities to unmistakably local domains."""
    email = value.strip().lower()
    if not email.endswith(("@localhost", "@local.test")):
        raise ValueError("seed email must end in @localhost or @local.test")
    return email


async def seed_local_user(*, email: str, display_name: str) -> bool:
    """Create the local user idempotently and return whether it was inserted."""
    settings = get_settings()
    if settings.application.environment != "development":
        raise RuntimeError("local user seeding is allowed only in APP_ENV=development")
    manager = DatabaseManager(settings.database)
    try:
        async with manager.transaction() as session:
            normalized_email = normalize_local_email(email)
            normalized_name = display_name.strip()
            if not normalized_name:
                raise ValueError("display name must not be blank")
            user_id = cast(
                UUID | None,
                await session.scalar(
                    insert(User)
                    .values(
                        email=normalized_email,
                        display_name=normalized_name,
                        password_hash=None,
                        status="active",
                    )
                    .on_conflict_do_nothing(index_elements=[User.email])
                    .returning(User.id)
                ),
            )
            if user_id is None:
                return False
            AuditLogService(SqlAlchemyAuditLogRepository(session)).record(
                action="development.user_seeded",
                resource_type="user",
                resource_id=user_id,
                details={"email": normalized_email},
            )
        return True
    finally:
        await manager.close()


def main() -> None:
    """Run the explicit local seed operation."""
    args = parse_args()
    created = asyncio.run(seed_local_user(email=args.email, display_name=args.display_name))
    print("Created local developer account." if created else "Local developer account exists.")


if __name__ == "__main__":
    main()
