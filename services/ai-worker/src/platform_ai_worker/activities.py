"""Bounded AI worker activities; model loading never runs in FastAPI."""

import logging

from platform_clients.llm.models import ModelRole as GatewayModelRole
from platform_clients.llm.protocols import LLMGateway
from platform_workflows.commands import ActivityResult, ModelWarmupInput
from platform_workflows.heartbeat import ActivityHeartbeat
from temporalio import activity

logger = logging.getLogger(__name__)


class ModelActivities:
    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

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
