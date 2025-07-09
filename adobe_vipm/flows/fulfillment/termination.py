"""
This module contains the logic to implement the termination fulfillment flow.
It exposes a single function that is the entrypoint for termination order
processing.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_INVALID_RENEWAL_STATE,
    ERR_INVALID_TERMINATION_ORDER_QUANTITY,
    TEMPLATE_NAME_TERMINATION,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    GetReturnOrders,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitReturnOrders,
    SyncAgreement,
    ValidateRenewalWindow,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext, Validate3YCCommitment
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
    validate_subscription_and_returnable_orders,
)
from adobe_vipm.flows.utils.subscription import get_subscription_by_line_subs_id

logger = logging.getLogger(__name__)


class GetReturnableOrders(Step):
    """
    For each SKU retrieve all the orders that can be returned.
    """

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            subscription_id = get_subscription_by_line_subs_id(
                context.order["agreement"]["subscriptions"],
                line
            )
            is_valid, returnable_orders = validate_subscription_and_returnable_orders(
                adobe_client, context, line, subscription_id, return_orders=context.adobe_return_orders.get(sku)
            )
            logger.info(f"{context}: returnable orders: {returnable_orders} for {sku}")
            if not is_valid:
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict(),
                )
                return

            context.adobe_returnable_orders[sku] = returnable_orders

        returnable_orders_count = sum(len(v) for v in context.adobe_returnable_orders.values())
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
            subscription = get_subscription_by_line_and_item_id(
                context.order["subscriptions"],
                line["item"]["id"],
                line["id"],
            )
            adobe_sub_id = get_adobe_subscription_id(subscription)
            adobe_subscription = adobe_client.get_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                adobe_sub_id,
            )
            if adobe_subscription["autoRenewal"]["enabled"]:
                try:
                    adobe_client.update_subscription(
                        context.authorization_id,
                        context.adobe_customer_id,
                        adobe_sub_id,
                        auto_renewal=False,
                    )
                    logger.info(
                        f"{context}: autorenewal switched off for {subscription['id']} "
                        f"({adobe_subscription['subscriptionId']})"
                    )
                except AdobeAPIError as e:
                    logger.error(
                        f"{context}: failed to switch off autorenewal for {subscription['id']} "
                        f"({adobe_subscription['subscriptionId']}) due to {e}"
                    )
                    if e.code == AdobeStatus.STATUS_INVALID_RENEWAL_STATE:
                        switch_order_to_failed(
                            client,
                            context.order,
                            ERR_INVALID_RENEWAL_STATE.to_dict(error=e.message),
                        )
                    return
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
        SetupDueDate(),
        SetOrUpdateCotermDate(),
        StartOrderProcessing(TEMPLATE_NAME_TERMINATION),
        ValidateRenewalWindow(),
        GetReturnOrders(),
        GetReturnableOrders(),
        Validate3YCCommitment(),
        SubmitReturnOrders(),
        CompleteOrder(TEMPLATE_NAME_TERMINATION),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
