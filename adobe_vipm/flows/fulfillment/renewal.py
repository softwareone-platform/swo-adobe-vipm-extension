"""
This module contains the logic to implement the at-anniversary renewal fulfillment flow.

It exposes a single function that is the entrypoint for change orders that
carry a renewal payload built by the renewal wizard. The plan is applied to
Adobe as deferred auto-renewal preferences that take effect at the coterm
date: no Adobe order is placed and nothing is invoiced until the anniversary.

The plan is applied in a fixed additive-before-subtractive order so the
running renewing aggregate never dips below the 3YC committed minimum:
the plan is validated with a single PREVIEW_RENEWAL, the net-new scheduled
subscriptions are created first, then the existing subscriptions are patched
(enable, increase, decrease, disable, in that order).
"""

import datetime as dt
import logging

from mpt_extension_sdk.mpt_http.mpt import create_subscription

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW_RENEWAL,
    AdobeSubscriptionStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.airtable.models import create_discount_redemptions
from adobe_vipm.flows.constants import (
    ERR_RENEWAL_NET_NEW_FAILED,
    ERR_RENEWAL_PREVIEW_FAILED,
    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED,
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
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_order_line_by_sku,
    get_subscription_by_line_and_item_id,
    notify_not_updated_subscriptions,
)
from adobe_vipm.flows.utils.deployment import get_deployment_id
from adobe_vipm.flows.utils.parameter import update_fulfillment_parameter_value
from adobe_vipm.notifications import send_exception
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


class PreviewRenewal(Step):
    """
    Validate the renewal plan with a single PREVIEW_RENEWAL order.

    The preview is the authoritative source of discount-code validation and
    runs before any mutation is applied to Adobe, so a rejection fails the
    order without anything to reverse.
    """

    def __call__(self, client, context, next_step):
        """Validate the renewal plan with a single PREVIEW_RENEWAL order."""
        line_items = self._build_line_items(context)
        if not line_items:
            logger.info("%s: no renewing subscriptions, skipping renewal preview", context)
        elif not self._validate_preview(client, context, line_items):
            return

        next_step(client, context)

    def _validate_preview(self, client, context, line_items):
        adobe_client = get_adobe_client()
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
                ERR_RENEWAL_PREVIEW_FAILED.to_dict(error=error.message),
            )
            return False

        logger.info(
            "%s: renewal preview validated for %s subscription(s)",
            context,
            len(line_items),
        )
        return True

    def _build_line_items(self, context):
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


