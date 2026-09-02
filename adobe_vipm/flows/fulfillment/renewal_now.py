"""
This module contains the logic to implement the renew-now fulfillment flow.

It exposes a single function that is the entrypoint for change orders that
carry a renewal payload built by the renewal wizard with renewalPath "now"
(see flows/fulfillment/renewal.py for the at-anniversary path). The
renewing subscriptions are committed as an actual Adobe RENEWAL order,
invoiced immediately, mirroring how the PURCHASE flow turns its PREVIEW
order into a NEW order: validate with PREVIEW_RENEWAL, then resubmit the
line items it returns as the real order. A renewing subscription already
committed in a previous renewal order (renewedQuantity populated) with no
requested quantity change is excluded from both. Once the order completes, the
renewed subscriptions (renew = true) have their autoRenewal normalised
(enabled=on, renewalQuantity taken from Adobe's post-renewal
renewedQuantity) and the plan's lapsing subscriptions (renew = false)
have their auto-renewal disabled. A lapsing subscription that was already
committed in a previous RENEWAL order (its pre-mutation snapshot carries a
renewedQuantity) additionally has that order's line returned via a RETURN
order, so the customer is not left paying for a renewal that is being
toggled off. Once the order is completed, the flex discount codes redeemed
by the plan are recorded on the AirTable redemptions table.

Net-new items are not handled yet.
"""

import logging
from operator import itemgetter

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RENEWAL,
    UNRECOVERABLE_ORDER_STATUSES,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_RENEWAL_ORDER_FAILED,
    ERR_RENEWAL_PREVIEW_FAILED,
    ERR_RENEWAL_RETURN_FAILED,
    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    TEMPLATE_NAME_CHANGE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.renewal import RecordDiscountRedemptions
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
    get_flex_discount_limit_error,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils.parameter import set_adobe_order_ids_created_parameter
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def _is_already_renewed(plan):
    """
    Return True for a renewing entry already committed in a previous renewal order.

    A plan entry with renew=true but no requested renewal quantity whose
    Adobe subscription already carries a renewedQuantity (snapshotted by
    SetupRenewalPlan before any mutation) was committed by a previous
    RENEWAL order and requests no change, so there is nothing to submit
    for it.
    """
    return not plan["renewal_quantity"] and plan["snapshot"]["renewed_quantity"] is not None


def _build_renewing_line_items(context):
    """
    Build PREVIEW_RENEWAL/RENEWAL line items for the plan's renewing subscriptions.

    Renewing subscriptions already committed in a previous renewal order
    with no requested quantity change are excluded — see _is_already_renewed.
    """
    line_items = []
    renewing = [
        plan
        for plan in context.renewal_plan_subscriptions
        if plan["renew"] and not _is_already_renewed(plan)
    ]
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


