import copy
import logging

from django.conf import settings

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_INVALID_MEMBERSHIP,
    STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ORDER_TYPE_CHANGE,
    ORDER_TYPE_TERMINATION,
    PARAM_ADOBE_SKU,
    PARAM_MEMBERSHIP_ID,
)
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_buyer,
    query_order,
    update_order,
)
from adobe_vipm.flows.shared import create_customer_account, populate_order_info
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_membership_id,
    get_adobe_order_id,
    get_adobe_subscription_id,
    get_order_line,
    get_order_line_by_sku,
    get_ordering_parameter,
    get_retry_count,
    get_subscription_by_line_and_item_id,
    group_items_by_type,
    increment_retry_count,
    is_purchase_order,
    is_transfer_order,
    reset_retry_count,
    set_adobe_customer_id,
    set_adobe_order_id,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def _handle_retries(mpt_client, order, adobe_order_id, adobe_order_type="NEW"):
    retry_count = get_retry_count(order)
    max_attemps = int(settings.EXTENSION_CONFIG.get("MAX_RETRY_ATTEMPS", "10"))
    if retry_count < max_attemps:
        order = increment_retry_count(order)
        update_order(mpt_client, order["id"], parameters=order["parameters"])
        logger.info(
            f"Order {order['id']} ({adobe_order_id}: {adobe_order_type}) "
            "is still processing on Adobe side, wait.",
        )
        return
    logger.info(
        f'The order {order["id"]} ({adobe_order_id}) '
        f"has reached the maximum number ({max_attemps}) of attemps.",
    )
    reason = f"Max processing attemps reached ({max_attemps})."
    fail_order(mpt_client, order["id"], reason)
    logger.warning(f"Order {order['id']} has been failed: {reason}.")
    return


def _reset_retries(mpt_client, order):
    order = reset_retry_count(order)
    update_order(mpt_client, order["id"], parameters=order["parameters"])
    return order


def _complete_order(mpt_client, order):
    order = _reset_retries(mpt_client, order)
    complete_order(
        mpt_client, order["id"], settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"]
    )
    logger.info(f'Order {order["id"]} has been completed successfully')


def _create_subscription(mpt_client, seller_country, customer_id, order, item):
    adobe_client = get_adobe_client()
    adobe_subscription = adobe_client.get_subscription(
        seller_country,
        customer_id,
        item["subscriptionId"],
    )

    order_line = get_order_line_by_sku(order, item["offerId"])

    subscription = {
        "name": f"Subscription for {order_line['item']['name']}",
        "parameters": {
            "fulfillment": [
                {
                    "externalId": PARAM_ADOBE_SKU,
                    "value": item["offerId"],
                }
            ]
        },
        "externalIds": {
            "vendor": item["subscriptionId"],
        },
        "lines": [
            {
                "id": order_line["id"],
            },
        ],
        "startDate": adobe_subscription["creationDate"],
    }
    subscription = create_subscription(mpt_client, order["id"], subscription)
    logger.info(
        f'Subscription {item["subscriptionId"]} ({subscription["id"]}) '
        f'created for order {order["id"]}'
    )

def _check_adobe_subscriptions(seller_country, customer_id, order, lines):
    lines_to_order = []
    adobe_client = get_adobe_client()
    for line in lines:
        subcription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        adobe_sub_id = get_adobe_subscription_id(subcription)
        adobe_subscription = adobe_client.get_subscription(
            seller_country,
            customer_id,
            adobe_sub_id,
        )
        desired_quantity = line["quantity"]
        current_quantity = adobe_subscription["currentQuantity"]
        current_renewal_quantity = adobe_subscription["autoRenewal"]["renewalQuantity"]
        renewal_quantity = desired_quantity
        if desired_quantity > current_quantity:
            # If we have to upsize over the current quantity
            # we have to place an new order for the delta
            # and set the renewal quantity equals to the
            # current quantity (current quantity will be
            # update due to the new order for the delta.
            renewal_quantity = current_quantity
            line_to_order = copy.deepcopy(line)
            line_to_order["oldQuantity"] = current_quantity
            lines_to_order.append(line_to_order)

        if current_renewal_quantity < renewal_quantity:
            adobe_client.update_subscription(
                seller_country,
                customer_id,
                adobe_sub_id,
                quantity=renewal_quantity,
            )

    return lines_to_order