class CreateNetNewSubscriptions(Step):
    """
    Create the scheduled Adobe subscriptions for the net-new products of the plan.

    Runs before any auto-renewal update so the additive operations always
    precede the subtractive ones and the renewing aggregate never dips below
    the 3YC committed minimum. The step is idempotent: a scheduled (1009)
    subscription already holding the offer is reused instead of re-created,
    and its auto-renewal is restored to the plan state when a previous
    reversal disabled it.
    """

    def __call__(self, client, context, next_step):
        """Create the scheduled Adobe subscriptions for the net-new products of the plan."""
        adobe_client = get_adobe_client()
        for net_new_item in context.renewal_payload.get("netNewItems", []):
            if not self._resolve_net_new_subscription(adobe_client, client, context, net_new_item):
                return

        next_step(client, context)

    def _resolve_net_new_subscription(self, adobe_client, client, context, net_new_item):
        """Reuse or create the scheduled subscription of a net-new item, False on failure."""
        offer_id = net_new_item["offerId"]
        existing = self._find_scheduled_subscription(context, offer_id)
        if existing:
            logger.info(
                "%s: scheduled subscription %s already exists for offer %s",
                context,
                existing["subscriptionId"],
                offer_id,
            )
            return self._reuse_scheduled_subscription(
                adobe_client, client, context, net_new_item, existing
            )

        try:
            subscription = adobe_client.create_customer_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                offer_id,
                net_new_item["quantity"],
                deployment_id=get_deployment_id(context.order),
                recommendation_tracker_id=(
                    context.renewal_payload.get("recommendationTrackerId") or None
                ),
            )
        except AdobeAPIError as error:
            logger.warning(
                "%s: failed to create scheduled subscription for offer %s: %s",
                context,
                offer_id,
                error,
            )
            disable_net_new_subscriptions(adobe_client, context)
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_NET_NEW_FAILED.to_dict(offer_id=offer_id, error=error.message),
            )
            return False

        logger.info(
            "%s: scheduled subscription %s created for offer %s",
            context,
            subscription["subscriptionId"],
            offer_id,
        )
        context.renewal_net_new_subscriptions[offer_id] = subscription
        context.renewal_created_net_new_subscriptions[offer_id] = subscription
        return True

    def _reuse_scheduled_subscription(self, adobe_client, client, context, net_new_item, existing):
        """
        Reuse a scheduled subscription, restoring its auto-renewal plan state when needed.

        A scheduled subscription neutralized by a previous reversal (auto-renewal
        disabled) or holding a stale renewal quantity is patched back to the plan
        state; one already in place is reused as-is. A re-enabled subscription is
        tracked as mutated-by-this-run so a later reversal neutralizes it again.
        """
        offer_id = net_new_item["offerId"]
        auto_renewal = existing.get("autoRenewal", {})
        quantity = net_new_item["quantity"]
        if (
            auto_renewal.get("enabled", False)
            and auto_renewal.get(Param.RENEWAL_QUANTITY.value) == quantity
        ):
            context.renewal_net_new_subscriptions[offer_id] = existing
            return True

        try:
            subscription = adobe_client.update_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                existing["subscriptionId"],
                auto_renewal=True,
                quantity=quantity,
            )
        except AdobeAPIError as error:
            logger.warning(
                "%s: failed to restore scheduled subscription %s for offer %s: %s",
                context,
                existing["subscriptionId"],
                offer_id,
                error,
            )
            disable_net_new_subscriptions(adobe_client, context)
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_NET_NEW_FAILED.to_dict(offer_id=offer_id, error=error.message),
            )
            return False

        logger.info(
            "%s: scheduled subscription %s re-enabled for offer %s (quantity=%s)",
            context,
            existing["subscriptionId"],
            offer_id,
            quantity,
        )
        context.renewal_net_new_subscriptions[offer_id] = subscription
        context.renewal_created_net_new_subscriptions[offer_id] = subscription
        return True

    def _find_scheduled_subscription(self, context, offer_id):
        return next(
            (
                subscription
                for subscription in context.adobe_customer_subscriptions
                if subscription["status"] == AdobeSubscriptionStatus.SCHEDULED
                and get_partial_sku(subscription["offerId"]) == get_partial_sku(offer_id)
            ),
            None,
        )


