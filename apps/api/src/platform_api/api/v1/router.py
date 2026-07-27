"""Version 1 route composition."""

from fastapi import APIRouter

from platform_api.api.v1.auth import router as auth_router
from platform_api.api.v1.models import router as models_router
from platform_api.api.v1.projects import router as projects_router
from platform_api.api.v1.system import router as system_router
from platform_api.api.v1.vector_collections import router as vector_collections_router

router = APIRouter()
router.include_router(auth_router, tags=["auth"])
router.include_router(models_router, tags=["models"])
router.include_router(projects_router, tags=["projects"])
router.include_router(system_router, tags=["system"])
router.include_router(vector_collections_router, tags=["vector-collections"])
