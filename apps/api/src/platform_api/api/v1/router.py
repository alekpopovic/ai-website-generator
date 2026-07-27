"""Version 1 route composition."""

from fastapi import APIRouter

from platform_api.api.v1.system import router as system_router

router = APIRouter()
router.include_router(system_router, tags=["system"])
