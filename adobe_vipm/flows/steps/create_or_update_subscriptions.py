from typing import override

from mpt_extension_sdk.errors.step import SkipStepError
from mpt_extension_sdk.pipeline import BaseStep, refresh_order

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.flows.constants import TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE, Param
from adobe_vipm.flows.context import AdobeOrderContext


class CreateOrUpdateSubscriptions(BaseStep, AdobeClientMixin):
    """Create or update Marketplace subscriptions from Adobe fulfillment data."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if not ctx.adobe_new_order:
            raise SkipStepError("No new Adobe order, skipping subscription creation.")

    @override
    @refresh_order
    async def process(self, ctx: AdobeOrderContext) -> None:
        one_time_items = await ctx.mpt_api_service.product_items.get_product_one_time_items_by_ids(
            ctx.order.product_id,
            [line.product_item.id for line in ctx.order.lines],
        )
        one_time_skus = [item.external_ids.vendor for item in one_time_items if item.external_ids]
        template = await ctx.mpt_api_service.templates.get_asset_template_by_name(
            ctx.order.product_id, TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE
        )
        for adobe_line in filter(
            lambda line: line.partial_sku not in one_time_skus, ctx.adobe_new_order.line_items
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
            if order_line and order_line.subscription:
                updated_parameters = order_line.subscription.parameters.with_fulfillment_value(
                    Param.ADOBE_SKU, adobe_line.offer_id
                )
                adobe_sku_param = updated_parameters.get_fulfillment_parameter(Param.ADOBE_SKU)
                await ctx.mpt_api_service.subscriptions.update_subscription(
                    order_line.subscription.id, parameters=adobe_sku_param.to_dict()
                )

            else:
                await ctx.mpt_api_service.subscriptions.create_order_subscription(
                    ctx.order_id,
                    name=f"Subscription for {order_line.product_item.name}",
                    parameters={
                        Param.PHASE_FULFILLMENT: [
                            {"externalId": Param.ADOBE_SKU, "value": adobe_line.offer_id},
                        ]
                    },
                    externalIds={"vendor": adobe_line.subscription_id},
                    template={"id": template.id, "name": template.name} if template else None,
                    lines=[{"id": order_line.id}],
                )
