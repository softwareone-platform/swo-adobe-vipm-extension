"""
This module contains the logic to implement the at-anniversary renewal fulfillment flow.

It exposes a single function that is the entrypoint for change orders that
carry a renewal payload built by the renewal wizard. The plan is applied to
Adobe as deferred auto-renewal preferences that take effect at the coterm
date: no Adobe order is placed and nothing is invoiced until the anniversary.

The plan is applied in a fixed order: auto-renewal is enabled where needed,
the discount codes are stored on the existing subscriptions as one batch and
confirmed with Adobe (which validates codes only through PREVIEW_RENEWAL) before
any net-new scheduled subscription is created, then the renewal quantities are
increased, decreased and disabled. That order is additive before subtractive,
so the running renewing aggregate never dips below the 3YC committed minimum;
the ordering only protects the intermediate states, so before any mutation the
resulting renewing aggregate is also validated numerically against the
committed minimum (Validate3YCRenewalFloor, shared with the renew-now flow).
Every change is snapshotted first, and a confirmed failure at any step restores
all of them and neutralizes the net-new subscriptions this run created.
"""

import datetime as dt
import logging

from mpt_extension_sdk.mpt_http.mpt import create_subscription

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW_RENEWAL,
    AdobeErrorCode,
    AdobeSubscriptionStatus,
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeTransportError
from adobe_vipm.airtable.models import (
    create_client_discount_codes,
    create_discount_redemptions,
    get_existing_discount_codes,
)
from adobe_vipm.flows.constants import (
    ERR_COMMITMENT_3YC_VALIDATION,
    ERR_RENEWAL_FLEX_DISCOUNT_REFUSED,
    ERR_RENEWAL_NET_NEW_FAILED,
    ERR_RENEWAL_PREVIEW_FAILED,
    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED,
    MARKET_SEGMENTS,
    MPT_ORDER_STATUS_COMPLETED,
    TEMPLATE_NAME_CHANGE,
    OrderType,
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
    get_configuration_template_name,
    get_flex_discount_limit_error,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext, Validate3YCCommitment
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_order_line_by_sku,
    get_subscription_by_line_and_item_id,
    is_3yc_commitment_ending_before_coterm,
    notify_not_updated_subscriptions,
)
from adobe_vipm.flows.utils.deployment import get_deployment_id
from adobe_vipm.flows.utils.parameter import update_fulfillment_parameter_value
from adobe_vipm.notifications import send_exception
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

logger = logging.getLogger(__name__)

# The only result for which Adobe honours a flexible discount code on a line.
FLEX_DISCOUNT_SUCCESS_RESULT = "SUCCESS"

# The committed minimum binds only while the commitment is in force.
IN_FORCE_COMMITMENT_STATUSES = frozenset((
    ThreeYearCommitmentStatus.COMMITTED,
    ThreeYearCommitmentStatus.ACTIVE,
))


def find_scheduled_subscription(subscriptions, offer_id):
    """Return the scheduled (1009) subscription holding the offer, or None."""
    return next(
        (
            subscription
            for subscription in subscriptions
            if subscription.get("status") == AdobeSubscriptionStatus.SCHEDULED
            and get_partial_sku(subscription["offerId"]) == get_partial_sku(offer_id)
        ),
        None,
    )


def record_renewal_change(context, plan, *, codes_changed=False):
    """
    Remember that this run changed an existing subscription, for the reversal.

    Every change is reversed to the subscription's pre-mutation snapshot, so one
    entry per subscription is enough; a later change to the same subscription
    only widens what the reversal restores (its codes). Callers record the
    change *before* the Adobe call: ``update_subscription`` PATCHes and then
    re-reads the subscription, so it can raise after Adobe applied the change
    (a failed re-read, or a response timeout on a committed PATCH). Restoring a
    subscription the call did not change is harmless: it re-sends the
    snapshot's own values, or a reset on a subscription that holds no code.
    """
    for change in context.renewal_applied_changes:
        if change["subscription_id"] == plan["subscription_id"]:
            change["codes_changed"] = change["codes_changed"] or codes_changed
            return
    context.renewal_applied_changes.append({
        "subscription_id": plan["subscription_id"],
        "snapshot": plan["snapshot"],
        "new_quantity": plan["renewal_quantity"],
        "codes_changed": codes_changed,
    })


def reverse_renewal_changes(adobe_client, context):
    """
    Restore every subscription this run changed to its snapshot, then neutralize net-new.

    Runs on a confirmed failure at any step that mutates Adobe. A subscription
    whose codes this run changed gets its snapshot codes back; when the snapshot
    had none, the codes are cleared with the reset flag, because Adobe ignores an
    empty list. Failures, including transport failures, are logged and
    notified, and the reversal carries on (best effort). Everything reversed is
    forgotten, so a second reversal of the same run changes nothing.
    """
    not_restored = []
    for change in reversed(context.renewal_applied_changes):
        snapshot = change["snapshot"]
        snapshot_codes = snapshot["flex_discount_codes"]
        try:
            adobe_client.update_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                change["subscription_id"],
                auto_renewal=snapshot["enabled"],
                quantity=snapshot["renewal_quantity"],
                flex_discount_codes=snapshot_codes or None,
                reset_flex_discount_codes=change["codes_changed"] and not snapshot_codes,
            )
        except (AdobeAPIError, AdobeTransportError):
            logger.exception(
                "%s: failed to restore auto-renewal snapshot for subscription %s",
                context,
                change["subscription_id"],
            )
            not_restored.append({
                "subscription_vendor_id": change["subscription_id"],
                "old_quantity": snapshot["renewal_quantity"],
                "new_quantity": change["new_quantity"],
            })
    context.renewal_applied_changes = []
    disable_net_new_subscriptions(adobe_client, context)
    context.renewal_created_net_new_subscriptions = {}
    if not_restored:
        notify_not_updated_subscriptions(
            context.order["id"],
            "Error rolling back the auto-renewal preferences of the renewal order",
            not_restored,
            context.product_id,
        )


