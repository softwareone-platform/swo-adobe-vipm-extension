"""
This module contains the logic to implement the renew-now fulfillment flow.

It exposes a single function that is the entrypoint for change orders that
carry a renewal payload built by the renewal wizard with renewalPath "now"
(see flows/fulfillment/renewal.py for the at-anniversary path). The
renewing subscriptions are committed as an actual Adobe RENEWAL order,
invoiced immediately, mirroring how the PURCHASE flow turns its PREVIEW
order into a NEW order: validate with PREVIEW_RENEWAL, then resubmit the
line items it returns as the real order, committing only the flex discount
codes the plan explicitly selected (reusable discounts Adobe auto-applies
are never echoed back, and an explicit code takes precedence over them). A
renewing subscription already committed in a previous renewal order
(renewedQuantity populated) with no requested quantity change is excluded
from both. Once the order completes, the
renewed subscriptions (renew = true) have their autoRenewal normalised
(enabled=on, renewalQuantity taken from Adobe's post-renewal
renewedQuantity) and the plan's lapsing subscriptions (renew = false)
have their auto-renewal disabled. A lapsing subscription that was already
committed in a previous RENEWAL order (its pre-mutation snapshot carries a
renewedQuantity) additionally has that order's line returned via a RETURN
order, so the customer is not left paying for a renewal that is being
toggled off; that previous line is located and checked against Adobe's
14-day return window before anything is committed, so an order that cannot
be undone fails with nothing to reverse. Once the order is completed, the
flex discount codes redeemed by the plan are recorded on the AirTable
redemptions table. Before anything is committed, the resulting renewing
aggregate is validated against the 3YC committed minimum
(Validate3YCRenewalFloor, shared with the at-anniversary flow).

Net-new items (products the customer does not yet hold) are submitted as
additional lines on the same RENEWAL order, carrying offerId + quantity and no
subscriptionId: Adobe creates-and-renews the new subscription in one shot,
invoiced immediately, and returns its new subscriptionId on the committed order.
Their MPT subscriptions are created after the order commits
(ResolveNetNewRenewedSubscriptions then CreateNetNewMptSubscriptions).
"""

import datetime as dt
import logging
from operator import itemgetter

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    CANCELLATION_WINDOW_DAYS,
    ORDER_STATUS_DESCRIPTION,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RENEWAL,
    UNRECOVERABLE_ORDER_STATUSES,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_RENEWAL_NET_NEW_FAILED,
    ERR_RENEWAL_ORDER_FAILED,
    ERR_RENEWAL_PREVIEW_FAILED,
    ERR_RENEWAL_RETURN_FAILED,
    ERR_RENEWAL_RETURN_WINDOW_CLOSED,
    ERR_RENEWAL_SUBSCRIPTION_UPDATE_FAILED,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    TEMPLATE_NAME_CHANGE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.renewal import (
    CreateNetNewMptSubscriptions,
    RecordClientDiscountCodes,
    RecordDiscountRedemptions,
    Validate3YCRenewalFloor,
)
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
from adobe_vipm.flows.utils import get_order_line_by_sku
from adobe_vipm.flows.utils.deployment import get_deployment_id
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


def _get_renewing_plans(context):
    """
    Return the plan's renewing subscriptions that still need a line submitted.

    Renewing subscriptions already committed in a previous renewal order with no
    requested quantity change are excluded — see _is_already_renewed.
    """
    return [
        plan
        for plan in context.renewal_plan_subscriptions
        if plan["renew"] and not _is_already_renewed(plan)
    ]


