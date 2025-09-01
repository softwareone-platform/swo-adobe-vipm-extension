import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import ERR_INVALID_TERMINATION_ORDER_QUANTITY
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    SetOrUpdateCotermDate,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext, Validate3YCCommitment
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    set_order_error,
    validate_subscription_and_returnable_orders,
)
from adobe_vipm.flows.utils.subscription import get_subscription_by_line_subs_id
from adobe_vipm.flows.validation.shared import ValidateDuplicateLines

logger = logging.getLogger(__name__)


class ValidateDownsizes(Step):
    """Checks that for downsizes there orders to remove on Adobe side."""

    def __call__(self, client, context, next_step):
        """Checks that for downsizes there orders to remove on Adobe side."""
        adobe_client = get_adobe_client()
        for line in context.downsize_lines:
            subscription_id = get_subscription_by_line_subs_id(
                context.order["agreement"]["subscriptions"],
                line
            )
            is_valid, _ = validate_subscription_and_returnable_orders(
                adobe_client, context, line, subscription_id
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
    """Validate termination pipeline."""
    pipeline = Pipeline(
        SetupContext(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(is_validation=True),
        ValidateDownsizes(),
        Validate3YCCommitment(is_validation=True),
    )
    context = Context(order=order)
    pipeline.run(client, context)

    return not context.validation_succeeded, context.order
