"""
This module contains the logic to implement the termination fulfillment flow.
It exposes a single function that is the entrypoint for termination order
processing.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import TEMPLATE_NAME_TERMINATION
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    GetReturnOrders,
    IncrementAttemptsCounter,
    SetOrUpdateCotermNextSyncDates,
    StartOrderProcessing,
    SubmitReturnOrders,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext, ValidateDownsizes3YC
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
)

logger = logging.getLogger(__name__)


class GetReturnableOrders(Step):
    """
    For each SKU retrieve all the orders that can be returned.
    """

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            context.adobe_returnable_orders[sku] = (
                adobe_client.get_returnable_orders_by_sku(
                    context.authorization_id,
                    context.adobe_customer_id,
                    sku,
                    context.adobe_customer["cotermDate"],
                )
            )
        returnable_orders_count = sum(
            len(v) for v in context.adobe_returnable_orders.values()
        )
        logger.info(f"{context}: found {returnable_orders_count} returnable orders.")
        next_step(client, context)


class SwitchAutoRenewalOff(Step):
    """
    Set the autoRenewal flag to False for
    subscription that must be cancelled.
    """

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        for line in context.downsize_lines:
            subcription = get_subscription_by_line_and_item_id(
                context.order["subscriptions"],
                line["item"]["id"],
                line["id"],
            )
            adobe_sub_id = get_adobe_subscription_id(subcription)
            adobe_subscription = adobe_client.get_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                adobe_sub_id,
            )
            if adobe_subscription["autoRenewal"]["enabled"]:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    adobe_sub_id,
                    auto_renewal=False,
                )
                logger.info(
                    f"{context}: autorenewal switched off for {subcription['id']} "
                    f"({adobe_subscription['subscriptionId']})"
                )
        next_step(client, context)


def fulfill_termination_order(client, order):
    """
    Fulfills a termination order with Adobe.
    Adobe allow to terminate a subscription with a cancellation window
    (X days from the first order).
    For subscriptions that are outside such window the auto renewal
    will be switched off.

    Args:
        mpt_client (MPTClient):  an instance of the Marketplace platform client.
        order (dct): The MPT termination order.
    """

    pipeline = Pipeline(
        SetupContext(),
        IncrementAttemptsCounter(),
        SetOrUpdateCotermNextSyncDates(),
        StartOrderProcessing(TEMPLATE_NAME_TERMINATION),
        ValidateRenewalWindow(),
        GetReturnableOrders(),
        ValidateDownsizes3YC(),
        GetReturnOrders(),
        SubmitReturnOrders(),
        SwitchAutoRenewalOff(),
        CompleteOrder(TEMPLATE_NAME_TERMINATION),
    )
    context = Context(order=order)
    pipeline.run(client, context)
