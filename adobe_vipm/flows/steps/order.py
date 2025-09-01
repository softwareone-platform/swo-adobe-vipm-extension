import itertools
import logging
from operator import itemgetter

from mpt_extension_sdk.mpt_http.mpt import (
    complete_order,
    get_product_template_or_default,
    update_order,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    UNRECOVERABLE_ORDER_STATUSES,
    AdobeStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeProductNotFoundError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_ERROR,
    ERR_INVALID_TERMINATION_ORDER_QUANTITY,
    ERR_MEMBERSHIP_ITEMS_DONT_MATCH,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    FAKE_CUSTOMERS_IDS,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    Param,
)
from adobe_vipm.flows.fulfillment.shared import send_mpt_notification, switch_order_to_failed
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.steps.validation import handle_transfer_preview_error
from adobe_vipm.flows.utils.customer import is_within_coterm_window
from adobe_vipm.flows.utils.date import reset_due_date
from adobe_vipm.flows.utils.deployment import get_deployment_id
from adobe_vipm.flows.utils.order import (
    add_lines_to_order,
    map_returnable_to_return_orders,
    set_adobe_order_id,
    set_order_error,
    set_template,
)
from adobe_vipm.flows.utils.subscription import get_subscription_by_line_subs_id
from adobe_vipm.flows.utils.validation import validate_subscription_and_returnable_orders
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

logger = logging.getLogger(__name__)


class GetPreviewOrder(Step):
    """
    Retrieve a preview order for the upsize/new lines.

    If there are incompatible SKUs
    within the PREVIEW order an error will be thrown by the Adobe API the order will
    be failed and the processing pipeline will stop.
    In case a new order as already been submitted by a previous attempt, this step will be
    skipped and the order processing pipeline will continue.
    """

    def __call__(self, client, context, next_step):
        """Retrieve a preview order for the upsize/new lines."""
        adobe_client = get_adobe_client()
        if (context.upsize_lines or context.new_lines) and not context.adobe_new_order_id:
            try:
                deployment_id = get_deployment_id(context.order)
                context.adobe_preview_order = adobe_client.create_preview_order(
                    context.authorization_id,
                    context.adobe_customer_id,
                    context.order_id,
                    context.upsize_lines,
                    context.new_lines,
                    deployment_id=deployment_id,
                )
            except AdobeError as e:
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(e)),
                )
                return

        next_step(client, context)


class GetPreviewOrderForUpsizeLines(Step):
    """
    Retrieve a preview order for the upsize/new lines.

    If there are incompatible SKUs within the PREVIEW order an error will be thrown by the
    Adobe API the draft validation fails, otherwise the draft order validation
    pipeline will continue.
    """

    def __call__(self, client, context, next_step):
        """Retrieve a preview order for the upsize/new lines."""
        if not (context.upsize_lines or context.new_lines):
            next_step(client, context)
            return

        customer_id = context.adobe_customer_id or FAKE_CUSTOMERS_IDS[context.market_segment]
        adobe_client = get_adobe_client()
        try:
            deployment_id = get_deployment_id(context.order)
            context.adobe_preview_order = adobe_client.create_preview_order(
                context.authorization_id,
                customer_id,
                context.order_id,
                context.upsize_lines,
                context.new_lines,
                deployment_id=deployment_id,
            )
        except AdobeAPIError as e:
            context.validation_succeeded = False
            context.order = set_order_error(context.order, ERR_ADOBE_ERROR.to_dict(details=str(e)))
            return
        except AdobeProductNotFoundError as e:
            context.validation_succeeded = False
            context.order = set_order_error(context.order, ERR_ADOBE_ERROR.to_dict(details=str(e)))
            return
        next_step(client, context)


class CompleteOrder(Step):
    """Complete MPT Order with template."""

    def __init__(self, template_name):
        self.template_name = template_name

    def __call__(self, client, context, next_step):
        """Complete MPT Order with template."""
        context.order = reset_due_date(context.order)
        template = get_product_template_or_default(
            client,
            context.product_id,
            MPT_ORDER_STATUS_COMPLETED,
            self.template_name,
        )
        agreement = context.order["agreement"]
        context.order = complete_order(
            client,
            context.order_id,
            template,
            parameters=context.order["parameters"],
        )
        context.order["agreement"] = agreement
        send_mpt_notification(client, context.order)
        logger.info("%s: order has been completed successfully", context)
        next_step(client, context)