class UpdateRenewalSubscriptions(Step):
    """
    Apply the plan's auto-renewal preferences to the existing Adobe subscriptions.

    The PATCH operations run in a fixed additive-before-subtractive order
    (enable, increase, decrease, disable) so the renewing aggregate never
    dips below the 3YC committed minimum. Each subscription state was
    snapshotted before mutating; on a confirmed Adobe failure the applied
    operations are reversed (restore-to-known-good, best effort) and the
    scheduled net-new subscriptions are neutralized by disabling their
    auto-renewal. Operations whose target state is already in place are
    skipped, so retries are safe.
    """

    def __call__(self, client, context, next_step):
        """Apply the plan's auto-renewal preferences to the existing Adobe subscriptions."""
        adobe_client = get_adobe_client()
        applied = []
        for operation in self._build_operations(context):
            try:
                self._apply_operation(adobe_client, context, operation)
            except AdobeAPIError as error:
                logger.warning(
                    "%s: failed to update auto-renewal for subscription %s: %s",
                    context,
                    operation["subscription_id"],
                    error,
                )
                self._reverse_applied_operations(adobe_client, context, applied)
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED.to_dict(
                        subscription_id=operation["subscription_id"],
                        error=error.message,
                    ),
                )
                return
            applied.append(operation)

        logger.info(
            "%s: auto-renewal preferences applied (%s operation(s))",
            context,
            len(applied),
        )
        next_step(client, context)

    # The list order is the fulfillment invariant: additive before subtractive.
    operation_kinds = ("enable", "increase", "decrease", "disable")

    def _build_operations(self, context):
        """Classify the plan into PATCH operations, additive before subtractive."""
        buckets = {kind: [] for kind in self.operation_kinds}
        for plan in context.renewal_plan_subscriptions:
            classified = self._classify_plan(plan)
            if classified:
                kind, operation = classified
                buckets[kind].append(operation)

        return [operation for kind in self.operation_kinds for operation in buckets[kind]]

    def _classify_plan(self, plan):
        """Return the (kind, operation) of a plan entry, or None when already in place."""
        snapshot = plan["snapshot"]
        if not plan["renew"]:
            return self._classify_lapsing(plan, snapshot)

        if self._is_renewal_in_place(plan, snapshot):
            return None

        operation = {
            "subscription_id": plan["subscription_id"],
            "enabled": True,
            "quantity": plan["renewal_quantity"],
            "flex_discount_codes": plan["flex_discount_codes"],
            "snapshot": snapshot,
        }
        kind = "enable"
        if snapshot["enabled"]:
            is_increase = plan["renewal_quantity"] >= (snapshot["renewal_quantity"] or 0)
            kind = "increase" if is_increase else "decrease"
        return kind, operation

    def _classify_lapsing(self, plan, snapshot):
        """Return the disable operation of a lapsing plan entry, or None if already disabled."""
        if not snapshot["enabled"]:
            return None
        return "disable", {
            "subscription_id": plan["subscription_id"],
            "enabled": False,
            "quantity": None,
            "flex_discount_codes": None,
            "snapshot": snapshot,
        }

    def _is_renewal_in_place(self, plan, snapshot):
        """Return True when the subscription already holds the target renewal state."""
        return (
            snapshot["enabled"]
            and snapshot["renewal_quantity"] == plan["renewal_quantity"]
            and sorted(snapshot["flex_discount_codes"]) == sorted(plan["flex_discount_codes"])
        )

    def _apply_operation(self, adobe_client, context, operation):
        adobe_client.update_subscription(
            context.authorization_id,
            context.adobe_customer_id,
            operation["subscription_id"],
            auto_renewal=operation["enabled"],
            quantity=operation["quantity"],
            flex_discount_codes=operation["flex_discount_codes"] or None,
        )
        logger.info(
            "%s: auto-renewal set for subscription %s (enabled=%s, quantity=%s)",
            context,
            operation["subscription_id"],
            operation["enabled"],
            operation["quantity"],
        )

    def _reverse_applied_operations(self, adobe_client, context, applied):
        """Restore the snapshotted state of the already-patched subscriptions, best effort."""
        not_restored = []
        for operation in reversed(applied):
            snapshot = operation["snapshot"]
            try:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    operation["subscription_id"],
                    auto_renewal=snapshot["enabled"],
                    quantity=snapshot["renewal_quantity"],
                    flex_discount_codes=snapshot["flex_discount_codes"],
                )
            except AdobeAPIError:
                # A restore that is no longer valid is logged and skipped, not
                # treated as fatal; the remaining reversal steps still proceed.
                logger.exception(
                    "%s: failed to restore auto-renewal snapshot for subscription %s",
                    context,
                    operation["subscription_id"],
                )
                not_restored.append({
                    "subscription_vendor_id": operation["subscription_id"],
                    "old_quantity": snapshot["renewal_quantity"],
                    "new_quantity": operation["quantity"],
                })
        disable_net_new_subscriptions(adobe_client, context)
        if not_restored:
            notify_not_updated_subscriptions(
                context.order["id"],
                "Error rolling back the auto-renewal preferences of the renewal order",
                not_restored,
                context.product_id,
            )


