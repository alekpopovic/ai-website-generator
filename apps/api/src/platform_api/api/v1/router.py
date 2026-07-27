"""Version 1 route composition."""

from fastapi import APIRouter

from platform_api.api.v1.auth import router as auth_router
from platform_api.api.v1.system import router as system_router

router = APIRouter()
router.include_router(auth_router, tags=["auth"])
router.include_router(system_router, tags=["system"])
