"""Provider-neutral inference inputs, results, and model metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class ModelRole(StrEnum):
    """Configured model responsibilities; callers cannot request arbitrary models."""

    GENERATION = "generation"
    VISION = "vision"
    EMBEDDING = "embedding"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    temperature: float = 0.0
    max_output_tokens: int = 2_048

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("chat requires at least one message")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if not 1 <= self.max_output_tokens <= 32_768:
            raise ValueError("max_output_tokens must be between 1 and 32768")


@dataclass(frozen=True, slots=True)
class VisionRequest:
    prompt: str
    images: tuple[bytes, ...]
    temperature: float = 0.0
    max_output_tokens: int = 2_048

    def __post_init__(self) -> None:
        if not self.images:
            raise ValueError("vision analysis requires at least one image")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if not 1 <= self.max_output_tokens <= 32_768:
            raise ValueError("max_output_tokens must be between 1 and 32768")


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    inputs: tuple[str, ...]
    dimensions: int | None = None

    def __post_init__(self) -> None:
        if not self.inputs or len(self.inputs) > 256:
            raise ValueError("embedding input count must be between 1 and 256")
        if self.dimensions is not None and not 1 <= self.dimensions <= 65_536:
            raise ValueError("embedding dimensions must be between 1 and 65536")


@dataclass(frozen=True, slots=True)
class InferenceMetadata:
    provider: str
    model: str
    model_digest: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_duration_ms: float | None = None
    load_duration_ms: float | None = None


@dataclass(frozen=True, slots=True)
class InferenceResult[ValueT]:
    value: ValueT
    metadata: InferenceMetadata


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    name: str
    digest: str
    size: int
    modified_at: datetime
    capabilities: frozenset[str]
    format: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None


@dataclass(frozen=True, slots=True)
class ModelReadiness:
    role: ModelRole
    model: str
    installed: bool
    capable: bool
    required_capability: str
    digest: str | None
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class WarmupResult:
    model: str
    model_digest: str
    latency_ms: float
    loaded: bool = True


type JsonObject = dict[str, object]
type OllamaRole = Literal["system", "user", "assistant"]
