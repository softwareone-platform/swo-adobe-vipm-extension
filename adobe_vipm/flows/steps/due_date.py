import datetime as dt
import logging

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.flows.constants import ERR_DUE_DATE_REACHED
from adobe_vipm.flows.fulfillment.shared import switch_order_to_failed
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.date import get_due_date, set_due_date

logger = logging.getLogger(__name__)


class SetupDueDate(Step):
    """Setups properly due date."""

    def __call__(self, client, context, next_step):
        """Setups properly due date."""
        context.order = set_due_date(context.order)
        due_date = get_due_date(context.order)
        context.due_date = due_date
        due_date_str = due_date.strftime("%Y-%m-%d")

        if dt.datetime.now(tz=dt.UTC).date() > due_date:
            logger.info("%s: due date (%s) is reached.", context, due_date_str)
            switch_order_to_failed(
                client,
                context.order,
                ERR_DUE_DATE_REACHED.to_dict(due_date=due_date_str),
            )
            return
        update_order(client, context.order_id, parameters=context.order["parameters"])
        logger.info("%s: due date is set to %s successfully.", context, due_date_str)
        next_step(client, context)
