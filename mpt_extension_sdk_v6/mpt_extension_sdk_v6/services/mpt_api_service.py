from collections.abc import Iterable
from typing import Any, Self

from mpt_api_client import RQLQuery
from mpt_api_client.models import Model
from mpt_api_client.resources.accounts.buyers import Buyer
from mpt_api_client.resources.accounts.licensees import Licensee
from mpt_api_client.resources.catalog.price_list_items import PriceListItem
from mpt_api_client.resources.commerce.assets import Asset
from mpt_api_client.resources.commerce.subscriptions import Subscription

from mpt_extension_sdk_v6.models import Agreement, Order, Template
from mpt_extension_sdk_v6.services.api_client_v2.mpt_api_client import AsyncMPTClient
from mpt_extension_sdk_v6.services.client_factory import build_mpt_client


class BaseService:
    """Base service class for all services."""

    _batch_size = 100

    def __init__(self, client: AsyncMPTClient) -> None:
        """Initialize service with an MPT client."""
        self._client = client

    async def _iterate_all(self, collection: Any, batch_size: int = 100) -> list[Model]:
        """Collect all resources from an iterable collection query."""
        return [item async for item in collection.iterate(batch_size=batch_size)]


class OrdersService(BaseService):
    """Orders service wrapper around the MPT client."""

    async def complete(self, order_id: str, template: Any, **kwargs: Any) -> Order:
        """Complete an order with a template payload."""
        return Order.from_payload(
            await self._client.commerce.orders.complete(order_id, {"template": template, **kwargs})
        )

    async def create_asset(self, order_id: str, asset: Any) -> Asset:
        """Create an asset inside an order."""
        return Asset.from_payload(await self._client.commerce.orders.assets(order_id).create(asset))

    async def fail(self, order_id: str, status_notes: dict, **kwargs: dict) -> None:
        """Fail an order with status notes."""
        kwargs["statusNotes"] = status_notes
        await self._client.commerce.orders.fail(order_id, kwargs)

    async def get_asset_by_external_id(self, order_id: str, asset_external_id: str) -> Asset | None:
        """Fetch the first order asset matching the vendor external ID."""
        query = RQLQuery(externalIds__vendor=asset_external_id)
        assets = (
            await self._client.commerce.orders.assets(order_id).filter(query).fetch_page(limit=1)
        )
        return Asset.model_validate(assets[0], from_attributes=True) if assets else None

    async def get_by_id(self, order_id: str) -> Order:
        """Fetch an order from Marketplace API."""
        return Order.from_payload(
            await self._client.commerce.orders.get(
                order_id,
                select=[
                    "agreement",
                    "assets",
                    "authorization",
                    "externalIds",
                    "lines",
                    "parameters",
                    "product",
                    "seller",
                    "subscriptions",
                    "template",
                ],
            )
        )

    async def get_rendered_template(self, order_id: str) -> str:
        """Fetch the rendered template content for an order."""
        return await self._client.commerce.orders.template(order_id)

    async def query(self, order_id: str, **kwargs: Any) -> Order:
        """Switch an order to query with additional payload."""
        return Order.from_payload(await self._client.commerce.orders.query(order_id, kwargs))

    async def set_processing_template(self, order_id: str, template: Any) -> Order:
        """Update the order template while the order is processing."""
        return await self.update(order_id, template=template)

    async def update(self, order_id: str, **kwargs: Any) -> Order:
        """Update an order."""
        return Order.from_payload(await self._client.commerce.orders.update(order_id, kwargs))

    async def update_asset(self, order_id: str, asset_id: str, **kwargs: Any) -> Asset:
        """Update an asset inside an order."""
        return await self._client.commerce.orders.assets(order_id).update(asset_id, kwargs)

    async def create_subscription(self, order_id: str, subscription: Any) -> Subscription:
        """Create a subscription inside an order."""
        return await self._client.commerce.orders.subscriptions(order_id).create(subscription)

    async def update_subscription(
        self, order_id: str, subscription_id: str, **kwargs: Any
    ) -> Subscription:
        """Update a subscription inside an order."""
        return await self._client.commerce.orders.subscriptions(order_id).update(
            subscription_id, kwargs
        )

    async def get_subscription_by_external_id(
        self, order_id: str, subscription_external_id: str
    ) -> Subscription | None:
        """Fetch the first order subscription matching the vendor external ID."""
        query = RQLQuery(externalIds__vendor=subscription_external_id)
        subscriptions = await (
            self._client.commerce.orders.subscriptions(order_id).filter(query).fetch_page(limit=1)
        )
        return (
            Subscription.model_validate(subscriptions[0], from_attributes=True)
            if subscriptions
            else None
        )


