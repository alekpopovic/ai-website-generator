"""Local Uvicorn entry point."""

from __future__ import annotations

import uvicorn

from platform_api.config import get_settings


def main() -> None:
    """Run the development ASGI server using validated bind settings."""
    settings = get_settings()
    uvicorn.run(
        "platform_api.main:app",
        host=settings.application.api_host,
        port=settings.application.api_port,
        reload=False,
        access_log=True,
    )


if __name__ == "__main__":
    main()