def fail_renewal_order(client, adobe_client, context, error):
    """Reverse everything this run changed on Adobe, then fail the order with ``error``."""
    reverse_renewal_changes(adobe_client, context)
    switch_order_to_failed(client, context.order, error)


class ReverseRenewalChangesOnError(Step):
    """
    Reverse the run's Adobe changes when a later step raises, then re-raise.

    A step that confirms a failure reverses and fails the order itself
    (``fail_renewal_order``). Any other error that escapes, such as a transport
    failure after which the order stays in processing and is retried, would
    leave the staged changes on Adobe: the retry would snapshot them as the
    customer's own, so a code this run added would survive a later rollback and
    never be recorded as redeemed. Once the order is completed its changes are
    final, and an error from the steps after it is only re-raised.
    """

    def __call__(self, client, context, next_step):
        """Run the remaining steps, reversing the run's Adobe changes if they raise."""
        try:
            next_step(client, context)
        except Exception:
            if context.order.get("status") != MPT_ORDER_STATUS_COMPLETED:
                logger.warning("%s: reversing the renewal changes after an error", context)
                reverse_renewal_changes(get_adobe_client(), context)
            raise


class EnableRenewalSubscriptions(Step):
    """
    Switch auto-renewal on for the plan's renewing subscriptions that have it off.

    The first mutation of the plan (additive, so the 3YC committed minimum is
    never breached), sending the plan's renewal quantity with it. A subscription
    already set to auto-renew is left to the later steps, so retries are safe.
    """

    def __call__(self, client, context, next_step):
        """Switch auto-renewal on for the renewing subscriptions that have it off."""
        adobe_client = get_adobe_client()
        for plan in context.renewal_plan_subscriptions:
            if not plan["renew"] or plan["snapshot"]["enabled"]:
                continue
            record_renewal_change(context, plan)
            try:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    plan["subscription_id"],
                    auto_renewal=True,
                    quantity=plan["renewal_quantity"],
                )
            except AdobeAPIError as error:
                logger.warning(
                    "%s: failed to enable auto-renewal for subscription %s: %s",
                    context,
                    plan["subscription_id"],
                    error,
                )
                fail_renewal_order(
                    client,
                    adobe_client,
                    context,
                    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED.to_dict(
                        subscription_id=plan["subscription_id"],
                        error=error.message,
                    ),
                )
                return
            logger.info(
                "%s: auto-renewal enabled for subscription %s (quantity=%s)",
                context,
                plan["subscription_id"],
                plan["renewal_quantity"],
            )

        next_step(client, context)


class ApplyRenewalDiscountCodes(Step):
    """
    Store the plan's discount codes on the renewing subscriptions, as one batch.

    Adobe does not validate a code on update-subscription, so this only stages
    the codes; ValidateRenewalDiscountCodes then asks Adobe whether it will
    honour them before anything else changes. A plan entry without codes leaves
    the codes the subscription holds untouched (inherited reusables), unless
    the customer removed them in the wizard (``clear_flex_discount_codes``),
    which clears them with the reset flag. Codes already in place are skipped,
    so retries are safe.
    """

    def __call__(self, client, context, next_step):
        """Store the plan's discount codes on the renewing subscriptions."""
        adobe_client = get_adobe_client()
        for plan in context.renewal_plan_subscriptions:
            update = self._codes_update(plan)
            if update is None:
                continue
            record_renewal_change(context, plan, codes_changed=True)
            try:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    plan["subscription_id"],
                    auto_renewal=True,
                    **update,
                )
            except AdobeAPIError as error:
                logger.warning(
                    "%s: failed to set the discount codes of subscription %s: %s",
                    context,
                    plan["subscription_id"],
                    error,
                )
                fail_renewal_order(
                    client,
                    adobe_client,
                    context,
                    get_flex_discount_limit_error(error)
                    or ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED.to_dict(
                        subscription_id=plan["subscription_id"],
                        error=error.message,
                    ),
                )
                return
            logger.info(
                "%s: discount codes of subscription %s set to %s",
                context,
                plan["subscription_id"],
                update.get("flex_discount_codes") or "none (cleared)",
            )

        next_step(client, context)

    def _codes_update(self, plan):
        """Return the update_subscription arguments for the plan's codes, or None."""
        if not plan["renew"]:
            return None
        codes = plan["flex_discount_codes"]
        stored_codes = plan["snapshot"]["flex_discount_codes"]
        if codes:
            if sorted(codes) == sorted(stored_codes):
                return None
            return {"flex_discount_codes": codes}
        if plan.get("clear_flex_discount_codes") and stored_codes:
            return {"reset_flex_discount_codes": True}
        return None


