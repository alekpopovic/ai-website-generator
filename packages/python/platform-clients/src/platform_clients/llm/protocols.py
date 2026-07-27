"""Provider interfaces kept independent from Ollama response shapes."""

from typing import Protocol

from pydantic import BaseModel

from platform_clients.llm.models import (
    ChatRequest,
    EmbeddingRequest,
    InferenceResult,
    ModelMetadata,
    ModelReadiness,
    ModelRole,
    VisionRequest,
    WarmupResult,
)


class ChatGenerator(Protocol):
    async def generate_chat(self, request: ChatRequest) -> InferenceResult[str]: ...


class StructuredGenerator(Protocol):
    async def generate_structured[OutputT: BaseModel](
        self, request: ChatRequest, response_model: type[OutputT]
    ) -> InferenceResult[OutputT]: ...


class VisionAnalyzer(Protocol):
    async def analyze_vision[OutputT: BaseModel](
        self, request: VisionRequest, response_model: type[OutputT]
    ) -> InferenceResult[OutputT]: ...


class EmbeddingGenerator(Protocol):
    async def create_embeddings(
        self, request: EmbeddingRequest
    ) -> InferenceResult[tuple[tuple[float, ...], ...]]: ...


class ModelManager(Protocol):
    async def list_models(self) -> tuple[ModelMetadata, ...]: ...

    async def model_metadata(self, role: ModelRole) -> ModelMetadata: ...

    async def readiness(self) -> tuple[ModelReadiness, ...]: ...

    async def warm_up(self, role: ModelRole) -> WarmupResult: ...


class LLMGateway(
    ChatGenerator,
    StructuredGenerator,
    VisionAnalyzer,
    EmbeddingGenerator,
    ModelManager,
    Protocol,
):
    async def close(self) -> None: ...