def _iter_net_new_lines(context):
    """
    Yield (extLineItemNumber, net_new_item) for the plan's net-new items.

    extLineItemNumber is a stable join key from the payload item to the committed
    RENEWAL line (whose offerId can differ from the ordered one across the renewal
    offer-type shift). The offset counts every renewing plan entry, not only the
    ones _get_renewing_plans currently submits: after this order's first commit a
    renewing entry can start matching _is_already_renewed (its renewedQuantity is
    now populated) and drop out of the submitted set, and on a retry that would
    shift the net-new numbers and misalign them against the existing committed
    order. Counting all renew=True entries keeps the numbering identical across
    retries.
    """
    offset = sum(1 for plan in context.renewal_plan_subscriptions if plan["renew"])
    net_new_items = (
        context.renewal_payload.get("netNewItems", []) if context.renewal_payload else []
    )
    for index, net_new_item in enumerate(net_new_items):
        yield offset + 1 + index, net_new_item


def _get_net_new_line_map(context):
    """Map extLineItemNumber -> net_new_item, matching the numbering used to build lines."""
    return dict(_iter_net_new_lines(context))


def _missing_net_new_offers(context, present_line_numbers):
    """
    Return the offerIds of expected net-new lines absent from present_line_numbers.

    The result is a comma-joined string (empty when every net-new line is present),
    ready for a user-facing error message.
    """
    net_new_by_line = _get_net_new_line_map(context)
    missing_numbers = sorted(set(net_new_by_line) - set(present_line_numbers))
    missing = [net_new_by_line[number] for number in missing_numbers]
    return ", ".join(net_new["offerId"] for net_new in missing)


def _build_renewing_line_items(context):
    """
    Build PREVIEW_RENEWAL/RENEWAL line items for the renewing subscriptions and net-new items.

    Renewing subscriptions already committed in a previous renewal order with no
    requested quantity change are excluded — see _is_already_renewed. Net-new items
    are appended after them, each carrying offerId + quantity and no subscriptionId:
    Adobe creates-and-renews the new subscription in the same order. Their
    extLineItemNumber continues after the renewing lines so the committed order can
    be matched back to the payload item (see _get_net_new_line_map).
    """
    line_items = []
    for number, plan in enumerate(_get_renewing_plans(context), start=1):
        line_item = {
            "extLineItemNumber": number,
            "offerId": plan["offer_id"],
            "subscriptionId": plan["subscription_id"],
            "quantity": plan["renewal_quantity"],
        }
        if plan["flex_discount_codes"]:
            line_item["flexDiscountCodes"] = plan["flex_discount_codes"]
        line_items.append(line_item)

    deployment_id = get_deployment_id(context.order)
    for number, net_new_item in _iter_net_new_lines(context):
        line_item = {
            "extLineItemNumber": number,
            "offerId": net_new_item["offerId"],
            "quantity": net_new_item["quantity"],
        }
        flex_discount_codes = net_new_item.get("flexDiscountCodes")
        if flex_discount_codes:
            line_item["flexDiscountCodes"] = flex_discount_codes
        if deployment_id:
            line_item["deploymentId"] = deployment_id
        line_items.append(line_item)
    return line_items


def _get_requested_flex_discount_codes(context):
    """
    Map each submitted line's extLineItemNumber to the flex codes selected for it.

    Covers both renewing subscriptions and net-new items, keyed by the same
    extLineItemNumber used to build the request lines, so the committed order can
    recover the requested codes for a net-new line that has no subscriptionId.
    """
    requested = {
        number: plan["flex_discount_codes"]
        for number, plan in enumerate(_get_renewing_plans(context), start=1)
    }
    for number, net_new_item in _iter_net_new_lines(context):
        requested[number] = net_new_item.get("flexDiscountCodes") or []
    return requested


