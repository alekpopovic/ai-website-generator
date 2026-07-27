"""AI activity tests use deterministic local gateway behavior."""

from uuid import uuid4

import pytest
from platform_ai_worker.activities import ModelActivities
from platform_clients.llm.fake import FakeLLMGateway
from platform_clients.llm.models import ModelRole as GatewayModelRole
from platform_workflows.commands import ModelWarmupInput
from platform_workflows.identifiers import ModelRole
from temporalio.testing import ActivityEnvironment


@pytest.mark.anyio
async def test_warmup_activity_invokes_only_the_configured_fake_model() -> None:
    gateway = FakeLLMGateway()
    activities = ModelActivities(gateway)
    command = ModelWarmupInput(
        job_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        idempotency_key="activity-warmup",
        model_role=ModelRole.EMBEDDING,
    )

    result = await ActivityEnvironment().run(activities.warm_up_model, command)

    assert result.record_id == command.job_id
    assert gateway.calls == [("warm-up", GatewayModelRole.EMBEDDING)]
