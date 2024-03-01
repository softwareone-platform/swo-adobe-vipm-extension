import logging

from django.conf import settings

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    STATUS_PENDING,
    STATUS_PROCESSED,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    ORDER_TYPE_CHANGE,
    ORDER_TYPE_TERMINATION,
    PARAM_SUBSCRIPTION_ID,
)
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_agreement,
    get_buyer,
    get_product_items,
    update_order,
)
from adobe_vipm.flows.shared import create_customer_account
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_order_id,
    get_adobe_subscription_id,
    get_order_item,
    get_retry_count,
    get_subscription_by_line_and_item_id,
    group_items_by_type,
    increment_retry_count,
    is_purchase_order,
    reset_retry_count,
    set_adobe_order_id,
)

logger = logging.getLogger(__name__)


def _handle_retries(mpt_client, order, adobe_order_id, adobe_order_type="NEW"):
    retry_count = get_retry_count(order)
    max_attemps = int(settings.EXTENSION_CONFIG.get("MAX_RETRY_ATTEMPS", "10"))
    if retry_count < max_attemps:
        order = increment_retry_count(order)
        order = update_order(mpt_client, order["id"], parameters=order["parameters"])
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


def _complete_order(mpt_client, order):
    order = reset_retry_count(order)
    order = update_order(mpt_client, order["id"], parameters=order["parameters"])
    complete_order(mpt_client, order["id"], settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"])
    logger.info(f'Order {order["id"]} has been completed successfully')


def _create_subscription(mpt_client, seller_country, customer_id, order, item):
    adobe_client = get_adobe_client()
    adobe_subscription = adobe_client.get_subscription(
        seller_country,
        customer_id,
        item["subscriptionId"],
    )
    order_line = get_order_item(order, item["extLineItemNumber"])
    subscription = {
        "name": f"Subscription for {order_line['item']['name']}",
        "parameters": {
            "fulfillment": [
                {
                    "externalId": PARAM_SUBSCRIPTION_ID,
                    "value": item["subscriptionId"],
                }
            ]
        },
        "lines": [
            {
                "id": item["extLineItemNumber"],
            },
        ],
        "startDate": adobe_subscription["creationDate"],
    }
    subscription = create_subscription(mpt_client, order["id"], subscription)
    logger.info(
        f'Subscription {item["subscriptionId"]} ({subscription["id"]}) '
        f'created for order {order["id"]}'
    )


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
        if order["type"] == ORDER_TYPE_TERMINATION and adobe_subscription["autoRenewal"]["enabled"]:
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
            line["item"]["id"],
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
                logger.debug(f"Return order created for a return order for item: {line}")
            if return_order["status"] == STATUS_PENDING:
                pending_order_ids.append(return_order["orderId"])
            else:
                completed_order_ids.append(return_order["orderId"])

    if pending_order_ids:
        _handle_retries(mpt_client, order, ", ".join(pending_order_ids), adobe_order_type="RETURN")
        return None

    return completed_order_ids


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
        return None, None

    adobe_order_id = adobe_order["orderId"]
    order = set_adobe_order_id(order, adobe_order_id)
    logger.debug(f'Updating the order {order["id"]} to save order id into vendor external id')
    update_order(mpt_client, order["id"], externalIds=order["externalIds"])
    return order, adobe_order


def _place_change_order(mpt_client, seller_country, customer_id, order):
    adobe_client = get_adobe_client()
    adobe_order = None
    grouped_items = group_items_by_type(order)

    try:
        preview_order = adobe_client.create_preview_order(
            seller_country,
            customer_id,
            order["id"],
            grouped_items.upsizing + grouped_items.downsizing_in_win,
        )
        if grouped_items.downsizing_out_win:
            _update_adobe_subscriptions(
                seller_country,
                customer_id,
                order,
                grouped_items.downsizing_out_win,
            )
        if grouped_items.downsizing_in_win:
            completed_return_orders = _place_return_orders(
                mpt_client,
                seller_country,
                customer_id,
                order,
                grouped_items.downsizing_in_win,
            )

            if not completed_return_orders:
                return None, None

        adobe_order = adobe_client.create_new_order(
            seller_country,
            customer_id,
            preview_order,
        )
        logger.info(f'New order created for {order["id"]}: {adobe_order["orderId"]}')
    except AdobeError as e:
        fail_order(mpt_client, order["id"], str(e))
        logger.warning(f"Order {order['id']} has been failed: {str(e)}.")
        return None, None

    adobe_order_id = adobe_order["orderId"]
    order = set_adobe_order_id(order, adobe_order_id)
    logger.debug(f'Updating the order {order["id"]} to save order id into vendor external id')
    order = update_order(mpt_client, order["id"], externalIds=order["externalIds"])
    return order, adobe_order


def _check_adobe_order_fulfilled(mpt_client, seller_country, order, customer_id, adobe_order_id):
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
        order, adobe_order = _place_new_order(mpt_client, seller_country, customer_id, order)
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
        order, adobe_order = _place_change_order(mpt_client, seller_country, customer_id, order)
        if not order:
            return

    adobe_order_id = order["externalIds"]["vendor"]
    adobe_order = _check_adobe_order_fulfilled(
        mpt_client, seller_country, order, customer_id, adobe_order_id
    )

    if not adobe_order:
        return

    for item in adobe_order["lineItems"]:
        order_item = get_order_item(
            order,
            item["extLineItemNumber"],
        )
        order_subscription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            order_item["item"]["id"],
            order_item["id"],
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

    has_orders_to_return = bool(grouped_items.upsizing + grouped_items.downsizing_in_win)
    completed_return_orders = None

    if has_orders_to_return:
        completed_return_orders = _place_return_orders(
            mpt_client,
            seller_country,
            customer_id,
            order,
            grouped_items.upsizing + grouped_items.downsizing_in_win,
        )
    if not has_orders_to_return or has_orders_to_return and completed_return_orders:
        _complete_order(mpt_client, order)


def _populate_order_lines(client, lines):
    item_ids = set([line["item"]["id"] for line in lines])

    product_items = get_product_items(client, settings.PRODUCT_ID, item_ids)
    id_sku_mapping = {
        pi["id"]: pi["externalIds"]["vendor"]
        for pi in product_items
        if pi.get("externalIds", {}).get("vendor")
    }

    for line in lines:
        line["item"]["externalIds"] = {"vendor": id_sku_mapping[line["item"]["id"]]}

    return lines


def _populate_order_info(client, order):
    if "lines" in order:
        order["lines"] = _populate_order_lines(client, order["lines"])

    return order


def fulfill_order(client, order):
    logger.info(f'Start processing {order["type"]} order {order["id"]}')
    order = _populate_order_info(client, order)
    agreement = get_agreement(client, order["agreement"]["id"])
    order["agreement"] = agreement
    seller_country = agreement["seller"]["address"]["country"]
    if is_purchase_order(order):
        _fulfill_purchase_order(client, seller_country, order)
    elif order["type"] == ORDER_TYPE_CHANGE:
        _fulfill_change_order(client, seller_country, order)
    elif order["type"] == ORDER_TYPE_TERMINATION:  # pragma: no branch
        _fulfill_termination_order(client, seller_country, order)
