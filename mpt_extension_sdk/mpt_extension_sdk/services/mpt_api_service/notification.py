from typing import Any

from mpt_api_client import RQLQuery

from mpt_extension_sdk.services.api_client_v2.mpt_api_client import AsyncMPTClient
from mpt_extension_sdk.services.mpt_api_service.base import BaseService


class NotificationService(BaseService):
    """Notification service."""

    def __init__(self, client: AsyncMPTClient) -> None:
        """Initialize service with an MPT client."""
        super().__init__(client)
        self._webhooks_cache: dict[str, dict[str, Any]] = {}

    def get_webhook(self, webhook_id: str) -> dict[str, Any]:
        """Fetch a webhook using the raw HTTP client until the SDK exposes it."""
        if webhook_id in self._webhooks_cache:
            return self._webhooks_cache[webhook_id]

        response = self._client.http_client.request(
            "get",
            f"/public/v1/notifications/webhooks/{webhook_id}?select=criteria",
        )
        webhook = response.json()
        self._webhooks_cache[webhook_id] = webhook
        return webhook

    async def notify(
        self,
        category_id: str,
        account_id: str,
        buyer_id: str,
        subject: str,
        message_body: str,
        limit: int = 1000,
    ) -> None:
        """Send batched notifications to the contacts subscribed for a buyer."""
        contacts = [
            notification
            async for notification in self._client.notifications
            .accounts(account_id, category_id)
            .filter(RQLQuery.from_string(f"filter(group.buyers.id,{buyer_id})"))
            .select("id", "-email", "-name", "-status", "-user")
            .iterate(batch_size=limit)
        ]
        await self._client.notifications.batches.create({
            "category": {"id": category_id},
            "subject": subject,
            "body": message_body,
            "contacts": contacts,
            "buyer": {"id": buyer_id},
        })