class AgreementsService(BaseService):
    """Agreements service wrapper around the MPT client."""

    async def get_by_id(self, agreement_id: str) -> Agreement:
        """Fetch an agreement from Marketplace API."""
        agreement = await self._client.commerce.agreements.get(
            agreement_id,
            select=[
                "seller",
                "buyer",
                "listing",
                "product",
                "subscriptions",
                "assets",
                "lines",
                "parameters",
            ],
        )
        return Agreement.model_validate(agreement, from_attributes=True)

    async def update(self, agreement_id: str, **kwargs: Any) -> Agreement:
        """Update an agreement."""
        return Agreement.model_validate(
            await self._client.commerce.agreements.update(agreement_id, kwargs),
            from_attributes=True,
        )

    async def get_by_external_id_values(
        self, external_id: str, display_values: Iterable[str]
    ) -> list[Agreement]:
        """Fetch agreements matching a parameter external ID and display values."""
        nested_query = (
            RQLQuery(externalId=external_id) & RQLQuery().displayValue.in_(list(display_values))
        ).any("parameters.fulfillment")

        return [
            item
            async for item in self._client.commerce.agreements
            .filter(nested_query)
            .select(
                "lines",
                "parameters",
                "subscriptions",
                "product",
                "listing",
            )
            .iterate(batch_size=self._batch_size)
        ]

    async def get_by_customer_deployments(
        self, deployment_id_parameter: str, deployment_ids: Iterable[str]
    ) -> list[Agreement]:
        """Fetch agreements matching any of the provided customer deployments."""
        nested_query = (
            RQLQuery(externalId=deployment_id_parameter)
            & RQLQuery().displayValue.in_(list(deployment_ids))
        ).any("parameters.fulfillment")
        return [
            item
            async for item in self._client.commerce.agreements
            .filter(nested_query)
            .select(
                "lines",
                "parameters",
                "subscriptions",
                "subscriptions.parameters",
                "assets",
                "product",
                "listing",
            )
            .iterate(batch_size=self._batch_size)
        ]


class AccountsService(BaseService):
    """Accounts service wrapper around the MPT client."""

    async def get_licensee(self, licensee_id: str) -> Licensee:
        """Fetch a licensee by ID."""
        return await self._client.accounts.licensees.get(licensee_id)

    async def get_buyer(self, buyer_id: str) -> Buyer:
        """Fetch a buyer by ID."""
        return await self._client.accounts.buyers.get(buyer_id)


class AssetsService(BaseService):
    """Assets service wrapper around the MPT client."""

    async def create(self, asset: Any) -> Asset:
        """Create an asset."""
        return await self._client.commerce.assets.create(asset)

    async def update(self, asset_id: str, **kwargs: Any) -> Asset:
        """Update an asset."""
        return await self._client.commerce.assets.update(asset_id, kwargs)

    async def get_by_id(self, asset_id: str) -> Asset:
        """Fetch an asset by ID."""
        return await self._client.commerce.assets.get(asset_id)

    async def get_agreement_asset_by_external_id(
        self, agreement_id: str, asset_external_id: str
    ) -> Asset | None:
        """Fetch the first active agreement asset matching the vendor external ID."""
        query = (
            RQLQuery(externalIds__vendor=asset_external_id)
            & RQLQuery(agreement__id=agreement_id)
            & RQLQuery(status="Active")
        )
        assets = await (
            self._client.commerce.assets.filter(query).select("agreement.id").fetch_page(limit=1)
        )
        return Asset.model_validate(assets[0], from_attributes=True) if assets else None


