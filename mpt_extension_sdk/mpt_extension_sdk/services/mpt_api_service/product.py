from mpt_api_client import RQLQuery

from mpt_extension_sdk.models import Product, ProductItem
from mpt_extension_sdk.services.mpt_api_service.base import BaseService


class ProductService(BaseService[Product]):
    """Product service."""


class ProductItemService(BaseService[ProductItem]):
    """Product item service."""

    async def get_product_one_time_items_by_ids(
        self, product_id: str, item_ids: list[str]
    ) -> list[ProductItem]:
        """Fetch one-time items by product and item identifiers."""
        query = (
            RQLQuery(product__id=product_id)
            & RQLQuery().id.in_(item_ids)
            & RQLQuery().n("terms.period").eq("one-time")
        )
        return await self._iterate_all(self._client.catalog.items.filter(query), ProductItem)
