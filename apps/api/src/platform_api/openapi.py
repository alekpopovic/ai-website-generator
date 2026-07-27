"""Deterministic OpenAPI schema generation and shared contract registration."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from platform_api.models.common import PaginationMeta, PaginationParams, ResponseMeta
from platform_api.models.problem import InvalidParameter, ProblemDetail

EXPORTED_CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    InvalidParameter,
    ProblemDetail,
    PaginationMeta,
    PaginationParams,
    ResponseMeta,
)


def build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """Build OpenAPI from application routes and register reusable contract primitives."""
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
    )
    components = schema.setdefault("components", {})
    component_schemas = components.setdefault("schemas", {})
    for model in EXPORTED_CONTRACT_MODELS:
        component_schemas.setdefault(
            model.__name__,
            model.model_json_schema(ref_template="#/components/schemas/{model}"),
        )
    return schema


def install_openapi_schema(app: FastAPI) -> None:
    """Install the cached application-specific OpenAPI builder."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = build_openapi_schema(app)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
