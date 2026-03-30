from mpt_extension_sdk.models.base import BaseModel
from mpt_extension_sdk.services.mpt_api_service.base import BaseService


class PriceList(BaseModel):
    """Price list model."""

    id: str


class PriceListService(BaseService):
    """Price list service."""

    async def get_by_id(self, price_list_id: str) -> PriceList:
        """Fetch a price list by ID."""
        return PriceList.from_payload(await self._client.catalog.price_lists.get(price_list_id))