def _get_committed_flex_discount_codes(preview_line_item, requested_codes):
    """
    Pick the flex discount code to commit for a PREVIEW_RENEWAL response line item.

    Only a code the plan explicitly selected for the line is committed, and
    only once the preview confirmed it (result SUCCESS). Reusable discounts
    the customer already holds are auto-applied by Adobe at renewal without
    any opt-in: the preview reports them alongside the requested ones, but
    they are never echoed back, so the commit does not double-apply them and
    an explicitly selected code takes precedence over them. Adobe accepts at
    most one code per line (it rejects more with error 2147), so a single
    surviving code is submitted.
    """
    flex_discounts = preview_line_item.get("flexDiscounts") or []
    line_number = preview_line_item.get("extLineItemNumber")
    successful = (fd for fd in flex_discounts if fd.get("result", "SUCCESS") == "SUCCESS")
    confirmed = {fd["code"] for fd in successful}
    committed = [code for code in requested_codes if code in confirmed]
    dropped = [code for code in requested_codes if code not in confirmed]
    if dropped:
        logger.warning(
            "Dropping flex discount code(s) not applied successfully by the renewal "
            "preview for line %s: %s",
            line_number,
            ", ".join(dropped),
        )
    auto_applied = sorted(confirmed.difference(requested_codes))
    if auto_applied:
        logger.info(
            "Leaving the discount(s) auto-applied by Adobe for line %s out of the renewal "
            "order, they apply without opt-in: %s",
            line_number,
            ", ".join(auto_applied),
        )
    if len(committed) > 1:
        logger.warning(
            "Renewal plan selected %s flex discounts for line %s, submitting only "
            "the first one (%s) to honour Adobe's one-code-per-line rule",
            len(committed),
            line_number,
            committed[0],
        )
    return committed[:1]


def _build_committed_line_items(preview_line_items, requested_codes_by_line):
    """
    Build RENEWAL order line items from a PREVIEW_RENEWAL response's line items.

    Mirrors how the PURCHASE flow turns its PREVIEW order into a NEW order
    (AdobeClient._build_line_item): the preview response is the source of
    truth for the offer and quantity actually being committed, but it is
    response-shaped (e.g. flexDiscounts is a list of discount result
    objects, not the flexDiscountCodes the create-order request expects) and
    carries pricing fields the create-order request doesn't need, so it is
    re-shaped into a request line item rather than forwarded as-is. A net-new
    line carries no subscriptionId (Adobe assigns it on the committed order),
    so it is only forwarded when present. The flex discount codes come from the
    plan's explicit selection per line, keyed by extLineItemNumber (stable
    across preview and commit) and confirmed by the preview (see
    _get_committed_flex_discount_codes).
    """
    line_items = []
    for preview_line_item in preview_line_items:
        line_item = {
            "extLineItemNumber": preview_line_item["extLineItemNumber"],
            "offerId": preview_line_item["offerId"],
            "quantity": preview_line_item["quantity"],
        }
        subscription_id = preview_line_item.get("subscriptionId")
        if subscription_id:
            line_item["subscriptionId"] = subscription_id
        requested_codes = requested_codes_by_line.get(preview_line_item["extLineItemNumber"])
        flex_discount_codes = _get_committed_flex_discount_codes(
            preview_line_item, requested_codes or []
        )
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

        if not self._ensure_net_new_previewed(client, context):
            return False

        logger.info(
            "%s: renewal preview validated for %s subscription(s)", context, len(line_items)
        )
        return True

    def _ensure_net_new_previewed(self, client, context):
        """
        Fail the order before commit when the preview omitted a requested net-new line.

        The renew-now RENEWAL order is invoiced immediately, so a net-new line the
        PREVIEW_RENEWAL did not accept must fail the order here — before anything is
        committed — rather than after commit, leaving nothing to reverse.
        """
        previewed = {
            line_item["extLineItemNumber"]
            for line_item in context.preview_renewal_order["lineItems"]
        }
        missing_offers = _missing_net_new_offers(context, previewed)
        if not missing_offers:
            return True

        logger.warning(
            "%s: renewal preview omitted net-new line(s) for offer(s): %s",
            context,
            missing_offers,
        )
        switch_order_to_failed(
            client,
            context.order,
            ERR_RENEWAL_NET_NEW_FAILED.to_dict(
                offer_id=missing_offers,
                error="line not present on the renewal preview",
            ),
        )
        return False