def disable_net_new_subscriptions(adobe_client, context):
    """
    Neutralize the net-new subscriptions created by this run by disabling their auto-renewal.

    A scheduled (1009) subscription cannot be deleted: disabling its
    auto-renewal prevents it from activating at the anniversary, which is the
    documented reversal path. Only the subscriptions created or re-enabled
    during this run are touched: a reused scheduled subscription whose
    auto-renewal was already in place was not mutated by this run, so its
    auto-renewal is preserved. Failures are logged and skipped (best effort).
    """
    for offer_id, subscription in context.renewal_created_net_new_subscriptions.items():
        try:
            adobe_client.update_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                subscription["subscriptionId"],
                auto_renewal=False,
            )
        except AdobeAPIError:
            logger.exception(
                "%s: failed to disable auto-renewal of scheduled subscription %s (offer %s)",
                context,
                subscription["subscriptionId"],
                offer_id,
            )


class CreateNetNewMptSubscriptions(Step):
    """
    Create the MPT subscriptions for the scheduled net-new Adobe subscriptions.

    Each subscription is attached to its net-new order line and carries the
    future start date: it is created directly in Active status and activates
    commercially only at the anniversary. The step is idempotent: a line that
    already holds a subscription is skipped.
    """

    def __call__(self, client, context, next_step):
        """Create the MPT subscriptions for the scheduled net-new Adobe subscriptions."""
        for offer_id, adobe_subscription in context.renewal_net_new_subscriptions.items():
            order_line = get_order_line_by_sku(context.order, offer_id)
            if not order_line:
                logger.warning(
                    "%s: no order line found for net-new offer %s, skipping subscription creation",
                    context,
                    offer_id,
                )
                continue

            existing = get_subscription_by_line_and_item_id(
                context.order["subscriptions"],
                order_line["item"]["id"],
                order_line["id"],
            )
            if existing:
                logger.info(
                    "%s: subscription %s already exists for net-new offer %s",
                    context,
                    existing["id"],
                    offer_id,
                )
                continue

            subscription = create_subscription(
                client,
                context.order_id,
                self._build_subscription_data(offer_id, adobe_subscription, order_line),
            )
            logger.info(
                "%s: subscription %s (%s) created for net-new offer %s",
                context,
                adobe_subscription["subscriptionId"],
                subscription["id"],
                offer_id,
            )

        next_step(client, context)

    def _build_subscription_data(self, offer_id, adobe_subscription, order_line):
        auto_renewal = adobe_subscription.get("autoRenewal", {})
        renewal_quantity = auto_renewal.get(Param.RENEWAL_QUANTITY.value)
        renewal_date = adobe_subscription.get("renewalDate")
        start_date = renewal_date or adobe_subscription["creationDate"]
        item_name = order_line["item"]["name"]
        return {
            "name": f"Subscription for {item_name}",
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": Param.ADOBE_SKU.value,
                        "value": offer_id,
                    },
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription.get(Param.CURRENT_QUANTITY.value, 0)),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": "" if renewal_quantity is None else str(renewal_quantity),
                    },
                    {
                        "externalId": Param.RENEWAL_DATE.value,
                        "value": "" if renewal_date is None else str(renewal_date),
                    },
                ]
            },
            "externalIds": {
                "vendor": adobe_subscription["subscriptionId"],
            },
            "lines": [
                {
                    "id": order_line["id"],
                },
            ],
            "startDate": start_date,
            "commitmentDate": adobe_subscription.get("renewalDate"),
            "autoRenew": auto_renewal.get("enabled", True),
        }