class SubmitNewOrder(Step):
    """
    Submit a new order if there are new/upsizing items to purchase.

    Wait for the order to be processed by Adobe before moving to
    the next step.
    """

    def __call__(self, client, context, next_step):  # noqa: C901
        """Submit a new order if there are new/upsizing items to purchase."""
        if not (context.upsize_lines or context.new_lines):
            logger.info("%s: skip creating order. There are no upsize lines or new lines", context)
            next_step(client, context)
            return
        adobe_client = get_adobe_client()
        adobe_order = None

        if not context.adobe_new_order_id and context.adobe_preview_order:
            deployment_id = get_deployment_id(context.order)
            adobe_order = adobe_client.create_new_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.adobe_preview_order,
                deployment_id=deployment_id,
            )
            logger.info("%s: new adobe order created: %s", context, adobe_order["orderId"])
            context.order = set_adobe_order_id(context.order, adobe_order["orderId"])
            update_order(client, context.order_id, externalIds=context.order["externalIds"])
        elif not context.adobe_new_order_id and not context.adobe_preview_order:
            logger.info(
                "%s: skip creating Adobe Order, preview order creation was skipped",
                context,
            )
            next_step(client, context)
            return
        else:
            adobe_order = adobe_client.get_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.adobe_new_order_id,
            )
        context.adobe_new_order = adobe_order
        context.adobe_new_order_id = adobe_order["orderId"]
        if adobe_order["status"] == AdobeStatus.PENDING:
            logger.info("%s: adobe order %s is still pending.", context, context.adobe_new_order_id)
            return

        if adobe_order["status"] in UNRECOVERABLE_ORDER_STATUSES:
            error = ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS.to_dict(
                description=ORDER_STATUS_DESCRIPTION[adobe_order["status"]],
            )
            switch_order_to_failed(
                client,
                context.order,
                error,
            )
            logger.warning("%s: The adobe order has been failed %s.", context, error["message"])
            return

        if adobe_order["status"] != AdobeStatus.PROCESSED:
            error = ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status=adobe_order["status"])
            switch_order_to_failed(client, context.order, error)
            logger.warning("%s: the order has been failed due to %s.", context, error["message"])
            return
        next_step(client, context)


class StartOrderProcessing(Step):
    """
    Set the template for the processing status.

    Or the delayed one if the processing is delated due to the renewal window open.
    """

    def __init__(self, template_name):
        self.template_name = template_name

    def __call__(self, client, context, next_step):
        """Set the template for the processing status."""
        template = get_product_template_or_default(
            client,
            context.order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            self.template_name,
        )
        current_template_id = context.order.get("template", {}).get("id")
        if template["id"] != current_template_id:
            context.order = set_template(context.order, template)
            update_order(client, context.order_id, template=context.order["template"])
            logger.info(
                "%s: processing template set to %s (%s)",
                context,
                self.template_name,
                template["id"],
            )
        logger.info("%s: processing template is ok, continue", context)
        if not context.due_date:
            send_mpt_notification(client, context.order)
        next_step(client, context)


class GetReturnOrders(Step):
    """Retrieves Adobe Return orders from Adobe API."""

    def __call__(self, client, context, next_step):
        """Retrieves Adobe Return orders from Adobe API."""
        adobe_client = get_adobe_client()
        context.adobe_return_orders = adobe_client.get_return_orders_by_external_reference(
            context.authorization_id,
            context.adobe_customer_id,
            context.order_id,
        )
        return_orders_count = sum(len(x) for x in context.adobe_return_orders.values())
        logger.info("%s: found %s return order", context, return_orders_count)
        next_step(client, context)


class SubmitReturnOrders(Step):
    """
    Creates the return orders for each returnable order to match the downsize quantities.

    Wait for the return orders to be processed before moving to the next step.
    """

    def __call__(self, client, context, next_step):
        """Creates the return orders for each returnable order to match the downsize quantities."""
        adobe_client = get_adobe_client()
        all_return_orders = []
        deployment_id = get_deployment_id(context.order)
        is_returnable = False

        logger.info(
            "%s: Initializing SubmitReturnOrders. deployment_id=%s, skus_returnables=%s",
            context,
            deployment_id,
            list(context.adobe_returnable_orders.keys()),
        )

        for sku, returnable_orders in context.adobe_returnable_orders.items():
            return_orders = context.adobe_return_orders.get(sku, [])
            for returnable_order, return_order in map_returnable_to_return_orders(
                returnable_orders or [], return_orders
            ):
                returnable_order_deployment_id = returnable_order.line.get("deploymentId", None)
                is_returnable = (
                    (deployment_id == returnable_order_deployment_id) if deployment_id else True
                )
                logger.info(
                    "%s: SKU=%s, returnable_order_id=%s, deployment_id=%s, is_returnable=%s, "
                    "return_order_exists=%s",
                    context,
                    sku,
                    returnable_order.order.get("orderId", None),
                    returnable_order_deployment_id,
                    is_returnable,
                    bool(return_order),
                )
                if is_returnable:
                    if return_order:
                        all_return_orders.append(return_order)
                        continue
                    all_return_orders.append(
                        adobe_client.create_return_order(
                            context.authorization_id,
                            context.adobe_customer_id,
                            returnable_order.order,
                            returnable_order.line,
                            context.order_id,
                            deployment_id,
                        )
                    )
        pending_orders = [
            return_order["orderId"]
            for return_order in all_return_orders
            if return_order["status"] != AdobeStatus.PROCESSED
        ]

        if pending_orders:
            logger.info(
                "%s: There are pending return orders %s",
                context,
                ", ".join(pending_orders),
            )
            return

        next_step(client, context)


