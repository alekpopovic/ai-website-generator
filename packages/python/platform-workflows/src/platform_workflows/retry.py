"""Reviewed retry policies by activity failure category."""

from dataclasses import replace
from datetime import timedelta
from enum import StrEnum

from temporalio.common import RetryPolicy


class ActivityCategory(StrEnum):
    """Categories with distinct safe retry budgets."""

    CONTROL = "control"
    NETWORK = "network"
    BROWSER = "browser"
    INFERENCE = "inference"
    STORAGE = "storage"
    RENDER = "render"
    VALIDATION = "validation"
    TRAINING = "training"


_POLICIES: dict[ActivityCategory, RetryPolicy] = {
    ActivityCategory.CONTROL: RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2,
        maximum_interval=timedelta(seconds=10),
        maximum_attempts=5,
    ),
    ActivityCategory.NETWORK: RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2,
        maximum_interval=timedelta(minutes=1),
        maximum_attempts=5,
        non_retryable_error_types=["PolicyViolation", "AuthorizationDenied", "InvalidUrl"],
    ),
    ActivityCategory.BROWSER: RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=3,
        non_retryable_error_types=["PolicyViolation", "InvalidArtifact"],
    ),
    ActivityCategory.INFERENCE: RetryPolicy(
        initial_interval=timedelta(seconds=10),
        backoff_coefficient=2,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=3,
        non_retryable_error_types=["InvalidModelOutput", "UnsupportedModel"],
    ),
    ActivityCategory.STORAGE: RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=7,
        non_retryable_error_types=["InvalidObjectKey", "AuthorizationDenied"],
    ),
    ActivityCategory.RENDER: RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=3,
        non_retryable_error_types=["InvalidSiteSpec", "UnknownComponent"],
    ),
    ActivityCategory.VALIDATION: RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=3,
        non_retryable_error_types=["InvalidArtifact"],
    ),
    ActivityCategory.TRAINING: RetryPolicy(
        initial_interval=timedelta(seconds=30),
        backoff_coefficient=2,
        maximum_interval=timedelta(minutes=5),
        maximum_attempts=2,
        non_retryable_error_types=["InvalidDataset", "TrainingNotAuthorized"],
    ),
}


def retry_policy(category: ActivityCategory) -> RetryPolicy:
    """Return an independent policy so callers cannot mutate shared defaults."""
    policy = _POLICIES[category]
    return replace(
        policy,
        non_retryable_error_types=list(policy.non_retryable_error_types or ()),
    )