def _update_adobe_subscriptions(seller_country, customer_id, order, lines):
    adobe_client = get_adobe_client()
    for line in lines:
        subcription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        adobe_sub_id = get_adobe_subscription_id(subcription)
        adobe_subscription = adobe_client.get_subscription(
            seller_country,
            customer_id,
            adobe_sub_id,
        )
        if (
            order["type"] == ORDER_TYPE_TERMINATION
            and adobe_subscription["autoRenewal"]["enabled"]
        ):
            adobe_client.update_subscription(
                seller_country,
                customer_id,
                adobe_sub_id,
                auto_renewal=False,
            )
        if (
            order["type"] == ORDER_TYPE_CHANGE
            and adobe_subscription["autoRenewal"]["renewalQuantity"] != line["quantity"]
        ):
            adobe_client.update_subscription(
                seller_country,
                customer_id,
                adobe_sub_id,
                quantity=line["quantity"],
            )


def _place_return_orders(mpt_client, seller_country, customer_id, order, lines):
    adobe_client = get_adobe_client()
    completed_order_ids = []
    pending_order_ids = []
    for line in lines:
        orders_4_item = adobe_client.search_new_and_returned_orders_by_sku_line_number(
            seller_country,
            customer_id,
            line["item"]["externalIds"]["vendor"],
            line["id"],
        )
        for order_to_return, item_to_return, return_order in orders_4_item:
            if not return_order:
                logger.debug(f"Return order not found for {line['item']['id']}")
                return_order = adobe_client.create_return_order(
                    seller_country,
                    customer_id,
                    order_to_return,
                    item_to_return,
                )
                logger.debug(
                    f"Return order created for a return order for item: {line}"
                )
            if return_order["status"] == STATUS_PENDING:
                pending_order_ids.append(return_order["orderId"])
                break
            else:
                completed_order_ids.append(return_order["orderId"])
                order = _reset_retries(mpt_client, order)


    if pending_order_ids:
        _handle_retries(
            mpt_client, order, ", ".join(pending_order_ids), adobe_order_type="RETURN"
        )
        return None, order

    return completed_order_ids, order


def _place_new_order(mpt_client, seller_country, customer_id, order):
    adobe_client = get_adobe_client()
    adobe_order = None
    try:
        preview_order = adobe_client.create_preview_order(
            seller_country, customer_id, order["id"], order["lines"]
        )
        adobe_order = adobe_client.create_new_order(
            seller_country,
            customer_id,
            preview_order,
        )
        logger.info(f'New order created for {order["id"]}: {adobe_order["orderId"]}')
    except AdobeError as e:
        fail_order(mpt_client, order["id"], str(e))
        logger.warning(f"Order {order['id']} has been failed: {str(e)}.")
        return None

    adobe_order_id = adobe_order["orderId"]
    order = set_adobe_order_id(order, adobe_order_id)
    logger.debug(
        f'Updating the order {order["id"]} to save order id into vendor external id'
    )
    update_order(mpt_client, order["id"], externalIds=order["externalIds"])
    return order


def _place_change_order(mpt_client, seller_country, customer_id, order):
    adobe_client = get_adobe_client()
    adobe_order = None
    grouped_items = group_items_by_type(order)
    logger.debug(
        f"item groups: upwin={grouped_items.upsizing_in_win}, "
        f"downin={grouped_items.downsizing_in_win}, "
        f"downout={grouped_items.downsizing_out_win}",
    )
    try:
        to_add_to_preview = []
        if grouped_items.upsizing_out_win:
            to_add_to_preview = _check_adobe_subscriptions(
                seller_country,
                customer_id,
                order,
                grouped_items.upsizing_out_win,
            )

        if grouped_items.downsizing_out_win:
            _update_adobe_subscriptions(
                seller_country,
                customer_id,
                order,
                grouped_items.downsizing_out_win,
            )

        items_to_preview = (
            grouped_items.upsizing_in_win + grouped_items.downsizing_in_win + to_add_to_preview
        )

        if items_to_preview:
            preview_order = adobe_client.create_preview_order(
                seller_country,
                customer_id,
                order["id"],
                items_to_preview,
            )

            if grouped_items.downsizing_in_win:
                completed_return_orders, order = _place_return_orders(
                    mpt_client,
                    seller_country,
                    customer_id,
                    order,
                    grouped_items.downsizing_in_win,
                )

                if not completed_return_orders:
                    return None

            adobe_order = adobe_client.create_new_order(
                seller_country,
                customer_id,
                preview_order,
            )
            logger.info(f'New order created for {order["id"]}: {adobe_order["orderId"]}')
    except AdobeError as e:
        fail_order(mpt_client, order["id"], str(e))
        logger.warning(f"Order {order['id']} has been failed: {str(e)}.")
        return None
    if adobe_order:
        adobe_order_id = adobe_order["orderId"]
        order = set_adobe_order_id(order, adobe_order_id)
        logger.debug(
            f'Updating the order {order["id"]} to save order id into vendor external id'
        )
        update_order(mpt_client, order["id"], externalIds=order["externalIds"])
    return order


