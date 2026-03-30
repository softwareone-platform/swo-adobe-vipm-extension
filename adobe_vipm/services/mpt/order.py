import logging
from typing import override

from mpt_extension_sdk.models import Order
from mpt_extension_sdk.services.mpt_api_service.order import OrderService

logger = logging.getLogger(__name__)


class ExtOrderService(OrderService):
    """Ext order service."""

    @override
    async def get_by_id(self, order_id: str) -> Order:
        logger.debug("Using new ext order service")
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
