import logging
from collections import Counter

from adobe_vipm.flows.constants import (
    ERR_DUPLICATED_ITEMS,
    ERR_EXISTING_ITEMS,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils import set_order_error

logger = logging.getLogger(__name__)


class ValidateDuplicateLines(Step):
    """
    Validates if there are duplicated lines (lines with the same item ID within this order)
    or new lines that are not duplicated within this order but that have already a subscription.
    """

    def __call__(self, client, context, next_step):
        if not context.order["lines"]:
            next_step(client, context)
            return

        items = [line["item"]["id"] for line in context.order["lines"]]
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            message = ERR_DUPLICATED_ITEMS.to_dict(duplicates=",".join(duplicates))
            context.order = set_order_error(context.order, message)
            logger.info(f"{context}: {message}")
            context.validation_succeeded = False
            return

        items = []
        for subscription in context.order["agreement"]["subscriptions"]:
            for line in subscription["lines"]:
                items.append(line["item"]["id"])

        items.extend(
            [
                line["item"]["id"]
                for line in context.order["lines"]
                if line["oldQuantity"] == 0
            ]
        )
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            message = ERR_EXISTING_ITEMS.to_dict(duplicates=",".join(duplicates))
            context.order = set_order_error(
                context.order,
                message,
            )
            logger.info(f"{context}: {message}")
            context.validation_succeeded = False
            return
        next_step(client, context)
