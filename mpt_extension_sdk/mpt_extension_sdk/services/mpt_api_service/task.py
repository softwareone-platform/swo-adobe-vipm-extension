from mpt_extension_sdk.services.mpt_api_service.base import BaseService


class TaskService(BaseService):
    """Task service."""

    async def complete(self, task_id: str) -> None:
        """Signal the platform that a task has been processed successfully.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.complete(task_id, {})

    async def fail(self, task_id: str) -> None:
        """Signal the platform that a task has failed.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.fail(task_id)

    async def progress(self, task_id: str, progress: float) -> None:
        """Update the progress of a task."""
        await self._client.system.tasks.update(task_id, {"progress": progress})

    async def reschedule(self, task_id: str) -> None:
        """Signal the platform that a task must be retried later.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.reschedule_task(task_id)

    async def start(self, task_id: str) -> None:
        """Signal the platform that processing of a task has started.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.execute(task_id)
