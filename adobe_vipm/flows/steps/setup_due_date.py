import datetime as dt
from typing import override

from mpt_extension_sdk.errors.step import StopStepError
from mpt_extension_sdk.pipeline import BaseStep, OrderStatusAction, OrderStatusActionType

from adobe_vipm.flows.constants import ERR_DUE_DATE_REACHED, Param
from adobe_vipm.flows.context import AdobeOrderContext


class SetupDueDate(BaseStep):
    """Set the due date for the order."""

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        due_date = ctx.due_date
        updated_parameters = ctx.order.parameters
        if due_date is None:
            due_date = dt.datetime.now(tz=dt.UTC).date() + dt.timedelta(
                days=int(ctx.ext_settings.due_date_days)
            )
            updated_parameters = ctx.with_due_date(due_date)

        now = dt.datetime.now(tz=dt.UTC).date()
        formatted_due_date = due_date.strftime("%Y-%m-%d")
        if now > due_date:
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.FAIL,
                message=f"Due date {formatted_due_date} is reached",
                status_notes=ERR_DUE_DATE_REACHED.to_dict(due_date=formatted_due_date),
                parameters=updated_parameters.to_dict(),
            )
            raise StopStepError(f"Due date {formatted_due_date} is reached")

        await ctx.mpt_api_service.orders.update(
            ctx.order_id,
            parameters=updated_parameters.get_fulfillment_parameter(Param.DUE_DATE).to_dict(),
        )
        ctx.logger.info("due date is set to %s successfully", formatted_due_date)