class SubscriptionsService(BaseService):
    """Subscriptions service wrapper around the MPT client."""

    async def create(self, subscription: Any) -> Subscription:
        """Create an agreement subscription."""
        return await self._client.commerce.subscriptions.create(subscription)

    async def update(self, subscription_id: str, **kwargs: Any) -> Subscription:
        """Update an agreement subscription."""
        return await self._client.commerce.subscriptions.update(subscription_id, kwargs)

    async def get_by_id(self, subscription_id: str) -> Subscription:
        """Fetch an agreement subscription by ID."""
        return await self._client.commerce.subscriptions.get(subscription_id)

    async def get_agreement_subscription_by_external_id(
        self, agreement_id: str, subscription_external_id: str
    ) -> Subscription | None:
        """Fetch the first agreement subscription matching the vendor external ID."""
        query = (
            RQLQuery(externalIds__vendor=subscription_external_id)
            & RQLQuery(agreement__id=agreement_id)
            & RQLQuery().status.in_(["Active", "Updating"])
        )
        subscription = await (
            self._client.commerce.subscriptions
            .filter(query)
            .select("agreement.id")
            .fetch_page(limit=1)
        )
        return (
            Subscription.model_validate(subscription[0], from_attributes=True)
            if subscription
            else None
        )

    async def terminate(self, subscription_id: str, reason: str) -> Subscription:
        """Terminate a subscription with the provided reason."""
        return await self._client.commerce.subscriptions.terminate(
            subscription_id, {"description": reason}
        )


class TemplateService(BaseService):
    """Template service wrapper around the MPT client."""

    async def get_template(
        self, product_id: str, status: str, name: str | None = None
    ) -> Template | None:
        """Fetch the named template for a status or fall back to the default."""
        type_filter = RQLQuery().type.eq(f"Order{status}")
        default_filter = RQLQuery(default=True)
        template_filter = type_filter & default_filter

        if name:
            template_filter = type_filter & (default_filter | RQLQuery(name=name))

        templates = await (
            self._client.catalog.products
            .templates(product_id)
            .filter(template_filter)
            .order_by("default")
            .fetch_page(limit=1)
        )

        return Template.model_validate(templates[0]) if templates else None

    async def get_by_name(self, product_id: str, template_name: str) -> Template | None:
        """Fetch a product template by its name."""
        templates = (
            await self._client.catalog.products
            .templates(product_id)
            .filter(RQLQuery(name=template_name))
            .fetch_page(limit=1)
        )
        return Template.model_validate(templates[0], from_attributes=True) if templates else None

    async def get_asset_template_by_name(
        self,
        product_id: str,
        template_name: str,
    ) -> Model | None:
        """Fetch an asset template by its name."""
        query = RQLQuery(type="Asset") & RQLQuery(name=template_name)
        templates = (
            await self._client.catalog.products
            .templates(product_id)
            .filter(query)
            .fetch_page(limit=1)
        )
        return Template.model_validate(templates[0], from_attributes=True) if templates else None