class _CodeVerdicts:
    """The plan's discount codes Adobe confirmed, and a description of each it did not."""

    def __init__(self):
        self.confirmed = set()
        self.refusals = []

    def judge(self, code, code_results, line):
        """Confirm ``code`` only when Adobe reported SUCCESS for it on ``line``."""
        result = code_results.get(code)
        if result == FLEX_DISCOUNT_SUCCESS_RESULT:
            self.confirmed.add(code)
            return
        reason = result or "not confirmed by Adobe"
        self.refusals.append(f"{code} on {line} ({reason})")

    def judge_net_new_preview(self, preview, net_new_items):
        """Judge each net-new item's codes on its preview line, matched by line number."""
        lines_by_number = {
            line_item.get("extLineItemNumber"): line_item
            for line_item in preview.get("lineItems") or []
        }
        for number, net_new_item in enumerate(net_new_items, start=1):
            code_results = preview_code_results(lines_by_number.get(number))
            for code in net_new_item["flexDiscountCodes"]:
                self.judge(code, code_results, f"new product {net_new_item['offerId']}")

    def refuse_request(self, error, net_new_items):
        """
        Record the net-new codes of a preview Adobe refused as a whole.

        Adobe refuses a net-new code by failing the whole request, naming the line
        in additionalDetails ("Line Item: N, Reason: ..."); without a line number
        every net-new code of the preview counts as refused.
        """
        refused_numbers = refused_line_numbers(error)
        for number, net_new_item in enumerate(net_new_items, start=1):
            if refused_numbers and number not in refused_numbers:
                continue
            offer_id = net_new_item["offerId"]
            self.refusals.extend(
                f"{code} on new product {offer_id} ({error.message})"
                for code in net_new_item["flexDiscountCodes"]
            )


def refused_line_numbers(error):
    """Read the line numbers Adobe named in a refusal's ``Line Item: N`` details."""
    numbers = set()
    for detail in error.details:
        head = str(detail).split(",", maxsplit=1)[0].strip()
        digits = head.removeprefix("Line Item:").strip()
        if head.startswith("Line Item:") and digits.isdigit():
            numbers.add(int(digits))
    return numbers


def find_preview_subscription_line(line_items, plan):
    """
    Find the preview line of a plan subscription.

    Matched by subscription id; when Adobe leaves it empty, by the partial SKU,
    which survives the level change Adobe may apply at renewal, as long as only
    one line carries that product. No match returns None (nothing confirmed).
    """
    for line_item in line_items:
        if line_item.get("subscriptionId") == plan["subscription_id"]:
            return line_item
    partial_sku = get_partial_sku(plan["offer_id"])
    candidates = [
        candidate
        for candidate in line_items
        if not candidate.get("subscriptionId")
        and get_partial_sku(candidate.get("offerId") or "") == partial_sku
    ]
    return candidates[0] if len(candidates) == 1 else None


def preview_code_results(line_item):
    """Map each code on a preview line to Adobe's result for it."""
    return {
        flex_discount.get("code"): flex_discount.get("result")
        for flex_discount in (line_item or {}).get("flexDiscounts") or []
    }


