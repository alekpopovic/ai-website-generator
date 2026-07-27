"""Inspect or explicitly remove tagged development-only test artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import NoReturn

from platform_clients.object_storage.models import StorageConfig, StorageProvider
from platform_clients.object_storage.s3 import S3ObjectStorage

_CONFIRMATION = "REMOVE-TEST-ARTIFACTS"


def _optional_environment(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def _config() -> StorageConfig:
    provider = StorageProvider(os.environ.get("MINIO_PROVIDER", "minio"))
    return StorageConfig(
        provider=provider,
        endpoint_url=_optional_environment("MINIO_ENDPOINT"),
        region=os.environ.get("MINIO_REGION", "us-east-1"),
        access_key=_optional_environment("MINIO_ACCESS_KEY"),
        secret_key=_optional_environment("MINIO_SECRET_KEY"),
        session_token=_optional_environment("MINIO_SESSION_TOKEN"),
    )


def _refuse(message: str) -> NoReturn:
    raise SystemExit(message)


async def _run(args: argparse.Namespace) -> None:
    environment = os.environ.get("APP_ENV", "development")
    if environment not in {"development", "test"}:
        _refuse("storage artifact CLI is restricted to development and test environments")
    config = _config()
    if args.command == "remove":
        if args.confirm != _CONFIRMATION:
            _refuse(f"removal requires --confirm {_CONFIRMATION}")
        if config.provider is not StorageProvider.MINIO:
            _refuse("test-artifact removal is restricted to the development MinIO provider")
    storage = await S3ObjectStorage.create(config)
    try:
        artifacts = await storage.list_test_artifacts()
        if args.command == "inspect":
            print(
                json.dumps(
                    [
                        {
                            "bucket": artifact.location.bucket.value,
                            "key": artifact.location.key,
                            "sha256": artifact.sha256,
                            "size": artifact.size,
                        }
                        for artifact in artifacts
                    ],
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        for artifact in artifacts:
            await storage.remove_test_artifact(artifact.location)
        print(f"Removed {len(artifacts)} tagged development test artifact(s).")
    finally:
        await storage.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect", help="list objects tagged aiwg-test-artifact=true")
    remove = subparsers.add_parser("remove", help="remove only tagged development test objects")
    remove.add_argument("--confirm", default="")
    return parser.parse_args()


def main() -> None:
    asyncio.run(_run(parse_args()))
