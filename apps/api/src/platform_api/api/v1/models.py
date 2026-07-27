"""Authenticated configured-model readiness and administrator workflow actions."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Request, status
from platform_clients.llm.ollama import LLMGatewayError
from platform_workflows.commands import ModelWarmupInput
from platform_workflows.dispatcher import DuplicateWorkflowDispatchError
from platform_workflows.identifiers import ModelRole
from pydantic import BaseModel, ConfigDict, Field
from temporalio.exceptions import WorkflowAlreadyStartedError

from platform_api.auth.dependencies import AdministratorUserDependency, CurrentUserDependency
from platform_api.dependencies import LLMGatewayDependency, WorkflowDispatcherDependency
from platform_api.errors import ApiError, DependencyUnavailableError, problem_responses
from platform_api.models.common import ApiResponse, ResponseMeta

router = APIRouter()


class ModelReadinessItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ModelRole
    model: str
    installed: bool
    capable: bool
    required_capability: str
    digest: str | None
    capabilities: tuple[str, ...]


class ModelReadinessData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool
    models: tuple[ModelReadinessItem, ...]


class ModelWarmupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ModelWarmupAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str
    workflow_id: str
    model_role: ModelRole


@router.get(
    "/models/readiness",
    response_model=ApiResponse[ModelReadinessData],
    operation_id="getConfiguredModelReadiness",
    responses=problem_responses(401, 503),
)
async def configured_model_readiness(
    request: Request,
    user: CurrentUserDependency,
    gateway: LLMGatewayDependency,
) -> ApiResponse[ModelReadinessData]:
    """Report installation and capability state without loading or pulling models."""
    del user
    try:
        readiness = await gateway.readiness()
    except LLMGatewayError as error:
        raise DependencyUnavailableError("local inference") from error
    models = tuple(
        ModelReadinessItem(
            role=ModelRole(item.role.value),
            model=item.model,
            installed=item.installed,
            capable=item.capable,
            required_capability=item.required_capability,
            digest=item.digest,
            capabilities=tuple(sorted(item.capabilities)),
        )
        for item in readiness
    )
    return ApiResponse(
        data=ModelReadinessData(
            ready=all(model.installed and model.capable for model in models), models=models
        ),
        meta=ResponseMeta(request_id=str(request.state.request_id)),
    )


@router.post(
    "/admin/models/{model_role}/warm-up",
    response_model=ApiResponse[ModelWarmupAccepted],
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="warmUpConfiguredModel",
    responses=problem_responses(401, 403, 409, 422, 503),
)
async def warm_up_configured_model(
    model_role: ModelRole,
    payload: ModelWarmupRequest,
    request: Request,
    administrator: AdministratorUserDependency,
    dispatcher: WorkflowDispatcherDependency,
) -> ApiResponse[ModelWarmupAccepted]:
    """Queue worker-side model loading; this request process never invokes inference."""
    job_id = uuid4()
    command = ModelWarmupInput(
        job_id=str(job_id),
        requested_by_user_id=str(administrator.id),
        idempotency_key=payload.idempotency_key,
        model_role=model_role,
    )
    try:
        dispatched = await dispatcher.dispatch_model_warmup(command)
    except (DuplicateWorkflowDispatchError, WorkflowAlreadyStartedError) as error:
        raise ApiError(409, "duplicate_workflow", "This warm-up request already exists.") from error
    return ApiResponse(
        data=ModelWarmupAccepted(
            job_id=str(job_id),
            workflow_id=dispatched.workflow_id,
            model_role=model_role,
        ),
        meta=ResponseMeta(request_id=str(request.state.request_id)),
    )
