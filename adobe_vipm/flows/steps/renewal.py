from venv import logger

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, SubscriptionUpdateError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR,
    ERR_INVALID_RENEWAL_STATE,
)
from adobe_vipm.flows.fulfillment.shared import switch_order_to_failed
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.steps.subscription import UpdateRenewalQuantities
from adobe_vipm.flows.utils.notification import notify_not_updated_subscriptions
from adobe_vipm.flows.utils.subscription import (
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
)


class UpdateRenewalQuantitiesDownsizes(UpdateRenewalQuantities):
    """Updates the Adobe subscriptions renewal quantity for downsized items."""

    def _get_lines(self, context):
        return context.downsize_lines


class SwitchAutoRenewalOff(Step):
    """Set the autoRenewal flag to False forsubscription that must be cancelled."""

    def __call__(self, client, context, next_step):
        """Set the autoRenewal flag to False forsubscription that must be cancelled."""
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
                        "%s: autorenewal switched off for %s (%s)",
                        context,
                        subscription["id"],
                        adobe_subscription["subscriptionId"],
                    )
                except AdobeAPIError as e:
                    logger.exception(
                        "%s: failed to switch off autorenewal for %s (%s)",
                        context,
                        subscription["id"],
                        adobe_subscription["subscriptionId"],
                    )
                    if e.code == AdobeStatus.INVALID_RENEWAL_STATE:
                        switch_order_to_failed(
                            client,
                            context.order,
                            ERR_INVALID_RENEWAL_STATE.to_dict(error=e.message),
                        )
                    return
        next_step(client, context)


class SubscriptionUpdateAutoRenewal(Step):
    """Updates Subscription auto renewal flag on Adobe."""

    def __call__(self, client, context, next_step):
        """Updates the auto renewal status of a subscription."""
        adobe_client = get_adobe_client()

        context.updated = []
        for subscription in context.order["subscriptions"]:
            try:
                self._process_subscription(adobe_client, context, subscription)
            except SubscriptionUpdateError as e:
                self._handle_subscription_error(client, adobe_client, context, str(e))
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
        except AdobeError as e:
            raise SubscriptionUpdateError(
                f"Error updating the subscription {subscription_vendor_id}: {e}"
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
