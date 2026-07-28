"""Temporal embedding activity with identifier-only input and compact heartbeats."""

from uuid import UUID

from platform_workflows.commands import ActivityResult, EmbeddingIndexInput
from platform_workflows.heartbeat import ActivityHeartbeat
from temporalio import activity

from platform_embedding_worker.runner import EmbeddingIndexer


class EmbeddingActivities:
    def __init__(self, indexer: EmbeddingIndexer) -> None:
        self._indexer = indexer

    @activity.defn(name="index-section-patterns")
    async def index_section_patterns(self, command: EmbeddingIndexInput) -> ActivityResult:
        heartbeat = ActivityHeartbeat()

        async def progress(stage: str, completed: int) -> None:
            heartbeat.report(stage=stage, completed=completed)

        run_id = UUID(command.embedding_run_id)
        await heartbeat.while_running(
            self._indexer.run(run_id, progress), stage="index-section-patterns"
        )
        return ActivityResult(record_id=command.embedding_run_id)
