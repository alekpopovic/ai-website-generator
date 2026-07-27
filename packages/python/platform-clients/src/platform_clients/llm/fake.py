"""Deterministic no-I/O inference gateway for unit tests and default CI."""

from datetime import UTC, datetime

from pydantic import BaseModel

from platform_clients.llm.models import (
    ChatRequest,
    EmbeddingRequest,
    InferenceMetadata,
    InferenceResult,
    ModelMetadata,
    ModelReadiness,
    ModelRole,
    VisionRequest,
    WarmupResult,
)


class FakeLLMGateway:
    """Returns explicit fixtures and never synthesizes fake business content."""

    def __init__(self, *, structured_payloads: dict[str, object] | None = None) -> None:
        self.structured_payloads = structured_payloads or {}
        self.calls: list[tuple[str, ModelRole]] = []
        self._models = {
            ModelRole.GENERATION: self._metadata("qwen3-coder:30b", "1" * 64, "completion"),
            ModelRole.VISION: self._metadata("qwen3-vl:8b", "2" * 64, "vision"),
            ModelRole.EMBEDDING: self._metadata("qwen3-embedding:0.6b", "3" * 64, "embedding"),
        }

    @staticmethod
    def _metadata(name: str, digest: str, capability: str) -> ModelMetadata:
        return ModelMetadata(
            provider="fake",
            name=name,
            digest=digest,
            size=0,
            modified_at=datetime(2026, 1, 1, tzinfo=UTC),
            capabilities=frozenset({capability}),
            format="gguf",
            embedding_dimensions=3 if capability == "embedding" else None,
        )

    def _result[ValueT](self, value: ValueT, role: ModelRole) -> InferenceResult[ValueT]:
        model = self._models[role]
        return InferenceResult(
            value=value,
            metadata=InferenceMetadata(
                provider="fake",
                model=model.name,
                model_digest=model.digest,
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
            ),
        )

    async def generate_chat(self, request: ChatRequest) -> InferenceResult[str]:
        self.calls.append(("chat", ModelRole.GENERATION))
        return self._result("", ModelRole.GENERATION)

    async def generate_structured[OutputT: BaseModel](
        self, request: ChatRequest, response_model: type[OutputT]
    ) -> InferenceResult[OutputT]:
        self.calls.append(("structured", ModelRole.GENERATION))
        value = response_model.model_validate(
            self.structured_payloads.get(response_model.__name__, {})
        )
        return self._result(value, ModelRole.GENERATION)

    async def analyze_vision[OutputT: BaseModel](
        self, request: VisionRequest, response_model: type[OutputT]
    ) -> InferenceResult[OutputT]:
        self.calls.append(("vision", ModelRole.VISION))
        value = response_model.model_validate(
            self.structured_payloads.get(response_model.__name__, {})
        )
        return self._result(value, ModelRole.VISION)

    async def create_embeddings(
        self, request: EmbeddingRequest
    ) -> InferenceResult[tuple[tuple[float, ...], ...]]:
        self.calls.append(("embedding", ModelRole.EMBEDDING))
        dimensions = request.dimensions or 3
        vectors = tuple(
            tuple(float(index == 0) for index in range(dimensions)) for _ in request.inputs
        )
        return self._result(vectors, ModelRole.EMBEDDING)

    async def list_models(self) -> tuple[ModelMetadata, ...]:
        return tuple(self._models.values())

    async def model_metadata(self, role: ModelRole) -> ModelMetadata:
        return self._models[role]

    async def readiness(self) -> tuple[ModelReadiness, ...]:
        return tuple(
            ModelReadiness(
                role=role,
                model=model.name,
                installed=True,
                capable=True,
                required_capability=next(iter(model.capabilities)),
                digest=model.digest,
                capabilities=model.capabilities,
            )
            for role, model in self._models.items()
        )

    async def warm_up(self, role: ModelRole) -> WarmupResult:
        self.calls.append(("warm-up", role))
        model = self._models[role]
        return WarmupResult(model=model.name, model_digest=model.digest, latency_ms=0)

    async def close(self) -> None:
        return None