def _check_adobe_order_fulfilled(
    mpt_client, seller_country, order, customer_id, adobe_order_id
):
    adobe_client = get_adobe_client()
    adobe_order = adobe_client.get_order(
        seller_country,
        customer_id,
        adobe_order_id,
    )
    if adobe_order["status"] == STATUS_PENDING:
        _handle_retries(mpt_client, order, adobe_order_id)
        return
    elif adobe_order["status"] in UNRECOVERABLE_ORDER_STATUSES:
        reason = ORDER_STATUS_DESCRIPTION[adobe_order["status"]]
        fail_order(mpt_client, order["id"], reason)
        logger.warning(f"Order {order['id']} has been failed: {reason}.")
        return
    elif adobe_order["status"] != STATUS_PROCESSED:
        reason = f"Unexpected status ({adobe_order['status']}) received from Adobe."
        fail_order(mpt_client, order["id"], reason)
        logger.warning(f"Order {order['id']} has been failed: {reason}.")
        return
    return adobe_order


def _fulfill_purchase_order(mpt_client, seller_country, order):
    buyer_id = order["agreement"]["buyer"]["id"]
    buyer = get_buyer(mpt_client, buyer_id)
    customer_id = get_adobe_customer_id(order)
    if not customer_id:
        order = create_customer_account(mpt_client, seller_country, buyer, order)
        if not order:
            return

    customer_id = get_adobe_customer_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        order = _place_new_order(mpt_client, seller_country, customer_id, order)
        if not order:
            return
    adobe_order_id = order["externalIds"]["vendor"]
    adobe_order = _check_adobe_order_fulfilled(
        mpt_client, seller_country, order, customer_id, adobe_order_id
    )
    if not adobe_order:
        return

    for item in adobe_order["lineItems"]:
        _create_subscription(mpt_client, seller_country, customer_id, order, item)

    _complete_order(mpt_client, order)


def _fulfill_change_order(mpt_client, seller_country, order):
    customer_id = get_adobe_customer_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        order = _place_change_order(mpt_client, seller_country, customer_id, order)
        if not order:
            return

    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        _complete_order(mpt_client, order)
        return

    adobe_order = _check_adobe_order_fulfilled(
        mpt_client, seller_country, order, customer_id, adobe_order_id
    )

    if not adobe_order:
        return

    for item in adobe_order["lineItems"]:
        order_line = get_order_line(
            order,
            item["extLineItemNumber"],
        )
        order_subscription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            order_line["item"]["id"],
            order_line["id"],
        )
        if not order_subscription:
            _create_subscription(mpt_client, seller_country, customer_id, order, item)

    _complete_order(mpt_client, order)


def _fulfill_termination_order(mpt_client, seller_country, order):
    customer_id = get_adobe_customer_id(order)

    grouped_items = group_items_by_type(order)
    if grouped_items.downsizing_out_win:
        _update_adobe_subscriptions(
            seller_country, customer_id, order, grouped_items.downsizing_out_win
        )

    has_orders_to_return = bool(
        grouped_items.upsizing_in_win + grouped_items.downsizing_in_win
    )
    if not has_orders_to_return:
        _complete_order(mpt_client, order)
        return

    completed_return_orders, order = _place_return_orders(
        mpt_client,
        seller_country,
        customer_id,
        order,
        grouped_items.upsizing_in_win + grouped_items.downsizing_in_win,
    )

    if completed_return_orders:
        _complete_order(mpt_client, order)


