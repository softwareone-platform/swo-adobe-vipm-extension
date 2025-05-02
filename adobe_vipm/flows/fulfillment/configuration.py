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
    StartOrderProcessing,
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
    """
    logger.info(f'Start processing {order["type"]} order {order["id"]}')

    template_name = get_configuration_template_name(order)

    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(template_name),
        SubscriptionUpdateAutoRenewal(),
        CompleteOrder(template_name),
    )

    context = Context(order=order)
    pipeline.run(client, context)



class SubscriptionUpdateAutoRenewal(Step):
    def __call__(self, client, context, next_step):
        """
        Updates the auto renewal status of a subscription.
        """
        logger.info(f'Start processing {context.order["type"]} order {context.order["id"]}')
        adobe_client = get_adobe_client()
        customer_id = context.adobe_customer_id
        auth_id = context.order["authorization"]["id"]

        updated = []
        for subscription in context.order["subscriptions"]:
            try:
                self._process_one_subscription(adobe_client, auth_id, customer_id,
                                               subscription, updated)
            except SubscriptionUpdateError as e:
                self._handle_subscription_error(client, adobe_client, auth_id, customer_id,
                                                updated, context, str(e))
                return

        next_step(client, context)


    def _process_one_subscription(self, adobe_client, auth_id, customer_id, subscription, updated):
        subscription_vendor_id = subscription["externalIds"]["vendor"]

        adobe_sub = adobe_client.get_subscription(auth_id, customer_id, subscription_vendor_id)
        if not adobe_sub:
            raise SubscriptionUpdateError(f"No Adobe subscription for "
                                          f"vendor {subscription_vendor_id}")

        desired = subscription["autoRenew"]
        qty = subscription["lines"][0]["quantity"]
        if adobe_sub["autoRenewal"]["enabled"] == desired:
            logger.info(f"Subscription {subscription_vendor_id} "
                        f"already autoRenew={desired}, qty={qty}")
            return

        try:
            adobe_client.update_subscription(
                auth_id, customer_id, adobe_sub["subscriptionId"],
                auto_renewal=desired, quantity=qty
            )
        except AdobeError as e:
            raise SubscriptionUpdateError(
                f"Error updating the subscription {subscription_vendor_id}: {str(e)}"
            )

        updated.append({
            "subscription_vendor_id": subscription_vendor_id,
            "auto_renewal": desired,
            "quantity": qty})
        logger.info(f"Updated subscription {subscription_vendor_id}: "
                    f"autoRenew={desired}, qty={qty}")


    def _handle_subscription_error(self,client, adobe_client, authorization_id, customer_id,
                                 update_success_subscriptions, context, error_message):
        """
        Handles subscription errors by rolling back changes and failing the order.
        """
        self.rollback_updated_subscriptions(
            adobe_client,
            authorization_id,
            customer_id,
            update_success_subscriptions)
        notify_not_updated_subscriptions(
            context.order["id"],
            error_message,
            update_success_subscriptions,
            context.product_id)
        switch_order_to_failed(client, context.order,
                               ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR.to_dict(error=error_message))


    def rollback_updated_subscriptions(self, adobe_client, authorization_id,
                                       customer_id, update_success_subscriptions):
        """
        Rolls back the updated subscriptions.
        """
        for subscription_vendor_id in update_success_subscriptions:
            try:
                logger.info(
                    f"Rollback updated Adobe subscription "
                    f"{subscription_vendor_id['subscription_vendor_id']}"
                )
                adobe_client.update_subscription(
                    authorization_id,
                    customer_id,
                    subscription_vendor_id["subscription_vendor_id"],
                    auto_renewal=not subscription_vendor_id["auto_renewal"],
                    quantity=subscription_vendor_id["quantity"]
                )
            except AdobeError as e:
                logger.error(f"Error rolling back Adobe subscription {subscription_vendor_id}: {e}")
