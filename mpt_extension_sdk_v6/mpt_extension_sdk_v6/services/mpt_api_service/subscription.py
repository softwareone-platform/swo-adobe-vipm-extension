from typing import Any

from mpt_extension_sdk_v6.models import Subscription
from mpt_extension_sdk_v6.services.mpt_api_service.base import BaseService


class SubscriptionService(BaseService[Subscription]):
    """Subscription service."""

    async def create(self, subscription: Any) -> Subscription:
        """Create a subscription."""
        return Subscription.from_payload(
            await self._client.commerce.subscriptions.create(subscription)
        )

    async def create_order_subscription(
        self, order_id: str, **kwargs: dict[str, Any]
    ) -> Subscription:
        """Create a subscription inside an order."""
        return Subscription.from_payload(
            await self._client.commerce.orders.subscriptions(order_id).create(kwargs)
        )

    async def get_by_id(self, subscription_id: str) -> Subscription:
        """Fetch a subscription by ID."""
        return Subscription.from_payload(
            await self._client.commerce.subscriptions.get(subscription_id)
        )

    async def update_subscription(self, subscription_id: str, **kwargs: dict[str, Any]) -> None:
        """Update a subscription."""
        await self._client.commerce.subscriptions.update(subscription_id, kwargs)
