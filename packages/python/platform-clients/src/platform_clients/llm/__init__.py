"""Provider-neutral local inference gateway contracts and implementations."""

from platform_clients.llm.fake import FakeLLMGateway
from platform_clients.llm.models import (
    ChatMessage,
    ChatRequest,
    EmbeddingRequest,
    InferenceResult,
    ModelReadiness,
    ModelRole,
    VisionRequest,
)
from platform_clients.llm.ollama import OllamaConfig, OllamaGateway
from platform_clients.llm.protocols import LLMGateway

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "EmbeddingRequest",
    "FakeLLMGateway",
    "InferenceResult",
    "LLMGateway",
    "ModelReadiness",
    "ModelRole",
    "OllamaConfig",
    "OllamaGateway",
    "VisionRequest",
]
