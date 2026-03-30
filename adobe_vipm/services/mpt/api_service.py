from mpt_api_client import AsyncMPTClient
from mpt_extension_sdk.services.mpt_api_service import MPTAPIService

from adobe_vipm.services.mpt.order import ExtOrderService
from adobe_vipm.services.mpt.price_list import PriceListService


class ExtensionMPTAPIService(MPTAPIService):
    """Typed Marketplace service container for this extension."""

    def __init__(self, client: AsyncMPTClient) -> None:
        """Initialize the extension-specific Marketplace services."""
        super().__init__(client)
        self.order = ExtOrderService(client)
        self.price_list = PriceListService(client)