class RecordFlexDiscounts(Step):
    """
    Record the discount codes applied by the plan on the order.

    On confirmed completion the used flexDiscountCodes are written to the
    order's flexibleDiscounts fulfillment parameter, persisted by the
    CompleteOrder step that follows.
    """

    def __call__(self, client, context, next_step):
        """Record the discount codes applied by the plan on the order."""
        flex_discounts = [
            {
                "offerId": plan["offer_id"],
                "subscriptionId": plan["subscription_id"],
                "flexDiscountCode": plan["flex_discount_codes"],
            }
            for plan in context.renewal_plan_subscriptions
            if plan["renew"] and plan["flex_discount_codes"]
        ]
        if flex_discounts:
            context.order = update_fulfillment_parameter_value(
                context.order,
                Param.FLEXIBLE_DISCOUNTS.value,
                flex_discounts,
            )
            logger.info(
                "%s: recorded %s flex discount entry(ies) on the order",
                context,
                len(flex_discounts),
            )
        next_step(client, context)


class RecordDiscountRedemptions(Step):
    """
    Record the flex discount codes redeemed by the plan on the AirTable redemptions table.

    Runs after the order has been completed, so a fulfillment retry of an
    earlier failure never duplicates rows. One row is written per unique code
    applied by the plan. The write is best effort: the order is already
    completed, so an AirTable failure is logged and notified for a manual
    backfill instead of failing the order.
    """

    def __call__(self, client, context, next_step):
        """Record the redeemed flex discount codes on the AirTable redemptions table."""
        redeemed_codes = list(
            dict.fromkeys(
                code
                for plan in context.renewal_plan_subscriptions
                if plan["renew"]
                for code in plan["flex_discount_codes"]
            )
        )
        if redeemed_codes:
            self._record_redemptions(context, redeemed_codes)
        else:
            logger.info(
                "%s: no flex discount codes redeemed by the plan, "
                "skipping the redemptions recording",
                context,
            )
        next_step(client, context)

    def _record_redemptions(self, context, redeemed_codes):
        logger.info(
            "%s: recording %s discount redemption(s) on AirTable: %s",
            context,
            len(redeemed_codes),
            ", ".join(redeemed_codes),
        )
        redeemed_at = dt.datetime.now(tz=dt.UTC)
        redemptions = [
            {
                "code": code,
                "customer_id": context.adobe_customer_id,
                "order_id": context.order_id,
                "redeemed_at": redeemed_at,
            }
            for code in redeemed_codes
        ]
        try:
            create_discount_redemptions(redemptions)
        except Exception:
            logger.exception(
                "%s: failed to record %s discount redemption(s) on AirTable",
                context,
                len(redemptions),
            )
            joined_codes = ", ".join(redeemed_codes)
            send_exception(
                f"Error recording the discount redemptions of order {context.order_id}",
                "The renewal order has been completed but the redeemed flex discount "
                "codes could not be recorded on the AirTable Discount Redemptions "
                "table and must be backfilled manually:\n"
                f"- Customer ID: {context.adobe_customer_id}\n"
                f"- Order ID: {context.order_id}\n"
                f"- Codes: {joined_codes}\n",
            )
            return
        logger.info(
            "%s: recorded %s discount redemption(s) on AirTable",
            context,
            len(redemptions),
        )


def fulfill_renewal_order(client, order):
    """
    Fulfills a change order that carries an at-anniversary renewal payload.

    It validates the plan with a PREVIEW_RENEWAL order, creates the scheduled
    net-new subscriptions first (additive before subtractive, so the 3YC
    committed minimum is never breached) and then applies the auto-renewal
    preferences to the existing subscriptions (enable, increase, decrease,
    disable). Nothing is invoiced and no Adobe order is placed: the plan
    takes effect at the coterm date.

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
        CreateNetNewSubscriptions(),
        UpdateRenewalSubscriptions(),
        CreateNetNewMptSubscriptions(),
        RecordFlexDiscounts(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        RecordDiscountRedemptions(),
        SetSubscriptionTemplate(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
