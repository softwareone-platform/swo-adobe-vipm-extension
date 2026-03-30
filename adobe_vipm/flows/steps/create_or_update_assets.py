from typing import override

from mpt_extension_sdk.errors.step import SkipStepError
from mpt_extension_sdk.models import ParameterBag
from mpt_extension_sdk.pipeline import BaseStep, refresh_order

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.flows.constants import TEMPLATE_ASSET_DEFAULT, Param
from adobe_vipm.flows.context import AdobeOrderContext


class CreateOrUpdateAssets(BaseStep, AdobeClientMixin):
    """Create or update Marketplace assets from Adobe fulfillment data."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if not ctx.adobe_new_order:
            raise SkipStepError("No new Adobe order, skipping asset creation.")

    @override
    @refresh_order
    async def process(self, ctx: AdobeOrderContext) -> None:
        # REVIEW
        one_time_items = await ctx.mpt_api_service.product_items.get_product_one_time_items_by_ids(
            ctx.order.product_id, [line.product_item.id for line in ctx.order.lines]
        )
        one_time_skus = [item.external_ids.vendor for item in one_time_items if item.external_ids]
        template = await ctx.mpt_api_service.templates.get_asset_template_by_name(
            ctx.order.product_id, TEMPLATE_ASSET_DEFAULT
        )
        for adobe_line in filter(
            lambda line: line.partial_sku in one_time_skus, ctx.adobe_new_order.line_items
        ):
            adobe_subscription = self.adobe_client.get_subscription(
                ctx.order.authorization_id, ctx.adobe_customer_id, adobe_line.subscription_id
            )
            if not adobe_subscription.is_processed:
                ctx.logger.info(
                    "Subscription %s for customer %s is in status %s, skip it",
                    adobe_subscription.id,
                    ctx.adobe_customer_id,
                    adobe_subscription.status,
                )
                continue

            order_line = ctx.order.get_line_by_sku(adobe_line.offer_id)
            if not order_line:
                ctx.logger.warning(
                    "No order line found for offer %s, skipping asset creation.",
                    adobe_line.offer_id,
                )
                continue

            payload = {
                "name": f"Asset for {order_line.product_item.name}",
                "parameters": {
                    "fulfillment": [
                        {
                            "externalId": Param.ADOBE_SKU.value,
                            "value": adobe_line.offer_id,
                        },
                        {
                            "externalId": Param.CURRENT_QUANTITY.value,
                            "value": str(adobe_subscription.current_quantity),
                        },
                        {
                            "externalId": Param.USED_QUANTITY.value,
                            "value": str(adobe_subscription.used_quantity),
                        },
                    ]
                },
                "externalIds": {
                    "vendor": adobe_line.subscription_id,
                },
                "lines": [
                    {
                        "id": order_line.id,
                    },
                ],
                "template": {"id": template.id, "name": template.name} if template else None,
            }
            if order_line.asset:
                parameters = ParameterBag.from_payload(payload["parameters"])
                await ctx.mpt_api_service.assets.update(
                    order_line.asset.id,
                    parameters=parameters.to_dict(),
                )
                ctx.logger.info("Asset (%s) updated.", order_line.asset.id)
            else:
                new_asset = await ctx.mpt_api_service.assets.create_order_asset(
                    ctx.order_id, **payload
                )
                ctx.logger.info("Asset (%s) has been created", new_asset.id)