class SubmitRenewalNowOrder(Step):
    """
    Commit the renew-now plan as an actual Adobe RENEWAL order.

    Uses the line items validated by PreviewRenewalNowOrder — the renewal
    counterpart of how the PURCHASE flow turns its PREVIEW order into a NEW
    order. It is invoiced immediately and takes effect now. The existing
    Adobe RENEWAL order is detected by its external reference id, so a
    retry of this step is idempotent.

    Net-new lines (offerId + quantity, no subscriptionId) ride this same order;
    their MPT subscriptions are created afterwards by
    ResolveNetNewRenewedSubscriptions and CreateNetNewMptSubscriptions.
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
                _build_committed_line_items(
                    context.preview_renewal_order["lineItems"],
                    _get_requested_flex_discount_codes(context),
                ),
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


def _get_creation_date(order):
    creation_date = dt.datetime.fromisoformat(order["creationDate"])
    return creation_date.replace(tzinfo=dt.UTC).date()


def _is_within_return_window(order):
    """Return True when the Adobe order was placed within the return window (inclusive)."""
    today = dt.datetime.now(tz=dt.UTC).date()
    window_start = today - dt.timedelta(days=CANCELLATION_WINDOW_DAYS)
    return _get_creation_date(order) >= window_start


class ResolvePreviousRenewalReturns(Step):
    """
    Resolve, before anything is committed, the previous RENEWAL order lines to return.

    A lapsing subscription (renew = false) whose pre-mutation snapshot
    (taken by SetupRenewalPlan) carries a renewedQuantity was already
    committed in a previous RENEWAL order, so ReturnPreviousRenewalOrders
    has to return that order's line once this order's RENEWAL commits.
    Adobe only accepts a RETURN within CANCELLATION_WINDOW_DAYS of the order
    placement, so the previous order is located here and its creation date
    checked against the window while nothing has been committed yet: a line
    outside the window, or a previous order that cannot be found, fails the
    MPT order with nothing to reverse instead of leaving a committed and
    invoiced RENEWAL behind a Failed order. A RETURN already created by a
    previous attempt of this MPT order (detected by its external reference
    prefix) is reused as-is, whatever the window says today, so retries stay
    idempotent. The resolved candidates are stored on the context for
    ReturnPreviousRenewalOrders.
    """

    def __call__(self, client, context, next_step):
        """Resolve the previous RENEWAL order lines of the plan's lapsing subscriptions."""
        context.renewal_return_candidates = []
        lapsing_renewed = [
            plan
            for plan in context.renewal_plan_subscriptions
            if not plan["renew"] and plan["snapshot"]["renewed_quantity"] is not None
        ]
        if not lapsing_renewed:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        existing_return_orders = adobe_client.get_return_orders_by_external_reference(
            context.authorization_id,
            context.adobe_customer_id,
            context.order_id,
        )
        renewal_orders = self._get_completed_renewal_orders(adobe_client, context)
        for plan in lapsing_renewed:
            candidate = self._resolve_candidate(
                client, context, plan, renewal_orders, existing_return_orders
            )
            if candidate is None:
                return
            context.renewal_return_candidates.append(candidate)

        logger.info(
            "%s: %s previous renewal line(s) resolved for return",
            context,
            len(context.renewal_return_candidates),
        )
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

    def _resolve_candidate(  # noqa: WPS211
        self, client, context, plan, renewal_orders, existing_return_orders
    ):
        subscription_id = plan["subscription_id"]
        candidate = {
            "subscription_id": subscription_id,
            "return_order": None,
            "returning_order": None,
            "returning_line": None,
        }
        existing_returns = existing_return_orders.get(get_partial_sku(plan["offer_id"]))
        if existing_returns:
            logger.info(
                "%s: return order %s already exists for subscription %s",
                context,
                existing_returns[0]["orderId"],
                subscription_id,
            )
            return {**candidate, "return_order": existing_returns[0]}

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

        if not _is_within_return_window(returning_order):
            creation_date = _get_creation_date(returning_order).isoformat()
            logger.warning(
                "%s: previous renewal order %s for subscription %s was placed on %s, "
                "outside the %s-day return window",
                context,
                returning_order["orderId"],
                subscription_id,
                creation_date,
                CANCELLATION_WINDOW_DAYS,
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_RETURN_WINDOW_CLOSED.to_dict(
                    order_id=returning_order["orderId"],
                    subscription_id=subscription_id,
                    creation_date=creation_date,
                    window_days=CANCELLATION_WINDOW_DAYS,
                ),
            )
            return None

        return {
            **candidate,
            "returning_order": returning_order,
            "returning_line": returning_line,
        }

    def _find_previous_renewal_line(self, context, renewal_orders, subscription_id):
        for order in renewal_orders:
            if order["externalReferenceId"] == context.order_id:
                continue
            for line_item in order["lineItems"]:
                if line_item.get("subscriptionId") == subscription_id:
                    return order, line_item
        return None, None


