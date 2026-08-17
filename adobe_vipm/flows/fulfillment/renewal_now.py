"""
This module contains the logic to implement the renew-now fulfillment flow.

It exposes a single function that is the entrypoint for change orders that
carry a renewal payload built by the renewal wizard with renewalPath "now"
(see flows/fulfillment/renewal.py for the at-anniversary path). The
renewing subscriptions are committed as an actual Adobe RENEWAL order,
invoiced immediately, mirroring how the PURCHASE flow turns its PREVIEW
order into a NEW order: validate with PREVIEW_RENEWAL, then resubmit the
line items it returns as the real order. Once the order completes, the
renewed subscriptions (renew = true) have their autoRenewal normalised
(enabled=on, renewalQuantity taken from Adobe's post-renewal
renewedQuantity) and the plan's lapsing subscriptions (renew = false)
have their auto-renewal disabled.

Net-new items and RETURN orders for toggled-off lines are not handled yet.
"""

import logging

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    ORDER_TYPE_PREVIEW_RENEWAL,
    UNRECOVERABLE_ORDER_STATUSES,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_RENEWAL_ORDER_FAILED,
    ERR_RENEWAL_PREVIEW_FAILED,
    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    TEMPLATE_NAME_CHANGE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
    SetupDueDate,
    SetupRenewalPlan,
    StartOrderProcessing,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
    get_existing_renewal_order,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils.parameter import set_adobe_order_ids_created_parameter

logger = logging.getLogger(__name__)


def _build_renewing_line_items(context):
    """Build PREVIEW_RENEWAL/RENEWAL line items for the plan's renewing subscriptions."""
    line_items = []
    renewing = [plan for plan in context.renewal_plan_subscriptions if plan["renew"]]
    for number, plan in enumerate(renewing, start=1):
        line_item = {
            "extLineItemNumber": number,
            "offerId": plan["offer_id"],
            "subscriptionId": plan["subscription_id"],
            "quantity": plan["renewal_quantity"],
        }
        if plan["flex_discount_codes"]:
            line_item["flexDiscountCodes"] = plan["flex_discount_codes"]
        line_items.append(line_item)
    return line_items


def _build_committed_line_items(preview_line_items):
    """
    Build RENEWAL order line items from a PREVIEW_RENEWAL response's line items.

    Mirrors how the PURCHASE flow turns its PREVIEW order into a NEW order
    (AdobeClient._build_line_item): the preview response is the source of
    truth for the offer and quantity actually being committed, but it is
    response-shaped (e.g. flexDiscounts is a list of discount result
    objects, not the flexDiscountCodes the create-order request expects) and
    carries pricing fields the create-order request doesn't need, so it is
    re-shaped into a request line item rather than forwarded as-is.
    """
    line_items = []
    for preview_line_item in preview_line_items:
        line_item = {
            "extLineItemNumber": preview_line_item["extLineItemNumber"],
            "offerId": preview_line_item["offerId"],
            "subscriptionId": preview_line_item["subscriptionId"],
            "quantity": preview_line_item["quantity"],
        }
        flex_discounts = preview_line_item.get("flexDiscounts")
        if flex_discounts:
            line_item["flexDiscountCodes"] = [flex_discounts[0]["code"]]
        if preview_line_item.get("deploymentId"):
            line_item["deploymentId"] = preview_line_item["deploymentId"]
            line_item["currencyCode"] = preview_line_item["currencyCode"]
        line_items.append(line_item)
    return line_items


