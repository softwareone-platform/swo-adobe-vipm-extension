"""
This module contains the logic to implement the configuration fulfillment flow.

It exposes a single function that is the entrypoint for configuration order
processing.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeError, SubscriptionUpdateError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SyncAgreement,
    ValidateRenewalWindow,
    get_configuration_template_name,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import notify_not_updated_subscriptions

logger = logging.getLogger(__name__)


def fulfill_configuration_order(client, order):
    """
    Fulfills a configuration order.

    Args:
        client (MPTClient): MPT API client.
        order (dict): MPT Order.
    """
    logger.info("Start processing %s order %s", order["type"], order["id"])

    template_name = get_configuration_template_name(order)

    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(template_name),
        SetupDueDate(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(),
        SubscriptionUpdateAutoRenewal(),
        CompleteOrder(template_name),
        SyncAgreement(),
    )

    context = Context(order=order)
    pipeline.run(client, context)


class SubscriptionUpdateAutoRenewal(Step):
    """Updates Subscription auto renewal flag on Adobe."""

    def __call__(self, client, context, next_step):
        """Updates the auto renewal status of a subscription."""
        adobe_client = get_adobe_client()

        context.updated = []
        for subscription in context.order["subscriptions"]:
            try:
                self._process_subscription(adobe_client, context, subscription)
            except SubscriptionUpdateError as error:
                self._handle_subscription_error(client, adobe_client, context, str(error))
                return

        next_step(client, context)

    def _process_subscription(self, adobe_client, context, subscription):
        subscription_vendor_id = subscription["externalIds"]["vendor"]

        adobe_sub = adobe_client.get_subscription(
            context.order["authorization"]["id"], context.adobe_customer_id, subscription_vendor_id
        )

        if not adobe_sub:
            raise SubscriptionUpdateError(
                f"No Adobe subscription for vendor {subscription_vendor_id}"
            )

        desired = subscription["autoRenew"]
        qty = subscription["lines"][0]["quantity"]
        if adobe_sub["autoRenewal"]["enabled"] == desired:
            logger.info(
                "Subscription %s already autoRenew=%s, qty=%s",
                subscription_vendor_id,
                desired,
                qty,
            )
            return

        try:
            adobe_client.update_subscription(
                context.order["authorization"]["id"],
                context.adobe_customer_id,
                adobe_sub["subscriptionId"],
                auto_renewal=desired,
                quantity=qty,
            )
        except AdobeError as error:
            raise SubscriptionUpdateError(
                f"Error updating the subscription {subscription_vendor_id}: {error}"
            )

        context.updated.append({
            "subscription_vendor_id": subscription_vendor_id,
            "auto_renewal": desired,
            "quantity": qty,
        })
        logger.info(
            "Updated subscription %s: autoRenew=%s, qty=%s",
            subscription_vendor_id,
            desired,
            qty,
        )

    def _handle_subscription_error(self, client, adobe_client, context, error_message):
        """Handles subscription errors by rolling back changes and failing the order."""
        self.rollback_updated_subscriptions(
            adobe_client,
            context.order["authorization"]["id"],
            context.adobe_customer_id,
            context.updated,
        )
        notify_not_updated_subscriptions(
            context.order["id"], error_message, context.updated, context.product_id
        )
        switch_order_to_failed(
            client, context.order, ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR.to_dict(error=error_message)
        )

    def rollback_updated_subscriptions(
        self, adobe_client, authorization_id, customer_id, update_success_subscriptions
    ):
        """
        Rolls back the updated subscriptions.

        Args:
            adobe_client (AdobeClient): Adobe API client
            authorization_id (str): MPT Authorization id.
            customer_id (str): Adobe customer Id.
            update_success_subscriptions (list[str]): list of subscriptions that were already
            updated.
        """
        for subscription_vendor_id in update_success_subscriptions:
            try:
                logger.info(
                    "Rollback updated Adobe subscription %s",
                    subscription_vendor_id["subscription_vendor_id"],
                )
                adobe_client.update_subscription(
                    authorization_id,
                    customer_id,
                    subscription_vendor_id["subscription_vendor_id"],
                    auto_renewal=not subscription_vendor_id["auto_renewal"],
                    quantity=subscription_vendor_id["quantity"],
                )
            except AdobeError:
                logger.exception(
                    "Error rolling back Adobe subscription %s",
                    subscription_vendor_id,
                )
