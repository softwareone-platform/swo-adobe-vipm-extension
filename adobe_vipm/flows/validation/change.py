import itertools
import logging
from datetime import datetime, timedelta
from operator import attrgetter

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import (
    ERR_INVALID_DOWNSIZE_QUANTITY,
    ERR_INVALID_ITEM_DOWNSIZE_QUANTITY,
    ERR_INVALID_ITEM_DOWNSIZE_QUANTITY_ANY_COMBINATION,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import set_order_error
from adobe_vipm.flows.validation.shared import ValidateDuplicateLines

logger = logging.getLogger(__name__)


class ValidateDownsizes(Step):
    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        errors = []
        last_two_weeks = (
            datetime.fromisoformat(context.adobe_customer["cotermDate"])
            - timedelta(days=13)
        ).date()
        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            returnable_orders = adobe_client.get_returnable_orders_by_sku(
                context.authorization_id,
                context.adobe_customer_id,
                sku,
                context.adobe_customer["cotermDate"],
            )
            if not returnable_orders:
                continue

            returnable_by_quantity = {}
            for r in range(len(returnable_orders), 0, -1):
                for sub in itertools.combinations(returnable_orders, r):
                    returnable_by_quantity[sum([x.quantity for x in sub])] = sub

            delta = line["oldQuantity"] - line["quantity"]
            if delta not in returnable_by_quantity:
                end_of_cancellation_window = max(
                    datetime.fromisoformat(roi.order["creationDate"]).date()
                    for roi in returnable_orders
                ) + timedelta(days=15)
                end_of_cancellation_window = min(
                    end_of_cancellation_window, last_two_weeks
                )
                quantities = [
                    str(roi.quantity)
                    for roi in sorted(returnable_orders, key=attrgetter("quantity"))
                ]
                message = ERR_INVALID_ITEM_DOWNSIZE_QUANTITY.format(
                    item=line["item"]["name"],
                    delta=delta,
                    available_quantities=", ".join(quantities),
                    any_combination=(
                        ERR_INVALID_ITEM_DOWNSIZE_QUANTITY_ANY_COMBINATION
                        if len(quantities) > 1
                        else ""
                    ),
                    date=end_of_cancellation_window.isoformat(),
                )
                errors.append(message)
                context.validation_succeeded = False
                continue
        if errors:
            context.order = set_order_error(
                context.order,
                ERR_INVALID_DOWNSIZE_QUANTITY.to_dict(messages="\n".join(errors)),
            )
        else:
            next_step(client, context)


def validate_change_order(client, order):
    pipeline = Pipeline(
        SetupContext(),
        ValidateDuplicateLines(),
        ValidateDownsizes(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
    return not context.validation_succeeded, context.order
