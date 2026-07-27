"""Administrator-only vector collection diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, Request
from platform_clients.llm.models import ModelRole
from platform_clients.llm.ollama import LLMGatewayError
from platform_clients.vector_store.models import CollectionIdentity
from platform_clients.vector_store.qdrant import VectorStoreError
from pydantic import BaseModel, ConfigDict, Field

from platform_api.auth.dependencies import AdministratorUserDependency
from platform_api.dependencies import (
    LLMGatewayDependency,
    SettingsDependency,
    VectorStoreDependency,
)
from platform_api.errors import DependencyUnavailableError, problem_responses
from platform_api.models.common import ApiResponse, ResponseMeta

router = APIRouter()


class EmbeddingCollectionVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    embedding_provider: str
    embedding_model: str
    embedding_model_digest: str
    serialization_schema_version: int = Field(ge=1)


class VectorCollectionStatisticsData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool
    alias: str
    active_collection: str | None
    expected_collection: str
    status: str
    vector_name: str
    expected_dimensions: int = Field(ge=1)
    active_dimensions: int | None = Field(default=None, ge=1)
    points_count: int = Field(ge=0)
    indexed_vectors_count: int = Field(ge=0)
    dimensions_match: bool
    identity_match: bool
    version: EmbeddingCollectionVersion


@router.get(
    "/admin/vector-collections/statistics",
    response_model=ApiResponse[VectorCollectionStatisticsData],
    operation_id="getVectorCollectionStatistics",
    responses=problem_responses(401, 403, 503),
)
async def vector_collection_statistics(
    request: Request,
    administrator: AdministratorUserDependency,
    settings: SettingsDependency,
    gateway: LLMGatewayDependency,
    vector_store: VectorStoreDependency,
) -> ApiResponse[VectorCollectionStatisticsData]:
    """Inspect bounded collection metadata without invoking embedding inference."""
    del administrator
    try:
        metadata = await gateway.model_metadata(ModelRole.EMBEDDING)
        dimensions = metadata.embedding_dimensions
        if dimensions is None:
            raise DependencyUnavailableError("embedding model dimension metadata")
        identity = CollectionIdentity(
            embedding_provider=metadata.provider,
            embedding_model=metadata.name,
            embedding_model_digest=metadata.digest,
            serialization_schema_version=settings.qdrant.serialization_schema_version,
            vector_name=settings.qdrant.vector_name,
        )
        readiness = await vector_store.readiness(identity, dimensions)
        statistics = await vector_store.statistics()
    except (LLMGatewayError, VectorStoreError) as error:
        raise DependencyUnavailableError("vector collection") from error
    return ApiResponse(
        data=VectorCollectionStatisticsData(
            ready=readiness.ready,
            alias=statistics.alias,
            active_collection=statistics.physical_collection,
            expected_collection=readiness.expected_collection,
            status=statistics.status,
            vector_name=identity.vector_name,
            expected_dimensions=dimensions,
            active_dimensions=statistics.dimensions,
            points_count=statistics.points_count,
            indexed_vectors_count=statistics.indexed_vectors_count,
            dimensions_match=readiness.dimensions_match,
            identity_match=readiness.identity_match,
            version=EmbeddingCollectionVersion(
                embedding_provider=identity.embedding_provider,
                embedding_model=identity.embedding_model,
                embedding_model_digest=identity.embedding_model_digest,
                serialization_schema_version=identity.serialization_schema_version,
            ),
        ),
        meta=ResponseMeta(request_id=str(request.state.request_id)),
    )
