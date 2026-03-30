from collections import Counter
from typing import override

from mpt_extension_sdk.errors.step import StopStepError
from mpt_extension_sdk.models import OrderLine, Subscription, SubscriptionLine
from mpt_extension_sdk.pipeline import (
    BaseStep,
    OrderContext,
    OrderStatusAction,
    OrderStatusActionType,
)

from adobe_vipm.flows.constants import ERR_DUPLICATED_ITEMS, ERR_EXISTING_ITEMS


class ValidateDuplicateLines(BaseStep):
    """Validate duplicate order lines before fulfillment."""

    @override
    async def process(self, ctx: OrderContext) -> None:
        duplicates = self._get_duplicates(ctx.order.lines)
        if duplicates:
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.FAIL,
                message="Duplicate items found",
                status_notes=ERR_DUPLICATED_ITEMS.to_dict(duplicates=",".join(duplicates)),
                parameters=ctx.order.parameters.to_dict(),
            )
            raise StopStepError("Duplicate items found")

        new_order_lines = [line for line in ctx.order.lines if line.old_quantity == 0]
        sub_lines = self._get_subscription_lines(ctx.order.subscriptions)
        duplicates = self._get_duplicates(new_order_lines + sub_lines)
        if duplicates:
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.FAIL,
                message="Duplicate items found",
                status_notes=ERR_EXISTING_ITEMS.to_dict(duplicates=",".join(duplicates)),
                parameters=ctx.order.parameters.to_dict(),
            )
            raise StopStepError("Duplicate items found")

    def _get_duplicates(self, lines: list[OrderLine | SubscriptionLine]) -> list[str]:
        line_ids = [line.product_item.id for line in lines]
        return [line_id for line_id, count in Counter(line_ids).items() if count > 1]

    def _get_subscription_lines(self, subscriptions: list[Subscription]) -> list[SubscriptionLine]:
        sub_lines: list[SubscriptionLine] = []
        for subscription in subscriptions:
            for line in subscription.lines:
                sub_lines.append(line)  # noqa: PERF402
        return sub_lines