def _get_committed_flex_discount_codes(preview_line_item):
    """
    Extract the flex discount code to commit from a PREVIEW_RENEWAL response line item.

    Adobe accepts at most one flexible discount code per line item (it rejects
    more with error 2147), so instead of blindly taking the first element the
    discounts the preview did not apply successfully are dropped and only one
    surviving code is submitted, logging what is being discarded.
    """
    flex_discounts = preview_line_item.get("flexDiscounts") or []
    successful = (fd for fd in flex_discounts if fd.get("result", "SUCCESS") == "SUCCESS")
    codes = [fd["code"] for fd in successful]
    discarded = [fd["code"] for fd in flex_discounts if fd["code"] not in codes]
    if discarded:
        logger.warning(
            "Dropping flex discount code(s) not applied successfully by the renewal "
            "preview for line %s: %s",
            preview_line_item.get("extLineItemNumber"),
            ", ".join(discarded),
        )
    if len(codes) > 1:
        logger.warning(
            "Renewal preview returned %s flex discounts for line %s, submitting only "
            "the first one (%s) to honour Adobe's one-code-per-line rule",
            len(codes),
            preview_line_item.get("extLineItemNumber"),
            codes[0],
        )
    return codes[:1]


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
        flex_discount_codes = _get_committed_flex_discount_codes(preview_line_item)
        if flex_discount_codes:
            line_item["flexDiscountCodes"] = flex_discount_codes
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
                recommendation_tracker_id=(
                    context.renewal_payload.get("recommendationTrackerId") or None
                ),
            )
        except AdobeAPIError as error:
            logger.warning("%s: renewal preview failed: %s", context, error)
            switch_order_to_failed(
                client,
                context.order,
                get_flex_discount_limit_error(error)
                or ERR_RENEWAL_PREVIEW_FAILED.to_dict(error=error.message),
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

    Net-new items are not handled by this step.
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
                recommendation_tracker_id=(
                    context.renewal_payload.get("recommendationTrackerId") or None
                ),
            )
        except AdobeAPIError as error:
            logger.warning("%s: renewal order failed: %s", context, error)
            switch_order_to_failed(
                client,
                context.order,
                get_flex_discount_limit_error(error)
                or ERR_RENEWAL_ORDER_FAILED.to_dict(error=error.message),
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


class ReturnPreviousRenewalOrders(Step):
    """
    Return the previous RENEWAL order lines of the plan's lapsing subscriptions.

    A lapsing subscription (renew = false) whose pre-mutation snapshot
    (taken by SetupRenewalPlan, before this order commits anything) carries
    a renewedQuantity was already committed in a previous RENEWAL order
    placed within the renewal window. Disabling its auto-renewal is not
    enough — the already-paid renewal must be undone, so this step submits
    a RETURN order referencing that previous RENEWAL order, returning only
    the lapsing subscription's line (other lines of that order stay
    renewed). Runs after SubmitRenewalNowOrder so the additive operation
    always precedes the subtractive one.

    Idempotent: RETURN orders created by this MPT order are detected by
    their external reference prefix and reused instead of re-submitted. A
    RETURN order still pending on Adobe's side keeps the MPT order in
    Processing to be retried on the next fulfillment attempt.
    """

    def __call__(self, client, context, next_step):
        """Return the previous RENEWAL order lines of the plan's lapsing subscriptions."""
        lapsing_renewed = [
            plan
            for plan in context.renewal_plan_subscriptions
            if not plan["renew"] and plan["snapshot"]["renewed_quantity"] is not None
        ]
        if not lapsing_renewed:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        renewal_orders = self._get_completed_renewal_orders(adobe_client, context)
        existing_return_orders = adobe_client.get_return_orders_by_external_reference(
            context.authorization_id,
            context.adobe_customer_id,
            context.order_id,
        )

        return_orders = []
        for plan in lapsing_renewed:
            return_order = self._return_previous_renewal(
                client, adobe_client, context, plan, renewal_orders, existing_return_orders
            )
            if return_order is None:
                return
            return_orders.append(return_order)

        if not self._ensure_not_pending_return_orders(context, return_orders):
            return

        next_step(client, context)

    def _get_completed_renewal_orders(self, adobe_client, context):
        orders = adobe_client.get_orders(
            context.authorization_id,
            context.adobe_customer_id,
            filters={
                "order-type": ORDER_TYPE_RENEWAL,
                "status": AdobeOrderStatus.COMPLETE,
            },
        )
        return sorted(orders, key=itemgetter("creationDate"), reverse=True)

    def _return_previous_renewal(  # noqa: WPS211
        self, client, adobe_client, context, plan, renewal_orders, existing_return_orders
    ):
        subscription_id = plan["subscription_id"]
        existing_returns = existing_return_orders.get(get_partial_sku(plan["offer_id"]))
        if existing_returns:
            logger.info(
                "%s: return order %s already exists for subscription %s",
                context,
                existing_returns[0]["orderId"],
                subscription_id,
            )
            return existing_returns[0]

        returning_order, returning_line = self._find_previous_renewal_line(
            context, renewal_orders, subscription_id
        )
        if returning_order is None:
            logger.warning(
                "%s: no previous renewal order found for subscription %s",
                context,
                subscription_id,
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_RETURN_FAILED.to_dict(
                    subscription_id=subscription_id,
                    error="previous renewal order not found",
                ),
            )
            return None

        return self._create_return_order(
            client, adobe_client, context, subscription_id, returning_order, returning_line
        )

    def _find_previous_renewal_line(self, context, renewal_orders, subscription_id):
        for order in renewal_orders:
            if order["externalReferenceId"] == context.order_id:
                continue
            for line_item in order["lineItems"]:
                if line_item.get("subscriptionId") == subscription_id:
                    return order, line_item
        return None, None

    def _create_return_order(  # noqa: WPS211
        self, client, adobe_client, context, subscription_id, returning_order, returning_line
    ):
        try:
            return_order = adobe_client.create_return_order(
                context.authorization_id,
                context.adobe_customer_id,
                returning_order,
                returning_line,
                context.order_id,
                returning_line.get("deploymentId"),
            )
        except AdobeAPIError as error:
            logger.warning(
                "%s: failed to return renewal order %s for subscription %s: %s",
                context,
                returning_order["orderId"],
                subscription_id,
                error,
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_RETURN_FAILED.to_dict(
                    subscription_id=subscription_id,
                    error=error.message,
                ),
            )
            return None

        logger.info(
            "%s: return order %s created for subscription %s against renewal order %s",
            context,
            return_order["orderId"],
            subscription_id,
            returning_order["orderId"],
        )
        context.order = set_adobe_order_ids_created_parameter(context, [return_order["orderId"]])
        update_order(client, context.order_id, parameters=context.order["parameters"])
        return return_order

    def _ensure_not_pending_return_orders(self, context, return_orders):
        pending_orders = [
            return_order["orderId"]
            for return_order in return_orders
            if return_order["status"] != AdobeOrderStatus.COMPLETE
        ]
        if pending_orders:
            logger.info(
                "%s: return order(s) %s still pending",
                context,
                ", ".join(pending_orders),
            )
            return False
        return True


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

    Renewing subscriptions already committed in a previous renewal order
    with no requested quantity change (see _is_already_renewed) are
    excluded: this order did not renew them, so they keep whatever that
    previous renewal order set.
    """

    def __call__(self, client, context, next_step):
        """Normalise autoRenewal for the plan's renewed subscriptions."""
        adobe_client = get_adobe_client()
        renewing = [
            plan
            for plan in context.renewal_plan_subscriptions
            if plan["renew"] and not _is_already_renewed(plan)
        ]
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
    Once it completes, lapsing subscriptions that were already committed in
    a previous RENEWAL order have that order's line returned, the renewed
    subscriptions (renew = true) have their autoRenewal normalised and the
    plan's lapsing subscriptions (renew = false) have their auto-renewal
    disabled.

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
        ReturnPreviousRenewalOrders(),
        NormalizeRenewedSubscriptions(),
        DisableLapsingSubscriptions(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        RecordDiscountRedemptions(),
        SetSubscriptionTemplate(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
