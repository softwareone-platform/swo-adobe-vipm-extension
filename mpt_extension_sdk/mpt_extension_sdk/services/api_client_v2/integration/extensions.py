from mpt_api_client.http import AsyncService
from mpt_api_client.models import Model

from mpt_extension_sdk.services.api_client_v2.integration.extensions_installations import (
    AsyncExtensionsInstallationsService,
)


class Extensions(Model):
    """Extensions model."""


class ExtensionsServiceConfig:
    """Extensions service config."""

    _endpoint = "/public/v1/integration/extensions"
    _model_class = Extensions
    _collection_key = "data"


class AsyncExtensionsService(AsyncService[Extensions]):
    """Extensions service."""

    def installations(self, extension_id: str) -> AsyncExtensionsInstallationsService:
        """Get the installations service for the given extension_id.

        Args:
            extension_id: Extension ID.

        Returns:
            Extension Installation service.
        """
        return AsyncExtensionsInstallationsService(
            http_client=self.http_client, endpoint_params={"extension_id": extension_id}
        )
