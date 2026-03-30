from abc import ABC
from typing import override

from mpt_extension_sdk.errors.step import StopStepError
from mpt_extension_sdk.pipeline import BasePipeline, BaseStep, OrderStatusActionType

from adobe_vipm.flows.context import AdobeOrderContext


class AdobeOrderPipeline(BasePipeline, ABC):
    """Base pipeline with Adobe-specific failure handling."""

    @override
    async def on_step_failed(
        self, step: BaseStep, ctx: AdobeOrderContext, error: Exception
    ) -> None:
        await super().on_step_failed(step, ctx, error)
        await self._handle_failure_action(ctx)

    @override
    async def on_step_stopped(
        self, step: BaseStep, ctx: AdobeOrderContext, error: StopStepError
    ) -> None:
        await super().on_step_stopped(step, ctx, error)
        await self._handle_failure_action(ctx)

    async def _handle_failure_action(self, ctx: AdobeOrderContext) -> None:
        """Persist the declared order status action once per pipeline execution."""
        if ctx.order_state.action is None or ctx.order_state.handled:
            return

        action = ctx.order_state.action
        if action.target_status == OrderStatusActionType.FAIL:
            ctx.logger.info("Failing order due %s.", action.status_notes)
            await ctx.mpt_api_service.orders.fail(
                order_id=ctx.order_id,
                status_notes=action.status_notes,
                parameters=action.parameters,
            )
        else:
            ctx.logger.info("Querying order due %s.", action.status_notes)
            ctx.logger.debug("Query parameters: %s", action.parameters)
            template = await ctx.mpt_api_service.templates.get_order_querying_template(
                ctx.order.product_id
            )
            action.parameters["template"] = template.to_dict()
            ctx.logger.debug("Query template: %s", action.parameters["template"])
            await ctx.mpt_api_service.orders.query(
                order_id=ctx.order_id,
                status_notes=action.status_notes,
                parameters=action.parameters,
            )
        ctx.order_state.handled = True
