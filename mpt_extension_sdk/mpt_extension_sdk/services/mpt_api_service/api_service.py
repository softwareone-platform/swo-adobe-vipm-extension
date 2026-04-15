from typing import Self

from mpt_extension_sdk.services.api_client_v2.mpt_api_client import AsyncMPTClient
from mpt_extension_sdk.services.mpt_api_service.agreement import AgreementService
from mpt_extension_sdk.services.mpt_api_service.asset import AssetService
from mpt_extension_sdk.services.mpt_api_service.client_factory import build_mpt_client
from mpt_extension_sdk.services.mpt_api_service.notification import NotificationService
from mpt_extension_sdk.services.mpt_api_service.order import OrderService
from mpt_extension_sdk.services.mpt_api_service.product import (
    ProductItemService,
    ProductService,
)
from mpt_extension_sdk.services.mpt_api_service.subscription import SubscriptionService
from mpt_extension_sdk.services.mpt_api_service.task import TaskService
from mpt_extension_sdk.services.mpt_api_service.template import TemplateService


class MPTAPIService:
    """API service for Marketplace operations."""

    def __init__(self, client: AsyncMPTClient) -> None:
        """Initialize API service.

        Args:
            client: Shared MPT API client.
        """
        self.client = client
        self.agreements = AgreementService(client)
        self.assets = AssetService(client)
        self.products = ProductService(client)
        self.product_items = ProductItemService(client)
        self.notifications = NotificationService(client)
        self.orders = OrderService(client)
        self.subscriptions = SubscriptionService(client)
        self.tasks = TaskService(client)
        self.templates = TemplateService(client)

    @classmethod
    def from_config(cls, base_url: str, api_token: str) -> Self:
        """Create the service from connection settings.

        Args:
            base_url: MPT API base URL.
            api_token: MPT API token.
        """
        return cls(build_mpt_client(base_url=base_url, api_token=api_token))