class PreviewRenewalNowOrder(Step):
    """
    Validate the renew-now plan with a PREVIEW_RENEWAL order.

    The preview is the authoritative source of discount-code and SKU
    validation and runs before SubmitRenewalNowOrder commits anything, so a
    rejected basket fails the order with nothing to reverse. Skipped once
    the real RENEWAL order already exists (idempotent retries).
    """

    def __call__(self, client, context, next_step):
        """Validate the renew-now plan with a PREVIEW_RENEWAL order."""
        line_items = _build_renewing_line_items(context)
        if not line_items:
            logger.info("%s: no renewing subscriptions, skipping renewal preview", context)
            next_step(client, context)
            return

        if not self._validate_preview(client, context, line_items):
            return

        next_step(client, context)

    def _validate_preview(self, client, context, line_items):
        """Validate the plan via PREVIEW_RENEWAL, returning False on a confirmed failure."""
        adobe_client = get_adobe_client()
        existing_order = get_existing_renewal_order(adobe_client, context, context.order_id)
        if existing_order:
            logger.info("%s: renewal order %s already exists", context, existing_order["orderId"])
            return True

        try:
            context.preview_renewal_order = adobe_client.create_renewal_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
                line_items,
                order_type=ORDER_TYPE_PREVIEW_RENEWAL,
            )
        except AdobeAPIError as error:
            logger.warning("%s: renewal preview failed: %s", context, error)
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_PREVIEW_FAILED.to_dict(error=error.message),
            )
            return False

        logger.info(
            "%s: renewal preview validated for %s subscription(s)", context, len(line_items)
        )
        return True


class SubmitRenewalNowOrder(Step):
    """
    Commit the renew-now plan as an actual Adobe RENEWAL order.

    Uses the line items validated by PreviewRenewalNowOrder — the renewal
    counterpart of how the PURCHASE flow turns its PREVIEW order into a NEW
    order. It is invoiced immediately and takes effect now. The existing
    Adobe RENEWAL order is detected by its external reference id, so a
    retry of this step is idempotent.

    Net-new items and RETURN orders for toggled-off lines are not handled
    by this step.
    """

    def __call__(self, client, context, next_step):
        """Commit the renew-now plan as an actual Adobe RENEWAL order."""
        if not _build_renewing_line_items(context):
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        existing_order = get_existing_renewal_order(adobe_client, context, context.order_id)
        if not existing_order and context.preview_renewal_order is None:
            logger.info("%s: no renewal preview available, skipping renewal order", context)
            next_step(client, context)
            return

        order = existing_order or self._submit_order(client, context, adobe_client)
        if order is None:
            return

        if not self._is_order_complete(client, context, order):
            return

        context.adobe_renewal_order = order
        logger.info("%s: renewal order %s completed", context, order["orderId"])
        next_step(client, context)

    def _submit_order(self, client, context, adobe_client):
        try:
            order = adobe_client.create_renewal_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
                _build_committed_line_items(context.preview_renewal_order["lineItems"]),
            )
        except AdobeAPIError as error:
            logger.warning("%s: renewal order failed: %s", context, error)
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_ORDER_FAILED.to_dict(error=error.message),
            )
            return None

        logger.info("%s: renewal order %s created", context, order["orderId"])
        context.order = set_adobe_order_ids_created_parameter(context, [order["orderId"]])
        update_order(client, context.order_id, parameters=context.order["parameters"])
        return order

    def _is_order_complete(self, client, context, order):
        """Return True once the order is COMPLETE, failing the MPT order on a terminal status."""
        if order["status"] == AdobeOrderStatus.OPEN:
            logger.info("%s: renewal order %s is still pending", context, order["orderId"])
            return False

        if order["status"] in UNRECOVERABLE_ORDER_STATUSES:
            error = ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS.to_dict(
                description=ORDER_STATUS_DESCRIPTION[order["status"]],
            )
            self._fail_order(client, context, order, error)
            return False

        if order["status"] != AdobeOrderStatus.COMPLETE:
            error = ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status=order["status"])
            self._fail_order(client, context, order, error)
            return False

        return True

    def _fail_order(self, client, context, order, error):
        switch_order_to_failed(client, context.order, error)
        logger.warning(
            "%s: renewal order %s has been failed: %s",
            context,
            order["orderId"],
            error["message"],
        )


