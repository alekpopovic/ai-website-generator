"""Ollama gateway tests against a deterministic in-process fake HTTP server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI, Request, Response
from platform_clients.llm.models import (
    ChatMessage,
    ChatRequest,
    EmbeddingRequest,
    MessageRole,
    ModelRole,
    VisionRequest,
)
from platform_clients.llm.ollama import (
    GatewayBusyError,
    OllamaConfig,
    OllamaGateway,
    ProviderRequestError,
    TransientProviderError,
)
from platform_clients.llm.redaction import PromptPolicy
from pydantic import BaseModel, ConfigDict

MODELS = {
    "qwen3-coder:30b": ("1" * 64, "completion"),
    "qwen3-vl:8b": ("2" * 64, "vision"),
    "qwen3-embedding:0.6b": ("3" * 64, "embedding"),
}


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    score: int


class FakeOllamaServer:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.models = dict(MODELS)
        self.chat_failures: list[int | str] = []
        self.chat_gate: asyncio.Event | None = None
        self.chat_entered = asyncio.Event()
        self._install_routes()

    def _listed_models(self) -> list[dict[str, object]]:
        return [
            {
                "name": name,
                "model": name,
                "modified_at": "2026-07-01T00:00:00Z",
                "size": 1024,
                "digest": digest,
                "details": {"format": "gguf", "family": "qwen3"},
            }
            for name, (digest, _) in self.models.items()
        ]

    def _install_routes(self) -> None:
        @self.app.get("/api/tags")
        async def tags() -> dict[str, object]:
            self.requests.append(("/api/tags", {}))
            return {"models": self._listed_models()}

        @self.app.post("/api/show")
        async def show(request: Request) -> dict[str, object]:
            payload = await request.json()
            self.requests.append(("/api/show", payload))
            _, capability = self.models[payload["model"]]
            return {
                "modified_at": "2026-07-01T00:00:00Z",
                "capabilities": [capability],
                "details": {"format": "gguf", "family": "qwen3"},
                "model_info": ({"qwen3.embedding_length": 3} if capability == "embedding" else {}),
            }

        @self.app.post("/api/chat")
        async def chat(request: Request) -> Any:
            payload = await request.json()
            self.requests.append(("/api/chat", payload))
            self.chat_entered.set()
            if self.chat_gate is not None:
                await self.chat_gate.wait()
            if self.chat_failures:
                failure = self.chat_failures.pop(0)
                if isinstance(failure, int):
                    return Response(status_code=failure, content='{"error":"safe fixture"}')
                if failure == "invalid-structure":
                    content = '{"title":12}'
                else:
                    return Response(content="not-json", media_type="application/json")
            elif payload.get("model") == "qwen3-vl:8b":
                content = '{"title":"vision","score":9}'
            elif "format" in payload:
                content = '{"title":"generated","score":7}'
            else:
                content = "bounded chat"
            return {
                "model": payload["model"],
                "message": {"role": "assistant", "content": content},
                "done": True,
                "total_duration": 2_000_000,
                "load_duration": 500_000,
                "prompt_eval_count": 4,
                "eval_count": 3,
            }

        @self.app.post("/api/embed")
        async def embed(request: Request) -> dict[str, object]:
            payload = await request.json()
            self.requests.append(("/api/embed", payload))
            inputs = payload["input"]
            dimensions = payload.get("dimensions", 3)
            return {
                "model": payload["model"],
                "embeddings": [[1.0] + [0.0] * (dimensions - 1) for _ in inputs],
                "total_duration": 1_000_000,
                "load_duration": 100_000,
                "prompt_eval_count": len(inputs),
            }

        @self.app.post("/api/generate")
        async def generate(request: Request) -> dict[str, object]:
            payload = await request.json()
            self.requests.append(("/api/generate", payload))
            return {"model": payload["model"], "done": True}


async def gateway_for(
    server: FakeOllamaServer,
    *,
    max_attempts: int = 3,
    circuit_failure_threshold: int = 3,
    circuit_recovery_seconds: float = 30,
    max_concurrency: int = 2,
    concurrency_wait_seconds: float = 10,
    request_timeout_seconds: float = 300,
) -> AsyncIterator[OllamaGateway]:
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=server.app), base_url="http://ollama.internal"
    )
    async with client:
        yield OllamaGateway(
            OllamaConfig(
                base_url="http://ollama.internal",
                retry_backoff_seconds=0,
                metadata_cache_seconds=60,
                max_attempts=max_attempts,
                circuit_failure_threshold=circuit_failure_threshold,
                circuit_recovery_seconds=circuit_recovery_seconds,
                max_concurrency=max_concurrency,
                concurrency_wait_seconds=concurrency_wait_seconds,
                request_timeout_seconds=request_timeout_seconds,
            ),
            client,
        )


@pytest.mark.anyio
async def test_structured_chat_retries_invalid_output_and_records_safe_metadata() -> None:
    server = FakeOllamaServer()
    server.chat_failures.append("invalid-structure")
    async for gateway in gateway_for(server):
        result = await gateway.generate_structured(
            ChatRequest(
                messages=(
                    ChatMessage(
                        MessageRole.USER,
                        "password=top-secret-value summarize safely",
                    ),
                )
            ),
            Profile,
        )

    assert result.value == Profile(title="generated", score=7)
    assert result.metadata.model_digest == "1" * 64
    assert result.metadata.prompt_tokens == 4
    chat_payloads = [payload for path, payload in server.requests if path == "/api/chat"]
    assert len(chat_payloads) == 2
    assert "top-secret-value" not in str(chat_payloads)
    assert "[REDACTED]" in str(chat_payloads)
    assert chat_payloads[0]["format"]["additionalProperties"] is False


@pytest.mark.anyio
async def test_vision_embeddings_readiness_metadata_and_warmup_use_fixed_models() -> None:
    server = FakeOllamaServer()
    async for gateway in gateway_for(server):
        vision = await gateway.analyze_vision(
            VisionRequest(prompt="analyze", images=(b"image-bytes",)), Profile
        )
        embeddings = await gateway.create_embeddings(
            EmbeddingRequest(inputs=("one", "two"), dimensions=4)
        )
        readiness = await gateway.readiness()
        warmup = await gateway.warm_up(ModelRole.VISION)

    assert vision.value.title == "vision"
    assert len(embeddings.value) == 2
    assert all(len(vector) == 4 for vector in embeddings.value)
    assert all(model.installed and model.capable for model in readiness)
    embedding_metadata = await gateway.model_metadata(ModelRole.EMBEDDING)
    assert embedding_metadata.embedding_dimensions == 3
    assert warmup.model == "qwen3-vl:8b"
    assert all(path != "/api/pull" for path, _ in server.requests)
    warmup_payload = next(payload for path, payload in server.requests if path == "/api/generate")
    assert warmup_payload["prompt"] == ""


@pytest.mark.anyio
async def test_non_retryable_http_error_is_attempted_once() -> None:
    server = FakeOllamaServer()
    server.chat_failures.append(400)
    async for gateway in gateway_for(server):
        with pytest.raises(ProviderRequestError):
            await gateway.generate_chat(
                ChatRequest(messages=(ChatMessage(MessageRole.USER, "hello"),))
            )

    assert sum(path == "/api/chat" for path, _ in server.requests) == 1


@pytest.mark.anyio
async def test_readiness_reports_a_missing_configured_model_without_pulling() -> None:
    server = FakeOllamaServer()
    server.models.pop("qwen3-vl:8b")
    async for gateway in gateway_for(server):
        readiness = await gateway.readiness()

    vision = next(item for item in readiness if item.role is ModelRole.VISION)
    assert not vision.installed
    assert not vision.capable
    assert vision.digest is None
    assert all(path != "/api/pull" for path, _ in server.requests)


@pytest.mark.anyio
async def test_transient_failures_open_circuit_without_additional_http_calls() -> None:
    server = FakeOllamaServer()
    server.chat_failures.extend([503, 503])
    async for gateway in gateway_for(
        server,
        max_attempts=1,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=60,
    ):
        request = ChatRequest(messages=(ChatMessage(MessageRole.USER, "hello"),))
        with pytest.raises(TransientProviderError):
            await gateway.generate_chat(request)
        with pytest.raises(TransientProviderError):
            await gateway.generate_chat(request)
        with pytest.raises(TransientProviderError, match="circuit"):
            await gateway.generate_chat(request)

    assert sum(path == "/api/chat" for path, _ in server.requests) == 2


def test_prompt_policy_rejects_oversized_text_and_images() -> None:
    policy = PromptPolicy(max_prompt_bytes=8, max_image_bytes=4, max_total_image_bytes=6)
    with pytest.raises(ValueError, match="prompt"):
        policy.prepare_text("too many bytes")
    with pytest.raises(ValueError, match="image"):
        policy.validate_images((b"12345",))


@pytest.mark.anyio
async def test_concurrency_wait_and_request_timeout_are_bounded() -> None:
    server = FakeOllamaServer()
    async for gateway in gateway_for(
        server,
        max_attempts=1,
        max_concurrency=1,
        concurrency_wait_seconds=0.01,
        request_timeout_seconds=1,
    ):
        await gateway.model_metadata(ModelRole.GENERATION)
        server.chat_gate = asyncio.Event()
        request = ChatRequest(messages=(ChatMessage(MessageRole.USER, "hello"),))
        first = asyncio.create_task(gateway.generate_chat(request))
        await server.chat_entered.wait()
        with pytest.raises(GatewayBusyError):
            await gateway.generate_chat(request)
        server.chat_gate.set()
        assert (await first).value == "bounded chat"

    timeout_server = FakeOllamaServer()
    async for gateway in gateway_for(
        timeout_server,
        max_attempts=1,
        request_timeout_seconds=0.01,
    ):
        await gateway.model_metadata(ModelRole.GENERATION)
        timeout_server.chat_gate = asyncio.Event()
        request = ChatRequest(messages=(ChatMessage(MessageRole.USER, "hello"),))
        with pytest.raises(TransientProviderError, match="transport"):
            await gateway.generate_chat(request)
