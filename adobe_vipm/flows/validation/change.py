import itertools
import logging
from datetime import datetime, timedelta
from operator import attrgetter

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import (
    ERR_INVALID_DOWNSIZE_QUANTITY,
    ERR_INVALID_ITEM_DOWNSIZE_FIRST_PO,
    ERR_INVALID_ITEM_DOWNSIZE_QUANTITY,
    ERR_INVALID_ITEM_DOWNSIZE_QUANTITY_ANY_COMBINATION,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    SetOrUpdateCotermNextSyncDates,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import (
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
)
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import set_order_error
from adobe_vipm.flows.utils.customer import is_within_coterm_window
from adobe_vipm.flows.validation.shared import (
    GetPreviewOrder,
    ValidateDuplicateLines,
)

logger = logging.getLogger(__name__)


class ValidateDownsizes(Step):
    @staticmethod
    def get_returnable_by_quantity_map(returnable_orders):
        returnable_by_quantity = {}
        for r in range(len(returnable_orders), 0, -1):
            for sub in itertools.combinations(returnable_orders, r):
                returnable_by_quantity[sum([x.quantity for x in sub])] = sub
        return returnable_by_quantity

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        errors = []

        if is_within_coterm_window(context.adobe_customer):
            logger.info(
                "Downsize occurs in the last two weeks before the anniversary date. "
                "Returnable orders are not going to be submitted, the renewal quantity "
                "will be updated. Skip downsize validation."
            )
            next_step(client, context)
            return

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

            returnable_by_quantity = self.get_returnable_by_quantity_map(returnable_orders)

            delta = line["oldQuantity"] - line["quantity"]

            if delta not in returnable_by_quantity:
                end_of_cancellation_window = max(
                    datetime.fromisoformat(roi.order["creationDate"]).date()
                    for roi in returnable_orders
                ) + timedelta(days=15)

                quantities = [
                    str(roi.quantity)
                    for roi in sorted(returnable_orders, key=attrgetter("quantity"))
                    if roi.quantity != line["oldQuantity"]
                ]
                if len(quantities) == 0:
                    message = ERR_INVALID_ITEM_DOWNSIZE_FIRST_PO.format(
                        item=line["item"]["name"],
                        delta=delta,
                        quantity=line["quantity"],
                    )
                    errors.append(message)
                    context.validation_succeeded = False
                    continue

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
            return
        next_step(client, context)


def validate_change_order(client, order):
    pipeline = Pipeline(
        SetupContext(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermNextSyncDates(),
        ValidateRenewalWindow(is_validation=True),
        ValidateDownsizes(),
        Validate3YCCommitment(True),
        GetPreviewOrder(),
        UpdatePrices(),
    )
    context = Context(order=order)
    pipeline.run(client, context)

    return not context.validation_succeeded, context.order
