"""Dedicated Ollama adapter behind provider-neutral inference contracts."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from platform_clients.llm.redaction import PromptPolicy
from platform_clients.llm.resilience import AsyncCircuitBreaker, CircuitOpenError


class LLMGatewayError(RuntimeError):
    """Safe provider-neutral inference failure."""


class ModelNotInstalledError(LLMGatewayError):
    """A configured model is absent; clients never pull it automatically."""


class MalformedProviderResponseError(LLMGatewayError):
    """The provider or model returned data outside its declared contract."""


class TransientProviderError(LLMGatewayError):
    """A bounded retry may recover from this provider failure."""


class ProviderRequestError(LLMGatewayError):
    """A non-retryable provider request failed."""


class GatewayBusyError(LLMGatewayError):
    """The local concurrency limit could not be acquired in time."""


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    base_url: str
    vision_model: str = "qwen3-vl:8b"
    generation_model: str = "qwen3-coder:30b"
    embedding_model: str = "qwen3-embedding:0.6b"
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 300.0
    concurrency_wait_seconds: float = 10.0
    max_concurrency: int = 2
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.25
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 30.0
    metadata_cache_seconds: float = 30.0
    max_prompt_bytes: int = 262_144
    max_image_bytes: int = 10_485_760
    max_total_image_bytes: int = 20_971_520
    max_response_bytes: int = 4_194_304
    keep_alive: str = "5m"

    def __post_init__(self) -> None:
        endpoint = urlsplit(self.base_url)
        if (
            endpoint.scheme not in {"http", "https"}
            or endpoint.hostname is None
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
        ):
            raise ValueError("base_url must be a credential-free HTTP(S) service root")
        model_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$")
        if any(
            not model_pattern.fullmatch(model) or len(model) > 200
            for model in (self.vision_model, self.generation_model, self.embedding_model)
        ):
            raise ValueError("configured model name is invalid")
        if not 1 <= self.max_concurrency <= 32 or not 1 <= self.max_attempts <= 5:
            raise ValueError("inference concurrency or attempt limit is invalid")
        if (
            min(
                self.connect_timeout_seconds,
                self.request_timeout_seconds,
                self.concurrency_wait_seconds,
                self.circuit_recovery_seconds,
            )
            <= 0
        ):
            raise ValueError("inference timeouts must be positive")
        if self.retry_backoff_seconds < 0 or not 1 <= self.circuit_failure_threshold <= 20:
            raise ValueError("inference retry or circuit configuration is invalid")
        if (
            self.metadata_cache_seconds < 0
            or min(
                self.max_prompt_bytes,
                self.max_image_bytes,
                self.max_total_image_bytes,
                self.max_response_bytes,
            )
            <= 0
        ):
            raise ValueError("inference cache and byte limits are invalid")
        if self.max_total_image_bytes < self.max_image_bytes:
            raise ValueError("combined image limit must cover one maximum-sized image")
        if not re.fullmatch(r"-?\d+(?:ms|s|m|h)?", self.keep_alive):
            raise ValueError("keep_alive must be a bounded Ollama duration")

    def model_for(self, role: ModelRole) -> str:
        return {
            ModelRole.GENERATION: self.generation_model,
            ModelRole.VISION: self.vision_model,
            ModelRole.EMBEDDING: self.embedding_model,
        }[role]


class _Details(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None


class _ListedModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    model: str
    modified_at: datetime
    size: int = Field(ge=0)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    details: _Details = Field(default_factory=_Details)


class _TagsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    models: tuple[_ListedModel, ...]


class _ShowResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    modified_at: datetime | None = None
    capabilities: frozenset[str] = frozenset()
    details: _Details = Field(default_factory=_Details)
    model_info: dict[str, object] = Field(default_factory=dict)


class _AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["assistant"]
    content: str


class _ChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    message: _AssistantMessage
    done: bool
    total_duration: int | None = Field(default=None, ge=0)
    load_duration: int | None = Field(default=None, ge=0)
    prompt_eval_count: int | None = Field(default=None, ge=0)
    eval_count: int | None = Field(default=None, ge=0)


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    embeddings: tuple[tuple[float, ...], ...]
    total_duration: int | None = Field(default=None, ge=0)
    load_duration: int | None = Field(default=None, ge=0)
    prompt_eval_count: int | None = Field(default=None, ge=0)


class _GenerateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    done: bool


_TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_REQUIRED_CAPABILITY = {
    ModelRole.GENERATION: "completion",
    ModelRole.VISION: "vision",
    ModelRole.EMBEDDING: "embedding",
}


class OllamaGateway:
    """Bounded asynchronous Ollama client that never accepts arbitrary endpoint URLs."""

    def __init__(
        self,
        config: OllamaConfig,
        client: httpx2.AsyncClient,
        *,
        owns_client: bool = False,
    ) -> None:
        self._config = config
        self._client = client
        self._owns_client = owns_client
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._breaker = AsyncCircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            recovery_seconds=config.circuit_recovery_seconds,
        )
        self._prompt_policy = PromptPolicy(
            max_prompt_bytes=config.max_prompt_bytes,
            max_image_bytes=config.max_image_bytes,
            max_total_image_bytes=config.max_total_image_bytes,
        )
        self._metadata_cache: dict[str, tuple[float, ModelMetadata]] = {}

    @classmethod
    def create(cls, config: OllamaConfig) -> OllamaGateway:
        timeout = httpx2.Timeout(
            config.request_timeout_seconds,
            connect=config.connect_timeout_seconds,
        )
        client = httpx2.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            limits=httpx2.Limits(
                max_connections=config.max_concurrency,
                max_keepalive_connections=config.max_concurrency,
            ),
        )
        return cls(config, client, owns_client=True)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _execute[ValueT](self, operation: Callable[[], Awaitable[ValueT]]) -> ValueT:
        for attempt in range(1, self._config.max_attempts + 1):
            try:
                await self._breaker.before_request()
            except CircuitOpenError as error:
                raise TransientProviderError("local inference circuit is open") from error
            try:
                await asyncio.wait_for(
                    self._semaphore.acquire(), timeout=self._config.concurrency_wait_seconds
                )
            except TimeoutError as error:
                raise GatewayBusyError("local inference concurrency limit reached") from error
            try:
                try:
                    async with asyncio.timeout(self._config.request_timeout_seconds):
                        result = await operation()
                except (httpx2.TransportError, TimeoutError) as error:
                    raise TransientProviderError("local inference transport failed") from error
            except (MalformedProviderResponseError, TransientProviderError):
                await self._breaker.record_failure()
                if attempt >= self._config.max_attempts:
                    raise
            else:
                await self._breaker.record_success()
                return result
            finally:
                self._semaphore.release()
            await asyncio.sleep(self._config.retry_backoff_seconds * (2 ** (attempt - 1)))
        raise AssertionError("retry loop did not return or raise")

    async def _request_json(
        self,
        method: Literal["GET", "POST"],
        path: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        response = await self._client.request(method, path, json=payload)
        if response.status_code == 404:
            raise ModelNotInstalledError("configured model is not installed")
        if response.status_code in _TRANSIENT_STATUSES:
            raise TransientProviderError("local inference provider is temporarily unavailable")
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderRequestError("local inference provider rejected the request")
        if len(response.content) > self._config.max_response_bytes:
            raise MalformedProviderResponseError("provider response exceeds configured size limit")
        try:
            return response.json()
        except ValueError as error:
            raise MalformedProviderResponseError("provider returned malformed JSON") from error

    async def _validated[ResponseT: BaseModel](
        self,
        method: Literal["GET", "POST"],
        path: str,
        response_model: type[ResponseT],
        payload: dict[str, object] | None = None,
    ) -> ResponseT:
        raw = await self._request_json(method, path, payload)
        try:
            return response_model.model_validate(raw)
        except ValidationError as error:
            raise MalformedProviderResponseError(
                "provider response failed transport validation"
            ) from error

    @staticmethod
    def _duration_ms(value: int | None) -> float | None:
        return None if value is None else round(value / 1_000_000, 3)

    def _inference_metadata(
        self,
        response: _ChatResponse | _EmbeddingResponse,
        model: ModelMetadata,
        latency_ms: float,
    ) -> InferenceMetadata:
        return InferenceMetadata(
            provider="ollama",
            model=response.model,
            model_digest=model.digest,
            latency_ms=round(latency_ms, 3),
            prompt_tokens=response.prompt_eval_count,
            completion_tokens=response.eval_count if isinstance(response, _ChatResponse) else None,
            total_duration_ms=self._duration_ms(response.total_duration),
            load_duration_ms=self._duration_ms(response.load_duration),
        )

    def _chat_payload(
        self,
        request: ChatRequest,
        *,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        prepared = self._prompt_policy.prepare_many(
            tuple(message.content for message in request.messages)
        )
        payload: dict[str, object] = {
            "model": self._config.generation_model,
            "messages": [
                {"role": message.role.value, "content": content}
                for message, content in zip(request.messages, prepared, strict=True)
            ],
            "stream": False,
            "keep_alive": self._config.keep_alive,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        if schema is not None:
            if (
                len(json.dumps(schema, separators=(",", ":")).encode())
                > self._config.max_prompt_bytes
            ):
                raise ValueError("structured output schema exceeds the configured byte limit")
            payload["format"] = schema
        return payload

    def _schema(self, response_model: type[BaseModel]) -> dict[str, Any]:
        schema = response_model.model_json_schema()
        if len(json.dumps(schema, separators=(",", ":")).encode()) > self._config.max_prompt_bytes:
            raise ValueError("structured output schema exceeds the configured byte limit")
        return schema

    async def generate_chat(self, request: ChatRequest) -> InferenceResult[str]:
        model = await self.model_metadata(ModelRole.GENERATION)
        payload = self._chat_payload(request)
        started = time.perf_counter()

        async def operation() -> _ChatResponse:
            response = await self._validated("POST", "/api/chat", _ChatResponse, payload)
            if not response.done:
                raise MalformedProviderResponseError("non-streaming chat response was incomplete")
            return response

        response = await self._execute(operation)
        return InferenceResult(
            value=response.message.content,
            metadata=self._inference_metadata(
                response, model, (time.perf_counter() - started) * 1_000
            ),
        )

    async def generate_structured[OutputT: BaseModel](
        self, request: ChatRequest, response_model: type[OutputT]
    ) -> InferenceResult[OutputT]:
        model = await self.model_metadata(ModelRole.GENERATION)
        payload = self._chat_payload(request, schema=self._schema(response_model))
        started = time.perf_counter()

        async def operation() -> tuple[_ChatResponse, OutputT]:
            response = await self._validated("POST", "/api/chat", _ChatResponse, payload)
            if not response.done:
                raise MalformedProviderResponseError("structured response was incomplete")
            try:
                value = response_model.model_validate_json(response.message.content)
            except (ValidationError, ValueError) as error:
                raise MalformedProviderResponseError(
                    "structured model output failed schema validation"
                ) from error
            return response, value

        response, value = await self._execute(operation)
        return InferenceResult(
            value=value,
            metadata=self._inference_metadata(
                response, model, (time.perf_counter() - started) * 1_000
            ),
        )

    async def analyze_vision[OutputT: BaseModel](
        self, request: VisionRequest, response_model: type[OutputT]
    ) -> InferenceResult[OutputT]:
        self._prompt_policy.validate_images(request.images)
        prompt = self._prompt_policy.prepare_text(request.prompt)
        model = await self.model_metadata(ModelRole.VISION)
        schema = self._schema(response_model)
        payload: dict[str, object] = {
            "model": self._config.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(image).decode("ascii") for image in request.images],
                }
            ],
            "format": schema,
            "stream": False,
            "keep_alive": self._config.keep_alive,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        started = time.perf_counter()

        async def operation() -> tuple[_ChatResponse, OutputT]:
            response = await self._validated("POST", "/api/chat", _ChatResponse, payload)
            if not response.done:
                raise MalformedProviderResponseError("vision response was incomplete")
            try:
                value = response_model.model_validate_json(response.message.content)
            except (ValidationError, ValueError) as error:
                raise MalformedProviderResponseError(
                    "vision model output failed schema validation"
                ) from error
            return response, value

        response, value = await self._execute(operation)
        return InferenceResult(
            value=value,
            metadata=self._inference_metadata(
                response, model, (time.perf_counter() - started) * 1_000
            ),
        )

    async def create_embeddings(
        self, request: EmbeddingRequest
    ) -> InferenceResult[tuple[tuple[float, ...], ...]]:
        inputs = self._prompt_policy.prepare_many(request.inputs)
        model = await self.model_metadata(ModelRole.EMBEDDING)
        payload: dict[str, object] = {
            "model": self._config.embedding_model,
            "input": list(inputs),
            "keep_alive": self._config.keep_alive,
        }
        if request.dimensions is not None:
            payload["dimensions"] = request.dimensions
        started = time.perf_counter()

        async def operation() -> _EmbeddingResponse:
            response = await self._validated("POST", "/api/embed", _EmbeddingResponse, payload)
            if len(response.embeddings) != len(inputs) or any(
                not vector or any(not math.isfinite(value) for value in vector)
                for vector in response.embeddings
            ):
                raise MalformedProviderResponseError(
                    "embedding response shape or values are invalid"
                )
            if request.dimensions is not None and any(
                len(vector) != request.dimensions for vector in response.embeddings
            ):
                raise MalformedProviderResponseError(
                    "embedding dimensions do not match the request"
                )
            return response

        response = await self._execute(operation)
        return InferenceResult(
            value=response.embeddings,
            metadata=self._inference_metadata(
                response, model, (time.perf_counter() - started) * 1_000
            ),
        )

    async def list_models(self) -> tuple[ModelMetadata, ...]:
        response = await self._execute(lambda: self._validated("GET", "/api/tags", _TagsResponse))
        return tuple(
            ModelMetadata(
                provider="ollama",
                name=item.model,
                digest=item.digest,
                size=item.size,
                modified_at=item.modified_at,
                capabilities=frozenset(),
                format=item.details.format,
                family=item.details.family,
                parameter_size=item.details.parameter_size,
                quantization_level=item.details.quantization_level,
            )
            for item in response.models
        )

    async def model_metadata(self, role: ModelRole) -> ModelMetadata:
        name = self._config.model_for(role)
        cached = self._metadata_cache.get(name)
        if (
            cached is not None
            and time.monotonic() - cached[0] <= self._config.metadata_cache_seconds
        ):
            return cached[1]
        listed = next((item for item in await self.list_models() if item.name == name), None)
        if listed is None:
            raise ModelNotInstalledError("configured model is not installed")
        shown = await self._execute(
            lambda: self._validated(
                "POST", "/api/show", _ShowResponse, {"model": name, "verbose": False}
            )
        )
        metadata = ModelMetadata(
            provider="ollama",
            name=listed.name,
            digest=listed.digest,
            size=listed.size,
            modified_at=shown.modified_at or listed.modified_at,
            capabilities=shown.capabilities,
            format=shown.details.format or listed.format,
            family=shown.details.family or listed.family,
            parameter_size=shown.details.parameter_size or listed.parameter_size,
            quantization_level=shown.details.quantization_level or listed.quantization_level,
            embedding_dimensions=_embedding_dimensions(shown.model_info),
        )
        self._metadata_cache[name] = (time.monotonic(), metadata)
        return metadata

    async def readiness(self) -> tuple[ModelReadiness, ...]:
        installed = {model.name: model for model in await self.list_models()}
        results: list[ModelReadiness] = []
        for role in ModelRole:
            name = self._config.model_for(role)
            listed = installed.get(name)
            required = _REQUIRED_CAPABILITY[role]
            if listed is None:
                results.append(
                    ModelReadiness(
                        role=role,
                        model=name,
                        installed=False,
                        capable=False,
                        required_capability=required,
                        digest=None,
                        capabilities=frozenset(),
                    )
                )
                continue
            metadata = await self.model_metadata(role)
            results.append(
                ModelReadiness(
                    role=role,
                    model=name,
                    installed=True,
                    capable=required in metadata.capabilities,
                    required_capability=required,
                    digest=metadata.digest,
                    capabilities=metadata.capabilities,
                )
            )
        return tuple(results)

    async def warm_up(self, role: ModelRole) -> WarmupResult:
        metadata = await self.model_metadata(role)
        required_capability = _REQUIRED_CAPABILITY[role]
        if required_capability not in metadata.capabilities:
            raise ProviderRequestError("configured model lacks its required capability")
        started = time.perf_counter()
        if role is ModelRole.EMBEDDING:
            embedding_response = await self._execute(
                lambda: self._validated(
                    "POST",
                    "/api/embed",
                    _EmbeddingResponse,
                    {
                        "model": metadata.name,
                        "input": "",
                        "keep_alive": self._config.keep_alive,
                    },
                )
            )
            response_model = embedding_response.model
        else:
            generation_response = await self._execute(
                lambda: self._validated(
                    "POST",
                    "/api/generate",
                    _GenerateResponse,
                    {
                        "model": metadata.name,
                        "prompt": "",
                        "stream": False,
                        "keep_alive": self._config.keep_alive,
                    },
                )
            )
            if not generation_response.done:
                raise MalformedProviderResponseError("model warm-up did not complete")
            response_model = generation_response.model
        return WarmupResult(
            model=response_model,
            model_digest=metadata.digest,
            latency_ms=round((time.perf_counter() - started) * 1_000, 3),
        )


def _embedding_dimensions(model_info: dict[str, object]) -> int | None:
    """Read Ollama's architecture-specific `*.embedding_length` metadata."""
    candidates = {
        value
        for key, value in model_info.items()
        if key.endswith(".embedding_length")
        and isinstance(value, int)
        and not isinstance(value, bool)
        and 1 <= value <= 65_536
    }
    if not candidates:
        return None
    if len(candidates) != 1:
        raise MalformedProviderResponseError("model reports conflicting embedding dimensions")
    return next(iter(candidates))
