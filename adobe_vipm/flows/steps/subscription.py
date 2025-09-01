import logging
from functools import partial

from mpt_extension_sdk.mpt_http.mpt import create_subscription
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import ERR_INVALID_RENEWAL_STATE, Param
from adobe_vipm.flows.fulfillment.shared import set_subscription_actual_sku, switch_order_to_failed
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.notification import notify_not_updated_subscriptions
from adobe_vipm.flows.utils.order import get_one_time_skus, get_order_line_by_sku
from adobe_vipm.flows.utils.subscription import (
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
    get_transfer_item_sku_by_subscription,
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


class CreateOrUpdateSubscriptions(Step):
    """Create or update subscriptions in MPT based on Adobe Subscriptions."""

    def __call__(self, client, context, next_step):
        """Create or update subscriptions in MPT based on Adobe Subscriptions."""
        if context.adobe_new_order:
            adobe_client = get_adobe_client()
            one_time_skus = get_one_time_skus(client, context.order)
            for line in filter(
                lambda x: get_partial_sku(x["offerId"]) not in one_time_skus,
                context.adobe_new_order["lineItems"],
            ):
                order_line = get_order_line_by_sku(context.order, line["offerId"])

                order_subscription = get_subscription_by_line_and_item_id(
                    context.order["subscriptions"],
                    order_line["item"]["id"],
                    order_line["id"],
                )
                if not order_subscription:
                    adobe_subscription = adobe_client.get_subscription(
                        context.authorization_id,
                        context.adobe_customer_id,
                        line["subscriptionId"],
                    )

                    if adobe_subscription["status"] != AdobeStatus.PROCESSED:
                        logger.warning(
                            "%s: subscription %s for customer %s is in status %s, skip it",
                            context,
                            adobe_subscription["subscriptionId"],
                            context.adobe_customer_id,
                            adobe_subscription["status"],
                        )
                        continue

                    subscription = {
                        "name": f"Subscription for {order_line['item']['name']}",
                        "parameters": {
                            "fulfillment": [
                                {
                                    "externalId": Param.ADOBE_SKU.value,
                                    "value": line["offerId"],
                                },
                                {
                                    "externalId": Param.CURRENT_QUANTITY.value,
                                    "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                                },
                                {
                                    "externalId": Param.RENEWAL_QUANTITY.value,
                                    "value": str(
                                        adobe_subscription["autoRenewal"][
                                            Param.RENEWAL_QUANTITY.value
                                        ]
                                    ),
                                },
                                {
                                    "externalId": Param.RENEWAL_DATE.value,
                                    "value": str(adobe_subscription["renewalDate"]),
                                },
                            ]
                        },
                        "externalIds": {
                            "vendor": line["subscriptionId"],
                        },
                        "lines": [
                            {
                                "id": order_line["id"],
                            },
                        ],
                        "startDate": adobe_subscription["creationDate"],
                        "commitmentDate": adobe_subscription["renewalDate"],
                        "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
                    }
                    subscription = create_subscription(client, context.order_id, subscription)
                    logger.info(
                        "%s: subscription %s (%s) created",
                        context,
                        line["subscriptionId"],
                        subscription["id"],
                    )
                else:
                    adobe_sku = line["offerId"]
                    set_subscription_actual_sku(
                        client,
                        context.order,
                        order_subscription,
                        adobe_sku,
                    )
                    logger.info(
                        "%s: subscription %s (%s) updated",
                        context,
                        line["subscriptionId"],
                        order_subscription["id"],
                    )
        next_step(client, context)


class UpdateRenewalQuantities(Step):
    """
    Updates the Adobe subscriptions renewal quantity if it doesn't match the agreement quantity.

    If process_downsize_lines is False, the downsize lines will not be processed.
    If process_upsize_lines is False, the upsize and new lines will not be processed.
    The upsizes and new lines are processed first, to process correctly the 3yc
    to maintain the compliant with the 3yc minimum quantities.
    """

    def __init__(self):
        self.error = None

    def __call__(self, client, context, next_step):
        """Updates the Adobe subscriptions renewal quantity if it doesn't match."""
        adobe_client = get_adobe_client()
        context.updated = []
        self._update_lines(adobe_client, context)
        if self.error:
            self._handle_subscription_update_error(adobe_client, client, context, self.error)
            return

        next_step(client, context)

    def _get_lines(self, context):
        return context.upsize_lines + context.new_lines

    def _update_lines(self, adobe_client, context):
        for line in self._get_lines(context):
            self._update_line(adobe_client, context, line)

    def _update_line(self, adobe_client, context, line):
        subscription = get_subscription_by_line_and_item_id(
            context.order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        if not subscription:
            return
        adobe_sub_id = get_adobe_subscription_id(subscription)
        adobe_subscription = adobe_client.get_subscription(
            context.authorization_id,
            context.adobe_customer_id,
            adobe_sub_id,
        )
        qty = line["quantity"]
        old_qty = adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]

        if old_qty != qty:
            try:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    adobe_sub_id,
                    quantity=qty,
                )
            except AdobeAPIError as error:
                invalid_renewal_state_allowed = False
                if error.code == AdobeStatus.INVALID_RENEWAL_STATE and old_qty < qty:
                    logger.info(
                        "Got invalid renewal state error for subscription %s while updating"
                        " quantity %s -> %s",
                        subscription["id"],
                        old_qty,
                        qty,
                    )
                    invalid_renewal_state_allowed = _is_invalid_renewal_state_ok(context, line)
                if not (
                    invalid_renewal_state_allowed
                    or (
                        error.code == AdobeStatus.LINE_ITEM_OFFER_ID_EXPIRED
                        and context.adobe_new_order
                    )
                ):
                    logger.exception(
                        "%s: failed to update renewal quantity for %s (%s)",
                        context,
                        subscription["id"],
                        adobe_sub_id,
                    )
                    notify_not_updated_subscriptions(
                        context.order["id"],
                        f"Error updating subscription {subscription['id']}, {error}",
                        [],
                        context.product_id,
                    )
                    self.error = error
                    return

            logger.info(
                "%s: update renewal quantity for sub %s (%s) %s -> %s",
                context,
                subscription["id"],
                adobe_sub_id,
                old_qty,
                qty,
            )
            context.updated.append({
                "subscription_vendor_id": adobe_sub_id,
                "old_quantity": old_qty,
                "new_quantity": qty,
            })

    def _handle_subscription_update_error(self, adobe_client, client, context, e):
        self._rollback_updated_subscriptions(adobe_client, context)
        if e.code in {
            AdobeStatus.INVALID_RENEWAL_STATE,
            AdobeStatus.SUBSCRIPTION_INACTIVE,
        }:
            switch_order_to_failed(
                client,
                context.order,
                ERR_INVALID_RENEWAL_STATE.to_dict(error=e.message),
            )

    def _rollback_updated_subscriptions(self, adobe_client, context):
        try:
            for updated in context.updated:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    updated["subscription_vendor_id"],
                    quantity=updated["old_quantity"],
                )
            if context.adobe_new_order:
                adobe_client.create_return_order_by_adobe_order(
                    context.authorization_id,
                    context.adobe_customer_id,
                    context.adobe_new_order,
                )
        except Exception as e:
            notify_not_updated_subscriptions(
                context.order["id"],
                f"Error rolling back updated subscriptions: {e}",
                context.updated,
                context.product_id,
            )
            logger.exception("Error rolling back updated subscriptions")


class UpdateSubscriptionSkus(Step):
    """Update MPT subscription skus."""

    def __call__(self, mpt_client, context, next_step):
        """Update MPT subscription skus."""
        for subscription in context.subscriptions["items"]:
            correct_sku = get_transfer_item_sku_by_subscription(
                context.adobe_transfer, subscription["subscriptionId"]
            )
            subscription["offerId"] = correct_sku or subscription["offerId"]
        next_step(mpt_client, context)
