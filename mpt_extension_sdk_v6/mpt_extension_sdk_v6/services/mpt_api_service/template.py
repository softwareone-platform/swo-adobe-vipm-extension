from mpt_api_client import RQLQuery

from mpt_extension_sdk_v6.models import Template
from mpt_extension_sdk_v6.services.mpt_api_service.base import BaseService


class TemplateService(BaseService[Template]):
    """Template service."""

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

        return Template.from_payload(templates[0]) if templates else None

    async def get_asset_template_by_name(
        self, product_id: str, template_name: str
    ) -> Template | None:
        """Fetch an asset template by its name."""
        query = RQLQuery(type="Asset") & RQLQuery(name=template_name)
        templates = (
            await self._client.catalog.products
            .templates(product_id)
            .filter(query)
            .fetch_page(limit=1)
        )
        return Template.from_payload(templates[0]) if templates else None

    async def get_order_querying_template(self, product_id: str) -> Template | None:
        """Fetch the order querying template."""
        query = RQLQuery(type="OrderQuerying") & RQLQuery(default=True)
        templates = (
            await self._client.catalog.products
            .templates(product_id)
            .filter(query)
            .fetch_page(limit=1)
        )
        return Template.from_payload(templates[0]) if templates else None

    async def set_order_template(self, order_id: str, template: Template) -> None:
        """Update the order template."""
        payload = {"template": template.to_dict()}
        await self._client.commerce.orders.update(order_id, payload)
