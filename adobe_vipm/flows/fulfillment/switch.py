"""
This module contains the logic to implement the switch fulfillment flow.

It exposes a single function that is the entrypoint for change orders
that carry a mid-term upgrade (SWITCH) payload computed from an Adobe
recommendation.

The flexible discount codes the payload selects per line item are validated
by the PREVIEW_SWITCH order: only a requested code the preview confirmed is
committed on the SWITCH order, and the applied codes are recorded on the
order's flexibleDiscounts parameter and on the AirTable redemptions table
once the order completes.
"""

import logging

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    UNRECOVERABLE_ORDER_STATUSES,
    AdobeOrderStatus,
    AdobeSubscriptionStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.adobe.utils import is_flex_discount_applied
from adobe_vipm.flows.constants import (
    ERR_FLEX_DISCOUNT_CODE_LIMIT,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    TEMPLATE_NAME_CHANGE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.renewal import RecordDiscountRedemptions
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    NullifyFlexDiscountParam,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
    SetupDueDate,
    StartOrderProcessing,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
    get_flex_discount_limit_error,
    refresh_flex_discounts_parameter,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext, UpdatePrices, ValidateSkuAvailability
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import get_switch_payload, set_adobe_order_id
from adobe_vipm.flows.utils.flex_discounts import get_order_redeemed_codes
from adobe_vipm.flows.utils.parameter import (
    set_adobe_order_ids_created_parameter,
    set_flex_discounts_parameter,
)
from adobe_vipm.notifications import send_exception, send_warning

logger = logging.getLogger(__name__)


def _describe_flex_discount_violation(line_item):
    line_number = line_item.get("extLineItemNumber")
    codes = line_item["flexDiscountCodes"]
    code_count = len(codes)
    joined_codes = ", ".join(codes)
    return f"line {line_number} carries {code_count} codes ({joined_codes})"


def _get_flex_discount_limit_violation(switch_payload):
    """
    Describe the switch payload lines that violate Adobe's one-code-per-line rule.

    The switch payload is external input forwarded verbatim to Adobe: a line
    item carrying more than one flexible discount code would be rejected by
    Adobe with error 2147 at submission, so it is caught upfront instead.
    Returns None when every line item carries at most one code.
    """
    violations = [
        _describe_flex_discount_violation(line_item)
        for line_item in switch_payload.get("lineItems", [])
        if len(line_item.get("flexDiscountCodes") or []) > 1
    ]
    return "; ".join(violations) or None


def get_requested_flex_discount_codes(switch_payload):
    """
    Map each switch payload line item's extLineItemNumber to the code it requests.

    Adobe accepts a single code per line item (the payload is checked upfront
    by _get_flex_discount_limit_violation), so the first code is the requested one.
    """
    return {
        line_item["extLineItemNumber"]: line_item["flexDiscountCodes"][0]
        for line_item in switch_payload.get("lineItems", [])
        if line_item.get("flexDiscountCodes")
    }


def _get_confirmed_flex_discount_codes(preview_order):
    """Map each PREVIEW_SWITCH line item to the codes Adobe applied on it (result SUCCESS)."""
    return {
        line_item.get("extLineItemNumber"): {
            flex_discount["code"]
            for flex_discount in line_item.get("flexDiscounts") or []
            if is_flex_discount_applied(flex_discount)
        }
        for line_item in preview_order.get("lineItems", [])
    }


def get_unconfirmed_flex_discount_codes(switch_payload, preview_order):
    """Return the requested codes the PREVIEW_SWITCH order did not apply, by line number."""
    confirmed_codes = _get_confirmed_flex_discount_codes(preview_order)
    return {
        line_number: code
        for line_number, code in get_requested_flex_discount_codes(switch_payload).items()
        if code not in confirmed_codes.get(line_number, set())
    }


def build_committed_switch_payload(switch_payload, preview_order):
    """
    Build the SWITCH order payload, committing only the preview-confirmed discount codes.

    The switch payload stays the source of truth for the line items and the
    cancellingItems; only the flexDiscountCodes of each line item are
    rewritten. A requested code the preview did not apply (result other than
    SUCCESS or not reported) is dropped from the line, so the SWITCH order is
    not rejected for it. A discount the preview reports that the payload did
    not request (a reusable discount Adobe auto-applied) is not echoed back:
    Adobe applies it itself and echoing it could put two codes on the line
    (error 2147).
    """
    confirmed_codes = _get_confirmed_flex_discount_codes(preview_order)
    line_items = [
        _build_committed_line_item(
            line_item, confirmed_codes.get(line_item.get("extLineItemNumber"), set())
        )
        for line_item in switch_payload.get("lineItems", [])
    ]
    return {**switch_payload, "lineItems": line_items}


def _build_committed_line_item(line_item, confirmed_codes):
    """Keep the line item's requested code only when the preview applied it."""
    committed_line_item = dict(line_item)
    requested_code = next(iter(committed_line_item.pop("flexDiscountCodes", None) or []), None)
    line_number = line_item.get("extLineItemNumber")
    auto_applied = sorted(confirmed_codes - {requested_code})
    if auto_applied:
        logger.info(
            "Flex discounts: leaving discount(s) %s auto-applied by Adobe on switch line %s "
            "out of the order, Adobe applies them itself",
            auto_applied,
            line_number,
        )
    if requested_code in confirmed_codes:
        committed_line_item["flexDiscountCodes"] = [requested_code]
    elif requested_code:
        logger.warning(
            "Flex discounts: requested code %s on switch line %s was not confirmed by the "
            "preview, committing the line without it",
            requested_code,
            line_number,
        )
    return committed_line_item


class GetSwitchPreviewOrder(Step):
    """
    Retrieve a PREVIEW_SWITCH order for the switch payload of the order.

    It validates with Adobe that the switch can be processed and retrieves
    the pricing of the new line items, including the flexible discount codes
    requested per line item. If Adobe rejects the preview the order will be
    failed and the processing pipeline will stop. A requested code the preview
    did not apply does not fail the order: the line proceeds undiscounted on
    the SWITCH order and a warning is notified.
    In case the switch order has already been submitted by a previous attempt,
    this step will be skipped and the order processing pipeline will continue.
    """

    def __call__(self, mpt_client, context, next_step):
        """Retrieve a PREVIEW_SWITCH order for the switch payload of the order."""
        if context.adobe_new_order_id:
            logger.info(
                "%s: skip switch preview, Adobe order %s has already been created",
                context,
                context.adobe_new_order_id,
            )
            next_step(mpt_client, context)
            return

        switch_payload = get_switch_payload(context.order)
        if not self._validate_flex_discount_limit(mpt_client, context, switch_payload):
            return

        adobe_client = get_adobe_client()
        try:
            context.adobe_preview_order = adobe_client.create_switch_preview_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
                switch_payload,
            )
        except AdobeError as error:
            switch_order_to_failed(
                mpt_client,
                context.order,
                get_flex_discount_limit_error(error)
                or ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
            )
            logger.warning("%s: switch preview failed: %s", context, error)
            return

        logger.info("%s: switch preview validated successfully", context)
        self._notify_unconfirmed_codes(context, switch_payload)
        next_step(mpt_client, context)

    def _validate_flex_discount_limit(self, mpt_client, context, switch_payload):
        """Fail the order upfront when a line item carries more than one code."""
        violation = _get_flex_discount_limit_violation(switch_payload)
        if not violation:
            return True
        logger.warning(
            "%s: switch payload violates the one-flex-discount-code-per-line rule: %s",
            context,
            violation,
        )
        switch_order_to_failed(
            mpt_client,
            context.order,
            ERR_FLEX_DISCOUNT_CODE_LIMIT.to_dict(error=violation),
        )
        return False

    def _notify_unconfirmed_codes(self, context, switch_payload):
        """Signal the requested codes the preview did not apply, dropped from the order."""
        unconfirmed = get_unconfirmed_flex_discount_codes(
            switch_payload, context.adobe_preview_order
        )
        if not unconfirmed:
            return
        details = "\n".join(
            f"- Line {line_number}: {code}" for line_number, code in sorted(unconfirmed.items())
        )
        logger.warning(
            "%s: Adobe's switch preview did not apply the flex discount code(s) of line(s) %s, "
            "they proceed undiscounted",
            context,
            sorted(unconfirmed),
        )
        customer_id = context.adobe_customer_id or "-"
        send_warning(
            f"Flex discounts not applied on order {context.order_id}",
            "Adobe's switch preview did not apply the requested discount code of the "
            "following lines, which proceed undiscounted:\n"
            f"{details}\n"
            f"- Customer ID: {customer_id}\n"
            f"- Order ID: {context.order_id}\n",
        )