def _handle_transfer_preview_error(client, order, e):
    if e.code in (
        STATUS_TRANSFER_INVALID_MEMBERSHIP,
        STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    ):
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=str(e)),
        )
        query_order(
            client,
            order["id"],
            parameters=order["parameters"],
            templateId=settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"],
        )
        return

    fail_order(client, order["id"], str(e))


def _check_transfer(mpt_client, seller_country, order, membership_id):
    adobe_client = get_adobe_client()
    transfer_preview = None
    try:
        transfer_preview = adobe_client.preview_transfer(seller_country, membership_id)
    except AdobeError as e:
        _handle_transfer_preview_error(mpt_client, order, e)
        logger.warning(f"Transfer order {order['id']} has been failed: {str(e)}.")
        return False

    adobe_lines = sorted(
        [
            (item["offerId"][:10], item["quantity"])
            for item in transfer_preview["items"]
        ],
        key=lambda i: i[0],
    )

    order_lines = sorted(
        [
            (line["item"]["externalIds"]["vendor"], line["quantity"])
            for line in order["lines"]
        ],
        key=lambda i: i[0],
    )
    if adobe_lines != order_lines:
        reason = (
            "The items owned by the given membership don't "
            f"match the order (sku or quantity): {','.join([line[0] for line in adobe_lines])}."
        )
        fail_order(mpt_client, order["id"], reason)
        logger.warning(f"Transfer 0rder {order['id']} has been failed: {reason}.")
        return False
    return True


def _place_transfer_order(mpt_client, seller_country, order, membership_id):
    adobe_client = get_adobe_client()
    adobe_transfer_order = None
    try:
        adobe_transfer_order = adobe_client.create_transfer(
            seller_country, order["id"], membership_id
        )
    except AdobeError as e:
        fail_order(mpt_client, order["id"], str(e))
        logger.warning(f"Transfer order {order['id']} has been failed: {str(e)}.")
        return None

    adobe_transfer_order_id = adobe_transfer_order["transferId"]
    order = set_adobe_order_id(order, adobe_transfer_order_id)
    logger.debug(
        f'Updating the order {order["id"]} to save transfer order id into vendor external id'
    )
    update_order(mpt_client, order["id"], externalIds=order["externalIds"])
    return order


def _check_adobe_transfer_order_fulfilled(
    mpt_client, seller_country, order, membership_id, adobe_transfer_id
):
    adobe_client = get_adobe_client()
    adobe_order = adobe_client.get_transfer(
        seller_country,
        membership_id,
        adobe_transfer_id,
    )
    if adobe_order["status"] == STATUS_PENDING:
        _handle_retries(mpt_client, order, adobe_transfer_id)
        return
    elif adobe_order["status"] != STATUS_PROCESSED:
        reason = f"Unexpected status ({adobe_order['status']}) received from Adobe."
        fail_order(mpt_client, order["id"], reason)
        logger.warning(f"Transfer {order['id']} has been failed: {reason}.")
        return
    return adobe_order


def _fulfill_transfer_order(mpt_client, seller_country, order):
    membership_id = get_adobe_membership_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        if not _check_transfer(mpt_client, seller_country, order, membership_id):
            return

        order = _place_transfer_order(mpt_client, seller_country, order, membership_id)
        if not order:
            return

        adobe_order_id = order["externalIds"]["vendor"]

    adobe_transfer_order = _check_adobe_transfer_order_fulfilled(
        mpt_client, seller_country, order, membership_id, adobe_order_id
    )
    if not adobe_transfer_order:
        return

    customer_id = adobe_transfer_order["customerId"]
    order = set_adobe_customer_id(order, customer_id)
    for item in adobe_transfer_order["lineItems"]:
        _create_subscription(mpt_client, seller_country, customer_id, order, item)
    _complete_order(mpt_client, order)


def fulfill_order(client, order):
    logger.info(f'Start processing {order["type"]} order {order["id"]}')
    order = populate_order_info(client, order)
    seller_country = order["agreement"]["seller"]["address"]["country"]
    if is_purchase_order(order):
        _fulfill_purchase_order(client, seller_country, order)
    elif is_transfer_order(order):
        _fulfill_transfer_order(client, seller_country, order)
    elif order["type"] == ORDER_TYPE_CHANGE:
        _fulfill_change_order(client, seller_country, order)
    elif order["type"] == ORDER_TYPE_TERMINATION:  # pragma: no branch
        _fulfill_termination_order(client, seller_country, order)