class ReturnPreviousRenewalOrders(Step):
    """
    Return the previous RENEWAL order lines resolved by ResolvePreviousRenewalReturns.

    Each candidate is a lapsing subscription (renew = false) already
    committed in a previous RENEWAL order placed within the return window.
    Disabling its auto-renewal is not enough — the already-paid renewal must
    be undone, so this step submits a RETURN order referencing that previous
    RENEWAL order, returning only the lapsing subscription's line (other
    lines of that order stay renewed). Runs after SubmitRenewalNowOrder so
    the additive operation always precedes the subtractive one.

    Idempotent: a RETURN order already created by this MPT order is carried
    by the candidate and reused instead of re-submitted. A RETURN order
    still pending on Adobe's side keeps the MPT order in Processing to be
    retried on the next fulfillment attempt.
    """

    def __call__(self, client, context, next_step):
        """Return the previous RENEWAL order lines of the plan's lapsing subscriptions."""
        if not context.renewal_return_candidates:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        return_orders = []
        for candidate in context.renewal_return_candidates:
            return_order = candidate["return_order"] or self._create_return_order(
                client, adobe_client, context, candidate
            )
            if return_order is None:
                return
            return_orders.append(return_order)

        if not self._ensure_not_pending_return_orders(context, return_orders):
            return

        next_step(client, context)

    def _create_return_order(self, client, adobe_client, context, candidate):
        subscription_id = candidate["subscription_id"]
        returning_order = candidate["returning_order"]
        returning_line = candidate["returning_line"]
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


