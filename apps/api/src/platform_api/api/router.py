"""Top-level API router composition."""

from fastapi import APIRouter

from platform_api.api.health import router as health_router
from platform_api.api.v1.router import router as v1_router
from platform_api.constants import API_V1_PREFIX

router = APIRouter()
router.include_router(health_router, prefix="/health", tags=["health"])
router.include_router(v1_router, prefix=API_V1_PREFIX)