class ValidateRenewalDiscountCodes(Step):
    """
    Ask Adobe whether it will honour every discount code of the plan.

    Runs after the codes are stored and before any net-new subscription is
    created, so a refusal leaves nothing that cannot be undone. Two previews
    are needed because Adobe does not allow existing subscriptions and new
    offers in one: an automated PREVIEW_RENEWAL (no line items) evaluates the
    codes now stored on the existing subscriptions, and a line-item
    PREVIEW_RENEWAL of the net-new offers evaluates their codes. A code counts
    as confirmed only when Adobe reports ``result: SUCCESS`` for it on its line;
    a code Adobe applied that the plan did not request (an auto-applied
    reusable) is not judged. Any code not confirmed reverses the plan and fails
    the order, naming the code and the line. The confirmed codes are kept for
    RecordDiscountRedemptions.
    """

    refusal_error_codes = frozenset((
        AdobeErrorCode.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT,
        AdobeErrorCode.INVALID_FLEX_DISCOUNT_CODE,
        AdobeErrorCode.FLEX_DISCOUNT_CODE_LIMIT_EXCEEDED,
    ))

    def __call__(self, client, context, next_step):
        """Ask Adobe whether it will honour every discount code of the plan."""
        plans = self._plans_with_codes(context)
        net_new_items = self._net_new_items_with_codes(context)
        if not plans and not net_new_items:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        try:
            verdicts = self._collect_verdicts(adobe_client, context, plans, net_new_items)
        except AdobeAPIError as error:
            logger.warning("%s: renewal discount code preview failed: %s", context, error)
            fail_renewal_order(
                client,
                adobe_client,
                context,
                ERR_RENEWAL_PREVIEW_FAILED.to_dict(error=error.message),
            )
            return

        if verdicts.refusals:
            self._refuse(client, adobe_client, context, verdicts.refusals)
            return

        context.renewal_confirmed_flex_discount_codes = verdicts.confirmed
        logger.info(
            "%s: Adobe confirmed the renewal plan's discount codes: %s",
            context,
            ", ".join(sorted(verdicts.confirmed)),
        )
        next_step(client, context)

    def _plans_with_codes(self, context):
        return [
            plan
            for plan in context.renewal_plan_subscriptions
            if plan["renew"] and plan["flex_discount_codes"]
        ]

    def _net_new_items_with_codes(self, context):
        return [
            net_new_item
            for net_new_item in (context.renewal_payload or {}).get("netNewItems", [])
            if net_new_item.get("flexDiscountCodes")
        ]

    def _collect_verdicts(self, adobe_client, context, plans, net_new_items):
        verdicts = _CodeVerdicts()
        if plans:
            self._judge_existing(adobe_client, context, plans, verdicts)
        if net_new_items:
            self._judge_net_new(adobe_client, context, net_new_items, verdicts)
        return verdicts

    def _judge_existing(self, adobe_client, context, plans, verdicts):
        """Judge the codes stored on the existing subscriptions with an automated preview."""
        preview = adobe_client.create_preview_renewal(
            context.authorization_id,
            context.adobe_customer_id,
        )
        line_items = preview.get("lineItems") or []
        for plan in plans:
            code_results = preview_code_results(find_preview_subscription_line(line_items, plan))
            for code in plan["flex_discount_codes"]:
                verdicts.judge(code, code_results, f"subscription {plan['subscription_id']}")

    def _judge_net_new(self, adobe_client, context, net_new_items, verdicts):
        """Judge the net-new offers' codes with a line-item preview of those offers only."""
        try:
            preview = adobe_client.create_renewal_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
                [
                    {
                        "extLineItemNumber": number,
                        "offerId": net_new_item["offerId"],
                        "quantity": net_new_item["quantity"],
                        "flexDiscountCodes": net_new_item["flexDiscountCodes"],
                    }
                    for number, net_new_item in enumerate(net_new_items, start=1)
                ],
                order_type=ORDER_TYPE_PREVIEW_RENEWAL,
                recommendation_tracker_id=(
                    context.renewal_payload.get("recommendationTrackerId") or None
                ),
            )
        except AdobeAPIError as error:
            if error.code not in self.refusal_error_codes:
                raise
            verdicts.refuse_request(error, net_new_items)
            return

        verdicts.judge_net_new_preview(preview, net_new_items)

    def _refuse(self, client, adobe_client, context, refusals):
        joined = "; ".join(refusals)
        logger.warning(
            "%s: Adobe did not confirm the renewal plan's discount codes: %s", context, joined
        )
        fail_renewal_order(
            client,
            adobe_client,
            context,
            ERR_RENEWAL_FLEX_DISCOUNT_REFUSED.to_dict(refusals=joined),
        )


class Validate3YCRenewalFloor(Step):
    """
    Validate the resulting renewing aggregate against the 3YC committed minimum.

    The additive-before-subtractive ordering of the renewal flows only
    protects the intermediate states: nothing compares the plan's end state
    with the committed floor, and the renewal orders are created directly in
    Processing so the draft validation guard never runs for them. This step
    projects the plan onto the customer's Adobe subscriptions snapshotted by
    SetupRenewalPlan (a renewing entry takes the plan's renewal quantity, a
    lapsing entry stops renewing, a subscription outside the plan keeps its
    current auto-renewal and inactive subscriptions never count), adds the
    net-new items when the flow creates them, and validates the resulting
    licenses and consumables aggregate with the same 3YC guard used by the
    other order types. It runs before any mutation, so a breach fails the
    order with nothing to reverse. The floor is enforced only for a
    COMMITTED/ACTIVE commitment that does not end before the coterm date.
    """

    def __init__(self, *, include_net_new_items=True):
        self.include_net_new_items = include_net_new_items
        self.commitment_validator = Validate3YCCommitment()

    def __call__(self, client, context, next_step):
        """Validate the resulting renewing aggregate against the 3YC committed minimum."""
        commitment = get_3yc_commitment(context.adobe_customer or {})
        if not self._is_floor_enforced(context, commitment):
            next_step(client, context)
            return

        projected_subscriptions = self._project_plan(context)
        count_licenses, count_consumables = (
            self.commitment_validator.get_licenses_and_consumables_count(
                context.market_segment, {"items": projected_subscriptions}
            )
        )
        error = self.commitment_validator.validate_minimum_quantity(
            context, commitment, count_licenses, count_consumables
        )
        if error:
            logger.warning(
                "%s: the renewal plan breaches the 3YC committed minimum: %s", context, error
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_COMMITMENT_3YC_VALIDATION.to_dict(error=error),
            )
            return

        logger.info(
            "%s: the renewal plan respects the 3YC committed minimum (licenses=%s, consumables=%s)",
            context,
            count_licenses,
            count_consumables,
        )
        next_step(client, context)

    def _is_floor_enforced(self, context, commitment):
        if not commitment or commitment.get("status") not in IN_FORCE_COMMITMENT_STATUSES:
            logger.info(
                "%s: no 3YC commitment in force, skipping the renewal floor validation", context
            )
            return False
        if is_3yc_commitment_ending_before_coterm(context.adobe_customer, commitment):
            logger.info(
                "%s: the 3YC commitment ends before the coterm date, "
                "skipping the renewal floor validation",
                context,
            )
            return False
        return True

    def _project_plan(self, context):
        """Return the Adobe subscriptions as they will renew once the plan is applied."""
        plans_by_subscription_id = {
            plan["subscription_id"]: plan for plan in context.renewal_plan_subscriptions
        }
        projected = [
            self._project_subscription(
                subscription, plans_by_subscription_id.get(subscription["subscriptionId"])
            )
            for subscription in context.adobe_customer_subscriptions
            if subscription.get("status") != AdobeSubscriptionStatus.INACTIVE
        ]
        if self.include_net_new_items:
            self._project_net_new_items(context, projected)
        return projected

    def _project_subscription(self, subscription, plan):
        auto_renewal = subscription.get("autoRenewal", {})
        if plan is None:
            enabled = auto_renewal.get("enabled", False)
            quantity = auto_renewal.get(Param.RENEWAL_QUANTITY.value) or 0
        elif plan["renew"]:
            enabled, quantity = True, self._renewing_quantity(plan)
        else:
            enabled, quantity = False, 0
        return {
            **subscription,
            "autoRenewal": {"enabled": enabled, Param.RENEWAL_QUANTITY.value: quantity},
        }

    def _renewing_quantity(self, plan):
        """
        Return the quantity a renewing plan entry will renew.

        An entry already committed by a previous renewal order with no
        requested quantity change keeps that order's renewedQuantity (the
        renew-now flow submits nothing for it); otherwise the plan's
        renewal quantity applies.
        """
        renewed_quantity = plan["snapshot"].get("renewed_quantity")
        if not plan["renewal_quantity"] and renewed_quantity is not None:
            return renewed_quantity
        return plan["renewal_quantity"]

    def _project_net_new_items(self, context, projected):
        """
        Add the plan's net-new items to the projection.

        Mirrors CreateNetNewSubscriptions: a scheduled subscription already
        holding the offer (created by a previous attempt) is reused instead
        of being counted twice.
        """
        for net_new_item in context.renewal_payload.get("netNewItems", []):
            auto_renewal = {
                "enabled": True,
                Param.RENEWAL_QUANTITY.value: net_new_item["quantity"],
            }
            scheduled = find_scheduled_subscription(projected, net_new_item["offerId"])
            if scheduled:
                scheduled["autoRenewal"] = auto_renewal
            else:
                projected.append({
                    "offerId": net_new_item["offerId"],
                    "status": AdobeSubscriptionStatus.SCHEDULED,
                    "autoRenewal": auto_renewal,
                })