class CatalogService(BaseService):
    """Catalog service wrapper around the MPT client."""

    async def get_product_items_by_skus(self, product_id: str, skus: Iterable[str]) -> list[Model]:
        """Fetch product items matching the provided vendor SKUs."""
        query = RQLQuery(product__id=product_id) & RQLQuery().n("externalIds.vendor").in_(
            list(skus)
        )
        return await self._iterate_all(self._client.catalog.items.filter(query))

    async def get_product_onetime_items_by_ids(
        self, product_id: str, item_ids: Iterable[str]
    ) -> list[Model]:
        """Fetch one-time items by product and item identifiers."""
        query = (
            RQLQuery(product__id=product_id)
            & RQLQuery().id.in_(list(item_ids))
            & RQLQuery().n("terms.period").eq("one-time")
        )
        return await self._iterate_all(self._client.catalog.items.filter(query))

    async def get_product_items_by_period(
        self,
        product_id: str,
        period: str,
        vendor_external_ids: Iterable[str] | None = None,
    ) -> list[Model]:
        """Fetch product items filtered by billing period and optional vendor IDs."""
        query = RQLQuery(product__id=product_id) & RQLQuery().n("terms.period").eq(period)

        if vendor_external_ids:
            query &= RQLQuery().n("externalIds.vendor").in_(list(vendor_external_ids))

        return await self._iterate_all(self._client.catalog.items.filter(query))

    async def get_authorizations_by_currency_and_seller_id(
        self, product_id: str, currency: str, owner_id: str
    ) -> list[Model]:
        """Fetch authorizations by product, currency, and owner."""
        query = (
            RQLQuery(product__id=product_id)
            & RQLQuery(currency=currency)
            & RQLQuery(owner__id=owner_id)
        )
        return await self._iterate_all(self._client.catalog.authorizations.filter(query))

    async def get_gc_price_list_by_currency(self, product_id: str, currency: str) -> list[Model]:
        """Fetch price lists by product and currency."""
        query = RQLQuery(product__id=product_id) & RQLQuery(currency=currency)
        return await self._iterate_all(self._client.catalog.price_lists.filter(query))

    async def get_listings_by_price_list_and_seller_and_authorization(
        self, product_id: str, price_list_id: str, seller_id: str, authorization_id: str
    ) -> list[Model]:
        """Fetch listings by product, price list, seller, and authorization."""
        query = (
            RQLQuery(product__id=product_id)
            & RQLQuery(priceList__id=price_list_id)
            & RQLQuery(seller__id=seller_id)
            & RQLQuery(authorization__id=authorization_id)
        )
        return await self._iterate_all(self._client.catalog.listings.filter(query))

    async def get_item_prices_by_pricelist_id(
        self, price_list_id: str, item_ids: Iterable[str]
    ) -> list[PriceListItem]:
        """Fetch price list items by the item identifiers."""
        query = RQLQuery(item__id__in=list(item_ids))
        return await self._iterate_all(
            self._client.catalog.price_lists.items(price_list_id).filter(query)
        )

    async def create_listing(self, listing: Any) -> Model:
        """Create a listing."""
        return await self._client.catalog.listings.create(listing)

    async def get_listing_by_id(self, listing_id: str) -> Model:
        """Fetch a listing by ID."""
        return await self._client.catalog.listings.get(listing_id)


class NotificationsService(BaseService):
    """Notifications service wrapper around the MPT client."""

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
            item
            async for item in self._client.notifications
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


class TasksService(BaseService):
    """Task lifecycle service wrapper authenticated with the SDK runtime key."""

    async def get_all(self):
        """Fetch all tasks."""
        return await self._iterate_all(self._client.system.tasks)

    async def complete(self, task_id: str) -> None:
        """Signal the platform that a task has been processed successfully.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.complete(task_id, {})

    async def fail(self, task_id: str) -> None:
        """Signal the platform that a task has failed.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.fail(task_id)

    async def reschedule(self, task_id: str) -> None:
        """Signal the platform that a task must be retried later.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.reschedule_task(task_id)

    async def start(self, task_id: str) -> None:
        """Signal the platform that processing of a task has started.

        Args:
            task_id: Unique identifier of the platform task.
        """
        await self._client.system.tasks.execute(task_id)

    async def progress(self, task_id: str, progress: float) -> None:
        """Update the progress of a task."""
        await self._client.system.tasks.update(task_id, {"progress": progress})


class MPTAPIService:
    """API service for Marketplace operations."""

    def __init__(self, client: AsyncMPTClient) -> None:
        """Initialize API service."""
        self.client = client
        self.accounts = AccountsService(client)
        self.agreements = AgreementsService(client)
        self.assets = AssetsService(client)
        self.catalog = CatalogService(client)
        self.notifications = NotificationsService(client)
        self.orders = OrdersService(client)
        self.subscriptions = SubscriptionsService(client)
        self.tasks = TasksService(client)
        self.templates = TemplateService(client)

    @classmethod
    def from_config(cls, base_url: str, api_token: str) -> Self:
        """Create the service from connection settings."""
        return cls(build_mpt_client(base_url=base_url, api_token=api_token))
