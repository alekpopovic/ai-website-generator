"""Bounded AI worker activities; model loading never runs in FastAPI."""

import logging
from typing import Protocol

from platform_clients.llm.models import ModelRole as GatewayModelRole
from platform_clients.llm.protocols import LLMGateway
from platform_workflows.commands import ActivityResult, ModelWarmupInput, ScanPageInput
from platform_workflows.heartbeat import ActivityHeartbeat
from temporalio import activity

logger = logging.getLogger(__name__)


class ScanPageAnalyzer(Protocol):
    async def analyze_and_persist(self, command: ScanPageInput) -> str: ...


class ModelActivities:
    def __init__(self, gateway: LLMGateway, scan_analyzer: ScanPageAnalyzer | None = None) -> None:
        self._gateway = gateway
        self._scan_analyzer = scan_analyzer

    @activity.defn(name="warm-up-model")
    async def warm_up_model(self, command: ModelWarmupInput) -> ActivityResult:
        """Load one configured installed model and emit only safe operational metadata."""
        result = await ActivityHeartbeat().while_running(
            self._gateway.warm_up(GatewayModelRole(command.model_role.value)),
            stage="warm-up-model",
        )
        logger.info(
            "model_warmup_completed model=%s digest=%s latency_ms=%s",
            result.model,
            result.model_digest,
            result.latency_ms,
        )
        return ActivityResult(record_id=command.job_id)

    @activity.defn(name="analyze-and-persist-page-profile")
    async def analyze_and_persist_page_profile(self, command: ScanPageInput) -> ActivityResult:
        if self._scan_analyzer is None:
            raise RuntimeError("scan page analyzer is not configured")
        heartbeat = ActivityHeartbeat()
        result = await heartbeat.while_running(
            self._scan_analyzer.analyze_and_persist(command), stage="analyze-page"
        )
        return ActivityResult(record_id=result)