class SubmitSwitchOrder(Step):
    """
    Submit the Adobe SWITCH order for the switch payload of the order.

    Only the flexible discount codes confirmed by the PREVIEW_SWITCH order are
    committed (see build_committed_switch_payload). They are recorded on the
    flexibleDiscounts parameter as pending proposals while the order is open,
    and reconciled with the codes Adobe applied once it completes.
    Wait for the order to be processed by Adobe before moving to the next step.
    The step is idempotent: if the Adobe order has already been created by a
    previous attempt it is retrieved instead of being created again.
    """

    def __call__(self, client, context, next_step):
        """Submit the Adobe SWITCH order for the switch payload of the order."""
        adobe_client = get_adobe_client()
        if context.adobe_new_order_id:
            adobe_order = adobe_client.get_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.adobe_new_order_id,
            )
        else:
            adobe_order = self._submit_switch_order(client, adobe_client, context)
            if adobe_order is None:
                return
        context.adobe_new_order = adobe_order
        context.adobe_new_order_id = adobe_order["orderId"]
        adobe_order_status = adobe_order["status"]

        if adobe_order_status == AdobeOrderStatus.OPEN:
            logger.info(
                "%s: adobe switch order %s is still pending.", context, context.adobe_new_order_id
            )
            return

        if adobe_order_status in UNRECOVERABLE_ORDER_STATUSES:
            error = ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS.to_dict(
                description=ORDER_STATUS_DESCRIPTION[adobe_order_status],
            )
            switch_order_to_failed(client, context.order, error)
            logger.warning("%s: the switch order has been failed %s.", context, error["message"])
            return

        if adobe_order_status != AdobeOrderStatus.COMPLETE:
            error = ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status=adobe_order_status)
            switch_order_to_failed(client, context.order, error)
            logger.warning(
                "%s: the switch order has been failed due to %s.", context, error["message"]
            )
            return

        refresh_flex_discounts_parameter(client, context)
        next_step(client, context)

    def _submit_switch_order(self, client, adobe_client, context):
        """
        Create the SWITCH order and persist its id and requested discount codes.

        Returns None when the submission was rejected and the order failed.
        """
        committed_payload = build_committed_switch_payload(
            get_switch_payload(context.order), context.adobe_preview_order
        )
        adobe_order = self._create_switch_order(client, adobe_client, context, committed_payload)
        if adobe_order is None:
            return None
        logger.info("%s: new adobe switch order created: %s", context, adobe_order["orderId"])
        context.order = set_adobe_order_id(context.order, adobe_order["orderId"])
        context.order = set_adobe_order_ids_created_parameter(context, [adobe_order["orderId"]])
        pending = adobe_order["status"] == AdobeOrderStatus.OPEN
        context.order = set_flex_discounts_parameter(
            context.order,
            context.adobe_preview_order if pending else adobe_order,
            requested_codes=get_requested_flex_discount_codes(committed_payload),
            pending=pending,
        )
        update_order(
            client,
            context.order_id,
            externalIds=context.order["externalIds"],
            parameters=context.order["parameters"],
        )
        return adobe_order

    def _create_switch_order(self, client, adobe_client, context, committed_payload):
        """
        Submit the Adobe SWITCH order, or None when the submission was rejected.

        Adobe's 2147 (more than one flex discount code on a line) is a
        deterministic rejection: retrying can never succeed, so the order is
        failed instead of being left to the retry loop. Any other Adobe error
        keeps the current retry semantics.
        """
        try:
            return adobe_client.create_switch_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
                committed_payload,
            )
        except AdobeAPIError as error:
            flex_discount_error = get_flex_discount_limit_error(error)
            if not flex_discount_error:
                raise
            logger.warning("%s: switch order submission failed: %s", context, error)
            switch_order_to_failed(client, context.order, flex_discount_error)
            return None


