import logging
from typing import Any

from mpt_extension_sdk_v6.models import Order
from mpt_extension_sdk_v6.services.mpt_api_service.base import BaseService

logger = logging.getLogger(__name__)


class OrderService(BaseService[Order]):
    """Order service."""

    async def get_by_id(self, order_id: str) -> Order:
        """Fetch an order from Marketplace API."""
        order = await self._client.commerce.orders.get(
            order_id,
            select=[
                "agreement",
                "agreement.authorizations",
                "agreement.client",
                "agreement.licensee",
                "agreement.lines",
                "agreement.parameters",
                "assets",
                "authorization",
                "externalIds",
                "lines",
                "lines.asset",
                "lines.subscription",
                "parameters",
                "product",
                "seller",
                "subscriptions",
                "template",
            ],
        )
        logger.debug("Fetched order %s: %s", order_id, order.to_dict())
        return Order.from_payload(order)

    async def complete(self, order_id: str, template: Any, **kwargs: Any) -> None:
        """Complete an order with a template payload."""
        await self._client.commerce.orders.complete(order_id, {"template": template, **kwargs})

    async def update(self, order_id: str, **kwargs: Any) -> None:
        """Update an order."""
        await self._client.commerce.orders.update(order_id, kwargs)

    async def query(self, order_id: str, **kwargs: Any) -> None:
        """Switch an order to query."""
        await self._client.commerce.orders.query(order_id, kwargs)

    async def fail(self, order_id: str, status_notes: dict, **kwargs: Any) -> None:
        """Fail an order with status notes."""
        kwargs["statusNotes"] = status_notes
        await self._client.commerce.orders.fail(order_id, kwargs)
