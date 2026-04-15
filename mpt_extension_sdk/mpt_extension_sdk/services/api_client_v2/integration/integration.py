from mpt_api_client.http import AsyncHTTPClient

from mpt_extension_sdk.services.api_client_v2.integration.extensions import (
    AsyncExtensionsService,
)


class AsyncIntegration:
    """Integration service."""

    def __init__(self, http_client: AsyncHTTPClient):
        self.http_client = http_client

    @property
    def extensions(self) -> AsyncExtensionsService:
        """Extensions service."""
        return AsyncExtensionsService(http_client=self.http_client)