class AlignSwitchRenewalQuantities(Step):
    """
    Set the renewal quantity of the switched subscriptions to their current quantity.

    A SWITCH cancels seats on the source subscriptions (cancellingItems) and adds
    them to the target subscriptions (the order's line items), but Adobe keeps an
    explicitly set ``autoRenewal.renewalQuantity`` through both, so the anniversary
    would renew the switched-away seats as well as the new ones. Once Adobe has
    completed the SWITCH, each switched subscription that is still active and set
    to auto-renew gets its renewal quantity set to its current quantity. Skipped:
    a source switched in full, which is inactive (1004); a subscription with
    auto-renewal off, where Adobe accepts but ignores a renewal quantity and has
    already reset any explicit one (re-enabling renews the current quantity); and
    a subscription already renewing its current quantity, so a retried order
    changes nothing twice.

    The SWITCH itself cannot be undone at this point, so a failure never fails the
    order: it is logged, reported through an exception notification listing the
    subscriptions for a manual correction, and the order still completes.
    """

    def __call__(self, client, context, next_step):
        """Set the renewal quantity of the switched subscriptions to their current quantity."""
        adobe_client = get_adobe_client()
        not_updated = []
        for subscription_id in self._switched_subscription_ids(context):
            try:
                self._align(adobe_client, context, subscription_id)
            except AdobeError as error:
                logger.warning(
                    "%s: failed to set the renewal quantity of switched subscription %s: %s",
                    context,
                    subscription_id,
                    error,
                )
                not_updated.append(f"{subscription_id}: {error}")

        if not_updated:
            send_exception(
                f"Renewal quantity not aligned after mid-term upgrade: {context.order_id}",
                "The mid-term upgrade completed, but the renewal quantity of these "
                "subscriptions could not be set to their current quantity and needs "
                "a manual correction:\n"
                + "".join(f"  - {line}\n" for line in not_updated)
                + f"\n- Product ID: {context.product_id}\n",
            )
        next_step(client, context)

    def _switched_subscription_ids(self, context):
        """Return the source and target subscription ids of the SWITCH, without duplicates."""
        switch_payload = get_switch_payload(context.order) or {}
        source_ids = [
            cancelling_item["subscriptionId"]
            for cancelling_item in switch_payload.get("cancellingItems", [])
            if cancelling_item.get("subscriptionId")
        ]
        target_ids = [
            line_item["subscriptionId"]
            for line_item in (context.adobe_new_order or {}).get("lineItems", [])
            if line_item.get("subscriptionId")
        ]
        return list(dict.fromkeys(source_ids + target_ids))

    def _align(self, adobe_client, context, subscription_id):
        subscription = adobe_client.get_subscription(
            context.authorization_id,
            context.adobe_customer_id,
            subscription_id,
        )
        if subscription["status"] != AdobeSubscriptionStatus.ACTIVE:
            logger.info(
                "%s: switched subscription %s is not active (status %s), renewal quantity left",
                context,
                subscription_id,
                subscription["status"],
            )
            return
        auto_renewal = subscription["autoRenewal"]
        if not auto_renewal.get("enabled"):
            logger.info(
                "%s: switched subscription %s does not auto-renew, renewal quantity left",
                context,
                subscription_id,
            )
            return
        current_quantity = subscription[Param.CURRENT_QUANTITY.value]
        if auto_renewal.get(Param.RENEWAL_QUANTITY.value) == current_quantity:
            return
        adobe_client.set_renewal_quantity(
            context.authorization_id,
            context.adobe_customer_id,
            subscription_id,
            current_quantity,
        )
        logger.info(
            "%s: renewal quantity of switched subscription %s set to %s",
            context,
            subscription_id,
            current_quantity,
        )


def fulfill_switch_order(client, order):
    """
    Fulfills a change order that carries a mid-term upgrade (SWITCH) payload.

    It validates the switch through a PREVIEW_SWITCH order, submits the actual
    SWITCH order and creates or updates the agreement subscriptions with the
    new Adobe subscriptions. The quantities of the subscriptions being switched
    from are cancelled by Adobe (cancellingItems) and synchronized back to the
    agreement at the end of the pipeline. The flexible discount codes the
    SWITCH order applied are recorded as redemptions once the order completes.

    Args:
        client (MPTClient): An instance of the MPT client used for communication
        with the MPT system.
        order (dict): The MPT order representing the switch order to be fulfilled.

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
        ValidateSkuAvailability(is_validation=False),
        GetSwitchPreviewOrder(),
        UpdatePrices(is_validation=False),
        SubmitSwitchOrder(),
        CreateOrUpdateSubscriptions(),
        AlignSwitchRenewalQuantities(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        SetSubscriptionTemplate(),
        RecordDiscountRedemptions(get_order_redeemed_codes),
        NullifyFlexDiscountParam(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