class ResolveNetNewRenewedSubscriptions(Step):
    """
    Resolve the Adobe subscriptions Adobe created for the plan's net-new items.

    A net-new item is submitted as a RENEWAL line with no subscriptionId; Adobe
    creates-and-renews the subscription in one shot and returns its new
    subscriptionId on that line of the committed order. This step matches each
    committed net-new line back to its payload item by extLineItemNumber (offerId
    can shift between the ordered and the renewal offer variant, so it is not a
    safe key), fetches the full Adobe subscription, and stores it on the context
    keyed by the payload offerId so CreateNetNewMptSubscriptions can create the MPT
    subscription. No-op when the plan has no net-new items or no RENEWAL order was
    committed. Idempotent: a retry reuses the existing RENEWAL order and re-resolves
    the same subscriptions.
    """

    def __call__(self, client, context, next_step):
        """Resolve the Adobe subscriptions created for the plan's net-new items."""
        net_new_by_line = _get_net_new_line_map(context)
        if not net_new_by_line or context.adobe_renewal_order is None:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        resolved_lines = set()
        for line_item in context.adobe_renewal_order.get("lineItems", []):
            net_new_item = net_new_by_line.get(line_item["extLineItemNumber"])
            if not net_new_item:
                continue
            if not self._resolve(client, adobe_client, context, line_item, net_new_item):
                return
            resolved_lines.add(line_item["extLineItemNumber"])

        if not self._ensure_all_resolved(client, context, resolved_lines):
            return

        next_step(client, context)

    def _ensure_all_resolved(self, client, context, resolved_lines):
        """Fail the order when the committed order omitted a requested net-new line."""
        missing_offers = _missing_net_new_offers(context, resolved_lines)
        if not missing_offers:
            return True

        logger.warning(
            "%s: committed renewal order is missing net-new line(s) for offer(s): %s",
            context,
            missing_offers,
        )
        switch_order_to_failed(
            client,
            context.order,
            ERR_RENEWAL_NET_NEW_FAILED.to_dict(
                offer_id=missing_offers,
                error="line not present on the committed renewal order",
            ),
        )
        return False

    def _resolve(self, client, adobe_client, context, line_item, net_new_item):
        """Fetch and store the Adobe subscription of a committed net-new line, False on failure."""
        offer_id = net_new_item["offerId"]
        subscription_id = line_item.get("subscriptionId")
        if not subscription_id:
            logger.warning(
                "%s: committed net-new line for offer %s has no subscriptionId",
                context,
                offer_id,
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_NET_NEW_FAILED.to_dict(
                    offer_id=offer_id,
                    error="committed renewal line has no subscriptionId",
                ),
            )
            return False

        try:
            subscription = adobe_client.get_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                subscription_id,
            )
        except AdobeAPIError as error:
            logger.warning(
                "%s: failed to resolve net-new subscription %s for offer %s: %s",
                context,
                subscription_id,
                offer_id,
                error,
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_RENEWAL_NET_NEW_FAILED.to_dict(offer_id=offer_id, error=error.message),
            )
            return False

        context.renewal_net_new_subscriptions[offer_id] = subscription
        logger.info(
            "%s: resolved net-new subscription %s for offer %s",
            context,
            subscription["subscriptionId"],
            offer_id,
        )
        return True


class ValidateNetNewOrderLines(Step):
    """
    Fail the order before any Adobe mutation when a net-new item has no MPT order line.

    CreateNetNewMptSubscriptions matches each net-new item to its MPT order line by SKU
    and skips an unmatched one. On the renew-now path that would leave Adobe having
    created-and-invoiced the subscription while the MPT order completes without it, so
    this step validates the mapping up front — before PREVIEW_RENEWAL — and fails the
    order with nothing committed instead.
    """

    def __call__(self, client, context, next_step):
        """Fail the order when a net-new item has no matching MPT order line."""
        unmatched = [
            net_new_item["offerId"]
            for _, net_new_item in _iter_net_new_lines(context)
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


def fulfill_renewal_now_order(client, order):
    """
    Fulfills a change order that carries a renew-now renewal payload.

    The plan's renewing subscriptions are validated with a PREVIEW_RENEWAL
    and committed as an actual Adobe RENEWAL order, invoiced immediately.
    Before that, the previous RENEWAL order lines of the lapsing
    subscriptions already committed are resolved and checked against the
    return window, so nothing is committed that cannot be undone. Net-new
    items ride the same RENEWAL order as extra lines and their MPT
    subscriptions are created after it commits. Once it
    completes, the previous lines are returned, the renewed
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
        ValidateNetNewOrderLines(),
        Validate3YCRenewalFloor(include_net_new_items=True),
        ResolvePreviousRenewalReturns(),
        PreviewRenewalNowOrder(),
        SubmitRenewalNowOrder(),
        ReturnPreviousRenewalOrders(),
        ResolveNetNewRenewedSubscriptions(),
        CreateNetNewMptSubscriptions(),
        NormalizeRenewedSubscriptions(),
        DisableLapsingSubscriptions(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        RecordClientDiscountCodes(),
        RecordDiscountRedemptions(),
        SetSubscriptionTemplate(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