class ValidateNetNewOrderLines(Step):
    """
    Fail the order before any Adobe mutation when a net-new item has no MPT order line.

    CreateNetNewMptSubscriptions matches each net-new item to its MPT order line by SKU
    and skips an unmatched one. That would leave Adobe holding the new subscription
    (scheduled at the anniversary, or created and invoiced on the renew-now path) while
    the MPT order completes without it, so both renewal flows validate the mapping up
    front, before any Adobe call, and fail the order with nothing changed instead. The
    check does not depend on the order type: a payload that carries net-new items on a
    Configuration order, which has no lines, fails here too.
    """

    def __call__(self, client, context, next_step):
        """Fail the order when a net-new item has no matching MPT order line."""
        net_new_items = (
            context.renewal_payload.get("netNewItems", []) if context.renewal_payload else []
        )
        unmatched = [
            net_new_item["offerId"]
            for net_new_item in net_new_items
            if not get_order_line_by_sku(context.order, net_new_item["offerId"])
        ]
        if unmatched:
            unmatched_offers = ", ".join(unmatched)
            logger.warning(
                "%s: net-new item(s) with no matching order line: %s",
                context,
                unmatched_offers,
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_NET_NEW_FAILED.to_dict(
                    offer_id=unmatched_offers,
                    error="no matching order line for the net-new item",
                ),
            )
            return

        next_step(client, context)