class NormalizeRenewedSubscriptions(Step):
    """
    Normalise autoRenewal for the plan's renewed subscriptions (renew = true).

    Runs once the renew-now RENEWAL order has committed — Adobe blocks
    autoRenewal PATCHes on a subscription during its renewal-fulfilment
    window, so this can't happen before SubmitRenewalNowOrder completes.
    For each renewed subscription, re-fetches it from Adobe to read the
    post-renewal `renewedQuantity` (only populated between the renewal and
    the subscription's anniversary date — never the plan's requested
    renewal_quantity, which can differ from what Adobe actually committed)
    and PATCHes autoRenewal to enabled=True with renewalQuantity set to
    that value, so the stored auto-renewal preference reflects what was
    just renewed. Scoped to only the subscriptions renewed by this order —
    never the full customer subscription list — so it can't clobber an
    auto-renewal preference a customer explicitly turned off on another
    subscription. Idempotent: a retry re-fetches and reapplies the same
    value.
    """

    def __call__(self, client, context, next_step):
        """Normalise autoRenewal for the plan's renewed subscriptions."""
        adobe_client = get_adobe_client()
        renewing = [plan for plan in context.renewal_plan_subscriptions if plan["renew"]]
        for plan in renewing:
            if not self._normalize(client, adobe_client, context, plan):
                return

        next_step(client, context)

    def _normalize(self, client, adobe_client, context, plan):
        subscription_id = plan["subscription_id"]
        try:
            subscription = adobe_client.get_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                subscription_id,
            )
        except AdobeAPIError as error:
            return self._fail(client, context, subscription_id, error)

        renewed_quantity = subscription.get(Param.RENEWED_QUANTITY.value)
        if renewed_quantity is None:
            logger.info(
                "%s: subscription %s has no renewedQuantity yet, skipping normalisation",
                context,
                subscription_id,
            )
            return True

        try:
            adobe_client.update_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                subscription_id,
                auto_renewal=True,
                quantity=renewed_quantity,
            )
        except AdobeAPIError as error:
            return self._fail(client, context, subscription_id, error)

        logger.info(
            "%s: autoRenewal normalised for subscription %s (renewalQuantity=%s)",
            context,
            subscription_id,
            renewed_quantity,
        )
        return True

    def _fail(self, client, context, subscription_id, error):
        logger.warning(
            "%s: failed to normalise autoRenewal for subscription %s: %s",
            context,
            subscription_id,
            error,
        )
        switch_order_to_failed(
            client,
            context.order,
            ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED.to_dict(
                subscription_id=subscription_id,
                error=error.message,
            ),
        )
        return False


class DisableLapsingSubscriptions(Step):
    """
    Disable auto-renewal for the plan's lapsing subscriptions (renew = false).

    Runs once the renew-now RENEWAL order has committed, so the subtractive
    operation never precedes the additive one. A subscription already
    disabled is skipped (using the snapshot SetupRenewalPlan took before any
    mutation), so retries are safe.
    """

    def __call__(self, client, context, next_step):
        """Disable auto-renewal for the plan's lapsing subscriptions."""
        adobe_client = get_adobe_client()
        for plan in context.renewal_plan_subscriptions:
            if plan["renew"] or not plan["snapshot"]["enabled"]:
                continue

            if not self._disable(client, adobe_client, context, plan):
                return

        next_step(client, context)

    def _disable(self, client, adobe_client, context, plan):
        try:
            adobe_client.update_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                plan["subscription_id"],
                auto_renewal=False,
            )
        except AdobeAPIError as error:
            logger.warning(
                "%s: failed to disable auto-renewal for subscription %s: %s",
                context,
                plan["subscription_id"],
                error,
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED.to_dict(
                    subscription_id=plan["subscription_id"],
                    error=error.message,
                ),
            )
            return False

        logger.info(
            "%s: auto-renewal disabled for subscription %s", context, plan["subscription_id"]
        )
        return True


def fulfill_renewal_now_order(client, order):
    """
    Fulfills a change order that carries a renew-now renewal payload.

    The plan's renewing subscriptions are validated with a PREVIEW_RENEWAL
    and committed as an actual Adobe RENEWAL order, invoiced immediately.
    Once it completes, the renewed subscriptions (renew = true) have their
    autoRenewal normalised and the plan's lapsing subscriptions
    (renew = false) have their auto-renewal disabled.

    Args:
        client (MPTClient): An instance of the MPT client used for communication
        with the MPT system.
        order (dict): The MPT order representing the renewal order to be fulfilled.

    Returns:
        None
    """
    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(TEMPLATE_NAME_CHANGE),
        SetupDueDate(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        UpdateAgreementParamsVisibility(),
        ValidateRenewalWindow(),
        SetupRenewalPlan(),
        PreviewRenewalNowOrder(),
        SubmitRenewalNowOrder(),
        NormalizeRenewedSubscriptions(),
        DisableLapsingSubscriptions(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        SetSubscriptionTemplate(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
