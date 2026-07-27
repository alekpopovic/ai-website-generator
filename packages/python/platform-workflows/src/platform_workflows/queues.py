"""Stable task queue names shared by dispatchers and workers."""

from enum import StrEnum


class TaskQueue(StrEnum):
    """Resource and trust-boundary-specific Temporal task queues."""

    CONTROL = "control"
    CRAWL = "crawl"
    BROWSER = "browser"
    AI_ANALYSIS = "ai-analysis"
    EMBEDDING = "embedding"
    GENERATION = "generation"
    RENDER = "render"
    VALIDATION = "validation"
    TRAINING = "training"
