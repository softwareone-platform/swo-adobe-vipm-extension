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
from adobe_vipm.flows.constants import ORDER_TYPE_CHANGE, PARAM_SUBSCRIPTION_ID
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_agreement,
    get_buyer,
    get_seller,
    update_order,
)
from adobe_vipm.flows.shared import create_customer_account
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_order_id,
    get_order_item,
    get_order_subscription,
    get_retry_count,
    increment_retry_count,
    is_purchase_order,
    reset_retry_count,
    set_adobe_order_id,
)

logger = logging.getLogger(__name__)


def _handle_retries(mpt_client, order, adobe_order_id):
    retry_count = get_retry_count(order)
    max_attemps = int(settings.EXTENSION_CONFIG.get("MAX_RETRY_ATTEMPS", "10"))
    if retry_count < max_attemps:
        order = increment_retry_count(order)
        order = update_order(mpt_client, order["id"], {"parameters": order["parameters"]})
        logger.info(
            f"Order {order['id']} ({adobe_order_id}) is still processing on Adobe side, wait.",
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
    order = update_order(mpt_client, order["id"], {"parameters": order["parameters"]})
    complete_order(mpt_client, order["id"], settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"])
    logger.info(f'Order {order["id"]} has been completed successfully')


def _create_subscription(mpt_client, seller_country, customer_id, order, item):
    adobe_client = get_adobe_client()
    adobe_subscription = adobe_client.get_subscription(
        seller_country,
        customer_id,
        item["subscriptionId"],
    )
    order_item = get_order_item(order, item["extLineItemNumber"])
    subscription = {
        "name": f"Subscription for {order_item['name']}",
        "parameters": {
            "fulfillment": [
                {
                    "name": PARAM_SUBSCRIPTION_ID,
                    "value": item["subscriptionId"],
                }
            ]
        },
        "items": [
            {
                "lineNumber": item["extLineItemNumber"],
            },
        ],
        "startDate": adobe_subscription["creationDate"],
    }
    subscription = create_subscription(mpt_client, order["id"], subscription)
    logger.info(
        f'Subscription {item["subscriptionId"]} ({subscription["id"]}) '
        f'created for order {order["id"]}'
    )


def _place_new_order(mpt_client, seller_country, customer_id, order):
    adobe_client = get_adobe_client()
    adobe_order = None
    try:
        preview_order = adobe_client.create_preview_order(seller_country, customer_id, order)
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
    order = update_order(mpt_client, order["id"], {"externalIDs": order["externalIDs"]})
    return order, adobe_order


def _place_change_order(mpt_client, seller_country, customer_id, order):
    adobe_client = get_adobe_client()
    adobe_order = None
    try:
        preview_order = adobe_client.create_preview_order(seller_country, customer_id, order)

        pending_return_orders = False
        pending_order_ids = []
        for item in order["items"]:
            if item["oldQuantity"] <= item["quantity"]:
                continue
            last_order = adobe_client.search_last_order_by_sku(
                seller_country,
                customer_id,
                item["productItemId"],
            )
            logger.debug(f"Order to return for item {item['productItemId']}: {last_order}")
            # TODO handle last order not found
            return_order = adobe_client.search_last_return_order_by_order(
                seller_country,
                customer_id,
                last_order["orderId"],
            )
            if not return_order:
                logger.debug(f"Return order not found for {item['productItemId']}")
                return_order = adobe_client.create_return_order(
                    seller_country,
                    customer_id,
                    last_order["orderId"],
                    order,
                    item,
                )
                logger.debug(f"Return order created for a return order for item: {item}")

            pending_return_orders = (
                pending_return_orders or return_order["status"] == STATUS_PENDING
            )
            pending_order_ids.append(return_order["orderId"])

        if pending_return_orders:
            _handle_retries(mpt_client, order, ", ".join(pending_order_ids))
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
    order = update_order(mpt_client, order["id"], {"externalIDs": order["externalIDs"]})
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


def _fulfill_purchase_order(mpt_client, seller_country, agreement, order):
    buyer_id = agreement["buyer"]["id"]
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
    adobe_order_id = order["externalIDs"]["vendor"]
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

    adobe_order_id = order["externalIDs"]["vendor"]
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
        order_subscription = get_order_subscription(
            order,
            order_item["lineNumber"],
            order_item["productItemId"],
        )
        if not order_subscription:
            _create_subscription(mpt_client, seller_country, customer_id, order, item)

    _complete_order(mpt_client, order)


def fulfill_order(client, order):
    logger.info(f'Start processing {order["type"]} order {order["id"]}')
    agreement = get_agreement(client, order["agreement"]["id"])
    seller_id = agreement["seller"]["id"]
    seller = get_seller(client, seller_id)
    seller_country = seller["address"]["country"]
    if is_purchase_order(order):
        _fulfill_purchase_order(client, seller_country, agreement, order)
    elif order["type"] == ORDER_TYPE_CHANGE:  # pragma: no branch
        _fulfill_change_order(client, seller_country, order)