class CreateNetNewSubscriptions(Step):
    """
    Create the scheduled Adobe subscriptions for the net-new products of the plan.

    Runs once the plan's discount codes are confirmed, so a refused code never
    leaves a scheduled subscription behind (one cannot be deleted, only
    neutralized), and before any renewal quantity is decreased or disabled, so
    the additive operations precede the subtractive ones and the renewing
    aggregate never dips below the 3YC committed minimum. On a failure,
    everything this run changed is reversed. The step is idempotent: a scheduled (1009)
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
                flex_discount_codes=net_new_item.get("flexDiscountCodes"),
            )
        except AdobeAPIError as error:
            logger.warning(
                "%s: failed to create scheduled subscription for offer %s: %s",
                context,
                offer_id,
                error,
            )
            fail_renewal_order(
                client,
                adobe_client,
                context,
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
        if self._scheduled_matches_plan(net_new_item, auto_renewal):
            context.renewal_net_new_subscriptions[offer_id] = existing
            return True

        requested_codes = net_new_item.get("flexDiscountCodes") or []
        try:
            subscription = adobe_client.update_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                existing["subscriptionId"],
                auto_renewal=True,
                quantity=net_new_item["quantity"],
                flex_discount_codes=requested_codes or None,
                # An empty list does not clear a stored code; Adobe needs the reset flag
                # when the plan drops a code the reused subscription still carries.
                reset_flex_discount_codes=(
                    not requested_codes and bool(auto_renewal.get("flexDiscountCodes"))
                ),
            )
        except AdobeAPIError as error:
            logger.warning(
                "%s: failed to restore scheduled subscription %s for offer %s: %s",
                context,
                existing["subscriptionId"],
                offer_id,
                error,
            )
            fail_renewal_order(
                client,
                adobe_client,
                context,
                ERR_RENEWAL_NET_NEW_FAILED.to_dict(offer_id=offer_id, error=error.message),
            )
            return False

        logger.info(
            "%s: scheduled subscription %s re-enabled for offer %s (quantity=%s)",
            context,
            existing["subscriptionId"],
            offer_id,
            net_new_item["quantity"],
        )
        context.renewal_net_new_subscriptions[offer_id] = subscription
        context.renewal_created_net_new_subscriptions[offer_id] = subscription
        return True

    def _scheduled_matches_plan(self, net_new_item, auto_renewal):
        """True when the scheduled subscription already matches the plan (reuse as-is)."""
        return (
            auto_renewal.get("enabled", False)
            and auto_renewal.get(Param.RENEWAL_QUANTITY.value) == net_new_item["quantity"]
            and (net_new_item.get("flexDiscountCodes") or [])
            == (auto_renewal.get("flexDiscountCodes") or [])
        )

    def _find_scheduled_subscription(self, context, offer_id):
        return find_scheduled_subscription(context.adobe_customer_subscriptions, offer_id)


class UpdateRenewalSubscriptions(Step):
    """
    Apply the plan's renewal quantities and lapses to the existing Adobe subscriptions.

    Runs last among the mutations, after auto-renewal was enabled, the codes
    were stored and confirmed, and the net-new subscriptions were created. The
    PATCH operations keep the additive-before-subtractive order (increase,
    decrease, disable) so the renewing aggregate never dips below the 3YC
    committed minimum; the codes are not sent again. On a confirmed Adobe
    failure everything this run changed is reversed (restore-to-known-good,
    best effort) and the scheduled net-new subscriptions are neutralized.
    Operations whose target state is already in place are skipped, so retries
    are safe.
    """

    def __call__(self, client, context, next_step):
        """Apply the plan's renewal quantities and lapses to the existing subscriptions."""
        adobe_client = get_adobe_client()
        operations = self._build_operations(context)
        for plan, operation in operations:
            record_renewal_change(context, plan)
            try:
                self._apply_operation(adobe_client, context, operation)
            except AdobeAPIError as error:
                logger.warning(
                    "%s: failed to update auto-renewal for subscription %s: %s",
                    context,
                    operation["subscription_id"],
                    error,
                )
                fail_renewal_order(
                    client,
                    adobe_client,
                    context,
                    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED.to_dict(
                        subscription_id=operation["subscription_id"],
                        error=error.message,
                    ),
                )
                return

        logger.info(
            "%s: auto-renewal preferences applied (%s operation(s))",
            context,
            len(operations),
        )
        next_step(client, context)

    # The list order is the fulfillment invariant: additive before subtractive.
    operation_kinds = ("increase", "decrease", "disable")

    def _build_operations(self, context):
        """Classify the plan into (plan, operation) pairs, additive before subtractive."""
        buckets = {kind: [] for kind in self.operation_kinds}
        for plan in context.renewal_plan_subscriptions:
            classified = self._classify_plan(plan)
            if classified:
                kind, operation = classified
                buckets[kind].append((plan, operation))

        return [pair for kind in self.operation_kinds for pair in buckets[kind]]

    def _classify_plan(self, plan):
        """Return the (kind, operation) of a plan entry, or None when already in place."""
        snapshot = plan["snapshot"]
        if not plan["renew"]:
            return self._classify_lapsing(plan, snapshot)

        # A subscription that had auto-renewal off was enabled with the plan's
        # quantity by EnableRenewalSubscriptions.
        if not snapshot["enabled"] or snapshot["renewal_quantity"] == plan["renewal_quantity"]:
            return None

        is_increase = plan["renewal_quantity"] >= (snapshot["renewal_quantity"] or 0)
        return ("increase" if is_increase else "decrease"), {
            "subscription_id": plan["subscription_id"],
            "enabled": True,
            "quantity": plan["renewal_quantity"],
        }

    def _classify_lapsing(self, plan, snapshot):
        """Return the disable operation of a lapsing plan entry, or None if already disabled."""
        if not snapshot["enabled"]:
            return None
        return "disable", {
            "subscription_id": plan["subscription_id"],
            "enabled": False,
            "quantity": None,
        }

    def _apply_operation(self, adobe_client, context, operation):
        adobe_client.update_subscription(
            context.authorization_id,
            context.adobe_customer_id,
            operation["subscription_id"],
            auto_renewal=operation["enabled"],
            quantity=operation["quantity"],
        )
        logger.info(
            "%s: auto-renewal set for subscription %s (enabled=%s, quantity=%s)",
            context,
            operation["subscription_id"],
            operation["enabled"],
            operation["quantity"],
        )


def disable_net_new_subscriptions(adobe_client, context):
    """
    Neutralize the net-new subscriptions created by this run by disabling their auto-renewal.

    A scheduled (1009) subscription cannot be deleted: disabling its
    auto-renewal prevents it from activating at the anniversary, which is the
    documented reversal path. Only the subscriptions created or re-enabled
    during this run are touched: a reused scheduled subscription whose
    auto-renewal was already in place was not mutated by this run, so its
    auto-renewal is preserved. Failures, including transport failures, are logged
    and skipped (best effort).
    """
    for offer_id, subscription in context.renewal_created_net_new_subscriptions.items():
        try:
            adobe_client.update_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                subscription["subscriptionId"],
                auto_renewal=False,
            )
        except (AdobeAPIError, AdobeTransportError):
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


