"""Deterministic workflow identifiers and duplicate-run policy."""

import re
from enum import StrEnum
from uuid import UUID

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy


class WorkflowKind(StrEnum):
    """Stable workflow type vocabulary used in IDs and dispatch requests."""

    SCAN_CAMPAIGN = "scan-campaign"
    DATASET_BUILD = "dataset-build"
    SITE_GENERATION = "site-generation"
    TRAINING_RUN = "training-run"


WORKFLOW_ID_REUSE_POLICY = WorkflowIDReusePolicy.REJECT_DUPLICATE
WORKFLOW_ID_CONFLICT_POLICY = WorkflowIDConflictPolicy.FAIL
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def workflow_id(kind: WorkflowKind, resource_id: str | UUID, idempotency_key: str) -> str:
    """Build an owner-independent ID that rejects duplicate logical submissions."""
    resource_uuid = UUID(str(resource_id))
    if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise ValueError("idempotency_key must be 1-128 URL-safe identifier characters")
    return f"aiwg:{kind.value}:{resource_uuid}:{idempotency_key}"
