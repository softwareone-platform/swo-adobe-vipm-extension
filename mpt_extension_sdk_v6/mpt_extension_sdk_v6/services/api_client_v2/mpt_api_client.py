from mpt_api_client.mpt_client import AsyncMPTClient as BaseAsyncMPTClient

from mpt_extension_sdk_v6.services.api_client_v2.integration.integration import (
    AsyncIntegration,
)
from mpt_extension_sdk_v6.services.api_client_v2.system.system import AsyncSystem


class AsyncMPTClient(BaseAsyncMPTClient):
    """MPT client wrapper to implement endpoints that will be moved there."""

    @property
    def integration(self) -> AsyncIntegration:
        """Integration service."""
        return AsyncIntegration(http_client=self.http_client)

    @property
    def system(self) -> AsyncSystem:
        """System service."""
        return AsyncSystem(http_client=self.http_client)