def get_redeemed_codes(context):
    """Return the unique codes newly applied by the plan, skipping inherited ones."""
    confirmed_codes = get_confirmed_codes(context)
    redeemed_codes, inherited_codes = _split_plan_codes(context)
    # Net-new items create a brand-new subscription, so they can hold no inherited
    # code: every code on a net-new item is a fresh redemption by this order.
    for net_new_item in (context.renewal_payload or {}).get("netNewItems", []):
        redeemed_codes.extend(net_new_item.get("flexDiscountCodes") or [])
    if confirmed_codes is not None:
        redeemed_codes = _drop_unconfirmed_codes(context, redeemed_codes, confirmed_codes)
    if inherited_codes:
        logger.info(
            "%s: skipping inherited flex discount code(s) already held by the "
            "subscriptions, not redeemed by this order: %s",
            context,
            ", ".join(dict.fromkeys(inherited_codes)),
        )
    return list(dict.fromkeys(redeemed_codes))


def get_confirmed_codes(context):
    """
    Return the codes Adobe confirmed for the order, or None when nothing was checked.

    At the anniversary, ValidateRenewalDiscountCodes stores the codes the
    renewal previews confirmed (context.renewal_confirmed_flex_discount_codes).
    On renew-now, the confirmed set is the codes Adobe applied (result SUCCESS)
    on the committed RENEWAL order's line items (context.adobe_renewal_order).
    Either set drops requested codes Adobe did not confirm. A discount object
    without an explicit SUCCESS result is treated as unconfirmed, so an
    ambiguous entry never consumes the customer's once-per-customer eligibility.
    """
    if context.renewal_confirmed_flex_discount_codes is not None:
        return context.renewal_confirmed_flex_discount_codes
    renewal_order = context.adobe_renewal_order
    if renewal_order is None:
        return None
    return {
        flex_discount["code"]
        for line_item in renewal_order.get("lineItems", [])
        for flex_discount in line_item.get("flexDiscounts") or []
        if flex_discount.get("result") == "SUCCESS"
    }


def _drop_unconfirmed_codes(context, redeemed_codes, confirmed_codes):
    """Keep only the plan codes the committed RENEWAL order confirmed (renew-now)."""
    dropped = [code for code in redeemed_codes if code not in confirmed_codes]
    if dropped:
        logger.warning(
            "%s: skipping flex discount code(s) not confirmed on the committed "
            "renewal order, not redeemed by this order: %s",
            context,
            ", ".join(dict.fromkeys(dropped)),
        )
    return [code for code in redeemed_codes if code in confirmed_codes]


def _split_plan_codes(context):
    """Split the renewing plan's codes into (redeemed, inherited)."""
    redeemed_codes, inherited_codes = [], []
    for plan in context.renewal_plan_subscriptions:
        if not plan["renew"]:
            continue
        for code in plan["flex_discount_codes"]:
            is_inherited = code in plan["snapshot"]["flex_discount_codes"]
            (inherited_codes if is_inherited else redeemed_codes).append(code)
    return redeemed_codes, inherited_codes


class RecordClientDiscountCodes(Step):
    """
    Write the redeemed discount codes missing from the AirTable store back to it.

    A code redeemed by the plan that the Discount Codes table does not know
    yet was typed by the client in the wizard (never offered from the store),
    and its use just succeeded on Adobe, so on this first successful use it is
    fetched from Adobe by code and stored with source "Client". Runs after the
    order has been completed and before RecordDiscountRedemptions, so the
    redemption rows always point at a known code. The write is best effort:
    the order is already completed, so a failure is logged and notified for a
    manual backfill instead of failing the order.
    """

    def __call__(self, client, context, next_step):
        """Write the redeemed discount codes missing from the AirTable store back to it."""
        redeemed_codes = get_redeemed_codes(context)
        if redeemed_codes:
            try:
                self._store_missing_codes(context, redeemed_codes)
            except Exception:
                logger.exception(
                    "%s: failed to write the client discount code(s) back to AirTable",
                    context,
                )
                joined_codes = ", ".join(redeemed_codes)
                send_exception(
                    f"Error storing the client discount codes of order {context.order_id}",
                    "The renewal order has been completed but the discount codes it "
                    "redeemed could not be checked against or written back to the "
                    "AirTable Discount Codes table and must be reviewed manually:\n"
                    f"- Customer ID: {context.adobe_customer_id}\n"
                    f"- Order ID: {context.order_id}\n"
                    f"- Codes: {joined_codes}\n",
                )
        next_step(client, context)

    def _store_missing_codes(self, context, redeemed_codes):
        market_segment = MARKET_SEGMENTS[context.market_segment]
        existing_codes = get_existing_discount_codes(redeemed_codes, market_segment)
        missing_codes = [code for code in redeemed_codes if code not in existing_codes]
        if not missing_codes:
            logger.info(
                "%s: every redeemed discount code is already on the AirTable store",
                context,
            )
            return
        discounts = self._fetch_adobe_discounts(context, market_segment, missing_codes)
        if discounts:
            create_client_discount_codes(discounts, market_segment, context.adobe_customer_id)
            logger.info(
                "%s: stored %s client discount code(s) on the AirTable store: %s",
                context,
                len(discounts),
                ", ".join(discount["code"] for discount in discounts),
            )

    def _fetch_adobe_discounts(self, context, market_segment, missing_codes):
        country = context.adobe_customer["companyProfile"]["address"]["country"]
        discounts = []
        for code in missing_codes:
            discount = self._fetch_adobe_discount(context, market_segment, country, code)
            if discount:
                discounts.append(discount)
            else:
                logger.warning(
                    "%s: Adobe returned no flex discount for the redeemed code %s, "
                    "it cannot be written back to the AirTable store",
                    context,
                    code,
                )
        return discounts

    def _fetch_adobe_discount(self, context, market_segment, country, code):
        flex_discounts = get_adobe_client().get_flex_discounts_by_code(
            context.authorization_id,
            market_segment,
            country,
            code,
        )
        return next((fd for fd in flex_discounts if fd.get("code") == code), None)


