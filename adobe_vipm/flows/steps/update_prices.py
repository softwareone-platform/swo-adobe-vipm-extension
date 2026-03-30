from typing import override

from mpt_extension_sdk.errors.step import SkipStepError
from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.context import AdobeOrderContext


class UpdatePrices(BaseStep):
    """Update MPT pricing data from Adobe responses."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if ctx.adobe_order_id or not ctx.adobe_preview_order:
            raise SkipStepError("New Adobe Order or no preview order, skipping price update.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        prices = ctx.adobe_preview_order.prices
        lines_updated = []
        updated_lines = []
        price_by_line_id = {}
        for sku in ctx.adobe_preview_order.skus:
            line = ctx.order.get_line_by_sku(sku)
            unit_price = prices.get(sku)
            price_by_line_id[line.id] = line.price.model_copy(update={"unit_pp": unit_price})
            lines_updated.append((line.id, unit_price))

        for line in ctx.order.lines:
            updated_price = price_by_line_id.get(line.id, line.price)
            updated_lines.append(line.model_copy(update={"price": updated_price}).to_dict())

        await ctx.mpt_api_service.orders.update(ctx.order_id, lines=updated_lines)
        ctx.logger.info("Updated order lines: %s", lines_updated)
