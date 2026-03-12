from mpt_api_client.http import AsyncService
from mpt_api_client.http.mixins import AsyncCollectionMixin, AsyncGetMixin, AsyncUpdateMixin
from mpt_api_client.models import Model, ResourceData


class Task(Model):
    """Task model."""


class TasksServiceConfig:
    """Tasks service config."""

    _endpoint = "/public/v1/system/tasks"
    _model_class = Task
    _collection_key = "data"


class AsyncTasksService(
    AsyncCollectionMixin[Task],
    AsyncGetMixin[Task],
    AsyncUpdateMixin[Task],
    AsyncService[Task],
    TasksServiceConfig,
):
    """Task service."""

    async def complete(self, resource_id: str, resource_data: ResourceData) -> Task:
        """Complete the task."""
        return await self._resource_action(resource_id, "POST", "complete", resource_data)

    async def fail(self, resource_id: str) -> Task:
        """Fail the task."""
        return await self._resource_action(resource_id, "POST", "fail")

    async def reschedule_task(self, resource_id: str) -> Task:
        """Reschedule the task."""
        return await self._resource_action(resource_id, "POST", "reschedule")

    async def execute(self, resource_id: str) -> Task:
        """Start the task."""
        return await self._resource_action(resource_id, "POST", "execute")