class RecordDiscountRedemptions(Step):
    """
    Record the flex discount codes redeemed by the order on the AirTable redemptions table.

    Runs after the order has been completed, so a fulfillment retry of an
    earlier failure never duplicates rows. One row is written per unique code
    the order redeemed, as reported by the code source the step is built with:
    by default the renewal plan (get_redeemed_codes), or the completed NEW
    order's flexibleDiscounts parameter for purchase/change orders
    (flows.utils.flex_discounts.get_order_redeemed_codes).

    On the renewal flows a code the subscription already carried before this
    order (inherited discount snapshotted by SetupRenewalPlan) was not
    redeemed by it, so it is skipped: an auto-applied reusable is never
    recorded as a fresh once-per-customer redemption.

    A code is recorded only once Adobe confirmed it, so an unconfirmed code
    never consumes the customer's once-per-customer eligibility. On the
    renew-now flow that is the committed RENEWAL order's result: the flow drops
    a requested code the preview did not confirm from the order without failing
    it. On the at-anniversary flow the codes ride update_subscription and
    create_customer_subscription, which Adobe does not validate, so
    ValidateRenewalDiscountCodes confirms them through renewal previews and
    fails the order on any refusal; the codes it confirmed are the recorded
    ones.

    The write is best effort: the order is already completed, so an AirTable
    failure is logged and notified for a manual backfill instead of failing
    the order.
    """

    def __init__(self, get_redeemed_codes=get_redeemed_codes):
        self._get_redeemed_codes = get_redeemed_codes

    def __call__(self, client, context, next_step):
        """Record the redeemed flex discount codes on the AirTable redemptions table."""
        try:
            redeemed_codes = self._get_redeemed_codes(context)
        except Exception:
            logger.exception("%s: failed to read the discount redemptions", context)
            send_exception(
                f"Error reading the discount redemptions of order {context.order_id}",
                "The order has been completed but its discount redemptions could not "
                "be determined. Review the order's flexibleDiscounts parameter and "
                "backfill any missing AirTable Discount Redemptions manually:\n"
                f"- Customer ID: {context.adobe_customer_id}\n"
                f"- Order ID: {context.order_id}\n",
            )
            next_step(client, context)
            return
        if redeemed_codes:
            self._record_redemptions(context, redeemed_codes)
        else:
            logger.info(
                "%s: no flex discount codes redeemed by the order, "
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
                "The order has been completed but the redeemed flex discount "
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
    Fulfills an order that carries an at-anniversary renewal payload.

    It validates the resulting renewing aggregate against the 3YC committed
    minimum, enables auto-renewal where needed, stores the plan's flexible
    discount codes and confirms them with Adobe before creating anything that
    cannot be undone, then creates the scheduled net-new subscriptions and
    applies the renewal quantities (increase, decrease, disable). The order is
    additive before subtractive, so the 3YC committed minimum is never
    breached. Nothing is invoiced and no Adobe order is placed: the plan takes
    effect at the coterm date.

    The renewal wizard submits the plan as a Change order when a quantity moves
    or a net-new product is added, and as a Configuration order when only
    renew decisions change; both carry the same payload and run this pipeline.
    A Configuration order keeps the configuration templates its order type
    uses elsewhere.

    Args:
        client (MPTClient): An instance of the MPT client used for communication
        with the MPT system.
        order (dict): The MPT order representing the renewal order to be fulfilled.

    Returns:
        None
    """
    template_name = (
        get_configuration_template_name(order)
        if order["type"] == OrderType.CONFIGURATION
        else TEMPLATE_NAME_CHANGE
    )
    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(template_name),
        SetupDueDate(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        UpdateAgreementParamsVisibility(),
        ValidateRenewalWindow(),
        SetupRenewalPlan(),
        ValidateNetNewOrderLines(),
        Validate3YCRenewalFloor(),
        ReverseRenewalChangesOnError(),
        EnableRenewalSubscriptions(),
        ApplyRenewalDiscountCodes(),
        ValidateRenewalDiscountCodes(),
        CreateNetNewSubscriptions(),
        UpdateRenewalSubscriptions(),
        CreateNetNewMptSubscriptions(),
        RecordFlexDiscounts(),
        CompleteOrder(template_name),
        RecordClientDiscountCodes(),
        RecordDiscountRedemptions(),
        SetSubscriptionTemplate(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