class GetReturnableOrders(Step):
    """
    Compute a map of returnable orders.

    it retrieves all the NEW or RENEWAL Adobe
    placed at most 14 days ago (cancellation window) and not
    after two weeks before the anniversary date.
    The computed dictionary map a SKU to a list of ReturnableOrderInfo
    so the sum of the quantity of such list of returnable orders match the downsize
    quantity if a sum that match such quantity exists.
    """

    def __call__(self, client, context, next_step):  # noqa: C901
        """Compute a map of returnable orders."""
        adobe_client = get_adobe_client()
        returnable_orders_count = 0
        if is_within_coterm_window(context.adobe_customer):
            logger.info(
                "Downsize occurs in the last two weeks before the anniversary date. "
                "Returnable orders are not going to be submitted, the renewal quantity "
                "will be updated."
            )
            next_step(client, context)
            return

        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            subscription_id = get_subscription_by_line_subs_id(
                context.order["agreement"]["subscriptions"], line
            )
            returnable_orders = adobe_client.get_returnable_orders_by_subscription_id(
                context.authorization_id,
                context.adobe_customer_id,
                subscription_id,
                context.adobe_customer["cotermDate"],
                return_orders=context.adobe_return_orders.get(sku),
            )
            if not returnable_orders:
                logger.info("%s: no returnable orders found for sku %s", context, sku)
                continue
            returnable_orders_count += len(returnable_orders)
            returnable_by_quantity = {}
            for r in range(len(returnable_orders), 0, -1):
                for sub in itertools.combinations(returnable_orders, r):
                    returnable_by_quantity[sum(line_item.quantity for line_item in sub)] = sub

            delta = line["oldQuantity"] - line["quantity"]
            if delta not in returnable_by_quantity:
                context.adobe_returnable_orders[sku] = None
                continue

            context.adobe_returnable_orders[sku] = returnable_by_quantity[delta]
        logger.info("%s: found %s returnable orders.", context, returnable_orders_count)
        next_step(client, context)


class GetReturnableOrdersForTermination(Step):
    """For each SKU retrieve all the orders that can be returned."""

    def __call__(self, client, context, next_step):
        """For each SKU retrieve all the orders that can be returned."""
        adobe_client = get_adobe_client()
        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            subscription_id = get_subscription_by_line_subs_id(
                context.order["agreement"]["subscriptions"], line
            )
            is_valid, returnable_orders = validate_subscription_and_returnable_orders(
                adobe_client,
                context,
                line,
                subscription_id,
                return_orders=context.adobe_return_orders.get(sku),
            )
            logger.info("%s: returnable orders: %s for %s", context, returnable_orders, sku)
            if not is_valid:
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict(),
                )
                return

            context.adobe_returnable_orders[sku] = returnable_orders

        returnable_orders_count = sum(len(v) for v in context.adobe_returnable_orders.values())
        logger.info("%s: found %s returnable orders.", context, returnable_orders_count)
        next_step(client, context)


def check_transfer(mpt_client, order, membership_id):
    """
    Checks the validity of a transfer order based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order being processed.
        membership_id (str): The Adobe membership ID associated with the transfer.

    Returns:
        bool: True if the transfer is valid, False otherwise.
    """
    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    transfer_preview = None
    try:
        transfer_preview = adobe_client.preview_transfer(authorization_id, membership_id)
    except AdobeError as e:
        handle_transfer_preview_error(mpt_client, order, e)
        logger.warning("Transfer order %s has been failed: %s.", order["id"], str(e))
        return False

    adobe_lines = sorted(
        [
            (get_partial_sku(item["offerId"]), item["quantity"])
            for item in transfer_preview["items"]
        ],
        key=itemgetter(0),
    )

    order_lines = sorted(
        [(line["item"]["externalIds"]["vendor"], line["quantity"]) for line in order["lines"]],
        key=itemgetter(0),
    )
    if adobe_lines != order_lines:
        error = ERR_MEMBERSHIP_ITEMS_DONT_MATCH.to_dict(
            lines=",".join([line[0] for line in adobe_lines]),
        )
        switch_order_to_failed(mpt_client, order, error)
        logger.warning("Transfer %s has been failed: %s.", order["id"], error["message"])
        return False
    return True


class AddLinesToOrder(Step):
    """Add adobe lines to order."""

    def __call__(self, mpt_client, context, next_step):
        """Add adobe lines to order."""
        commitment = get_3yc_commitment(context.adobe_customer)
        has_error, order = add_lines_to_order(
            mpt_client,
            context.order,
            context.subscriptions["items"],
            commitment,
            Param.CURRENT_QUANTITY.value,
            is_transferred=True,
        )
        context.order = order
        context.validation_succeeded = not has_error
        next_step(mpt_client, context)
