from mpt_api_client.http import AsyncHTTPClient

from mpt_extension_sdk.services.api_client_v2.system.system_tasks import AsyncTasksService


class AsyncSystem:
    """System service."""

    def __init__(self, http_client: AsyncHTTPClient):
        self.http_client = http_client

    @property
    def tasks(self) -> AsyncTasksService:
        """Tasks service."""
        return AsyncTasksService(http_client=self.http_client)
