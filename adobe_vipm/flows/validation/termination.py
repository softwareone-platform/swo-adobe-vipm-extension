import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import ERR_INVALID_TERMINATION_ORDER_QUANTITY
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    SetOrUpdateCotermNextSyncDates,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext, ValidateDownsizes3YC
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    set_order_error,
    validate_subscription_and_returnable_orders,
)
from adobe_vipm.flows.validation.shared import ValidateDuplicateLines

logger = logging.getLogger(__name__)


class ValidateDownsizes(Step):
    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]

            is_valid, _ = validate_subscription_and_returnable_orders(
                adobe_client, context, line, sku
            )

            if not is_valid:
                context.validation_succeeded = False
                context.order = set_order_error(
                    context.order,
                    ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict(),
                )
                return

        next_step(client, context)


def validate_termination_order(client, order):
    pipeline = Pipeline(
        SetupContext(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermNextSyncDates(),
        ValidateRenewalWindow(True),
        ValidateDownsizes(),
        ValidateDownsizes3YC(True),
    )
    context = Context(order=order)
    pipeline.run(client, context)

    return not context.validation_succeeded, context.order
