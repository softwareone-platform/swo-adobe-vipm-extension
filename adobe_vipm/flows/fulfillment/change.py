"""
This module contains the logic to implement the change fulfillment flow.

It exposes a single function that is the entrypoint for change order
processing.
"""

import logging
from functools import partial

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.utils import find_first
from adobe_vipm.flows.constants import (
    TEMPLATE_NAME_CHANGE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.steps.agreement import SyncAgreement
from adobe_vipm.flows.steps.context import SetupContext
from adobe_vipm.flows.steps.coterm_date import SetOrUpdateCotermDate
from adobe_vipm.flows.steps.due_date import SetupDueDate
from adobe_vipm.flows.steps.order import (
    CompleteOrder,
    GetPreviewOrder,
    GetReturnableOrders,
    GetReturnOrders,
    StartOrderProcessing,
    SubmitNewOrder,
    SubmitReturnOrders,
)
from adobe_vipm.flows.steps.price import UpdatePrices
from adobe_vipm.flows.steps.renewal import UpdateRenewalQuantitiesDownsizes
from adobe_vipm.flows.steps.subscription import CreateOrUpdateSubscriptions, UpdateRenewalQuantities
from adobe_vipm.flows.steps.validation import (
    Validate3YCCommitment,
    ValidateDuplicateLinesForOrder,
    ValidateRenewalWindow,
    ValidateReturnableOrders,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def _check_item_in_order(line, order_item):
    return get_partial_sku(order_item["offerId"]) == line["item"]["externalIds"]["vendor"]


def _is_invalid_renewal_state_ok(context, line):
    invalid_renewal_state_allowed = True
    check_item_in_order = partial(_check_item_in_order, line)
    if context.adobe_new_order and find_first(
        check_item_in_order, context.adobe_new_order["lineItems"]
    ):
        invalid_renewal_state_allowed = (
            context.adobe_new_order["status"] == AdobeStatus.PROCESSED.value
        )
        if invalid_renewal_state_allowed:
            logger.info("> Vendor order with the item has status PROCESSED")

    return invalid_renewal_state_allowed


def fulfill_change_order(client, order):
    """
    Fulfills a change order by processing the necessary actions based on the provided parameters.

    Args:
        client (MPTClient): An instance of the MPT client used for communication
        with the MPT system.
        order (dict): The MPT order representing the change order to be fulfilled.

    Returns:
        None
    """
    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(TEMPLATE_NAME_CHANGE),
        SetupDueDate(),
        ValidateDuplicateLinesForOrder(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(),
        GetReturnOrders(),
        GetReturnableOrders(),
        ValidateReturnableOrders(),
        Validate3YCCommitment(),
        GetPreviewOrder(),
        SubmitNewOrder(),
        UpdateRenewalQuantities(),
        SubmitReturnOrders(),
        UpdateRenewalQuantitiesDownsizes(),
        CreateOrUpdateSubscriptions(),
        UpdatePrices(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
