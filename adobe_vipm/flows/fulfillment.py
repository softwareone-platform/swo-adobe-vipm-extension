import logging

from django.conf import settings

from adobe_vipm.adobe.client import AdobeError, get_adobe_client
from adobe_vipm.flows.constants import (
    ORDER_STATUS_DESCRIPTION,
    STATUS_PENDING,
    STATUS_PROCESSED,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_seller,
    update_order,
    update_subscription,
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
    is_upsizing_order,
    set_adobe_order_id,
    update_subscription_item,
)

logger = logging.getLogger(__name__)


def _update_or_create_subscription(
    mpt_client, seller_country, customer_id, order, item
):
    adobe_client = get_adobe_client()
    adobe_subscription = adobe_client.get_subscription(
        seller_country,
        customer_id,
        item["subscriptionId"],
    )
    order_item = get_order_item(
        order,
        adobe_subscription["offerId"],
    )
    order_subscription = get_order_subscription(
        order,
        order_item["lineNumber"],
        order_item["productItemId"],
    )
    if not order_subscription:
        subscription = {
            "name": f"Subscription for {adobe_subscription['offerId']}",
            "parameters": {
                "fulfillment": [
                    {
                        "name": "SubscriptionId",
                        "value": item["subscriptionId"],
                    }
                ]
            },
            "items": [
                {
                    "lineNumber": order_item["lineNumber"],
                },
            ],
            "startDate": adobe_subscription["creationDate"],
        }
        subscription = create_subscription(mpt_client, order["id"], subscription)
        logger.info(
            f'Subscription {item["subscriptionId"]} ({subscription["id"]}) '
            f'created for order {order["id"]}'
        )
    else:
        order_subscription = update_subscription_item(
            order_subscription,
            order_item["lineNumber"],
            order_item["productItemId"],
            order_item["quantity"],
        )
        return update_subscription(
            mpt_client,
            order["id"],
            order_subscription["id"],
            {
                "items": order_subscription["items"],
            },
        )


def _place_new_order(mpt_client, seller_country, customer_id, order):
    adobe_client = get_adobe_client()
    adobe_order = None
    try:
        preview_order = adobe_client.create_preview_order(
            seller_country, customer_id, order
        )
        adobe_order = adobe_client.create_new_order(
            seller_country, customer_id, order["id"], preview_order
        )
        logger.info(f'New order created for {order["id"]}: {adobe_order["orderId"]}')
    except AdobeError as e:
        fail_order(mpt_client, order["id"], str(e))
        return None, None

    adobe_order_id = adobe_order["orderId"]
    order = set_adobe_order_id(order, adobe_order_id)
    logger.debug(
        f'Updating the order {order["id"]} to save order id into vendor external id'
    )
    order = update_order(mpt_client, order["id"], {"externalIDs": order["externalIDs"]})
    return order, adobe_order


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
        retry_count = get_retry_count(order)
        max_attemps = int(settings.EXTENSION_CONFIG.get("MAX_RETRY_ATTEMPS", "10"))
        if retry_count < max_attemps:
            order = increment_retry_count(order)
            order = update_order(
                mpt_client, order["id"], {"parameters": order["parameters"]}
            )
            logger.info(
                f'Order {order["id"]} ({adobe_order_id}) '
                "is still processing on Adobe side, wait.",
            )
            return
        logger.info(
            f'The order {order["id"]} ({adobe_order_id}) '
            f"has reached the maximum number ({max_attemps}) of attemps.",
        )
        fail_order(
            mpt_client, order["id"], f"Max processing attemps reached ({max_attemps})"
        )
        return
    elif adobe_order["status"] in UNRECOVERABLE_ORDER_STATUSES:
        fail_order(
            mpt_client, order["id"], ORDER_STATUS_DESCRIPTION[adobe_order["status"]]
        )
        return
    elif adobe_order["status"] != STATUS_PROCESSED:
        fail_order(
            mpt_client,
            order["id"],
            f"Unexpected status ({adobe_order['status']}) received from Adobe.",
        )
        return
    return adobe_order


def _fulfill_purchase_order(mpt_client, seller_country, order):
    customer_id = get_adobe_customer_id(order)
    if not customer_id:
        order = create_customer_account(mpt_client, seller_country, order)
        if not order:
            return

    customer_id = get_adobe_customer_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        order, adobe_order = _place_new_order(
            mpt_client, seller_country, customer_id, order
        )
        if not order:
            return
    adobe_order_id = order["externalIDs"]["vendor"]
    adobe_order = _check_adobe_order_fulfilled(
        mpt_client, seller_country, order, customer_id, adobe_order_id
    )
    if not adobe_order:
        return

    for item in adobe_order["lineItems"]:
        _update_or_create_subscription(
            mpt_client, seller_country, customer_id, order, item
        )

    complete_order(
        mpt_client, order["id"], settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"]
    )
    logger.info(f'Order {order["id"]} has been completed successfully')


def _fulfill_upsizing_order(client, seller_country, order):
    customer_id = get_adobe_customer_id(order["agreement"])
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        order, adobe_order = _place_new_order(
            client, seller_country, customer_id, order
        )
        if not order:
            return

    adobe_order_id = order["externalIDs"]["vendor"]
    adobe_order = _check_adobe_order_fulfilled(
        client, seller_country, order, customer_id, adobe_order_id
    )

    if not adobe_order:
        return

    for item in adobe_order["lineItems"]:
        _update_or_create_subscription(client, seller_country, customer_id, order, item)

    complete_order(
        client, order["id"], settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"]
    )
    logger.info(f'Order {order["id"]} has been completed successfully')


def fulfill_order(client, order):
    logger.info(f'Start processing {order["type"]} order {order["id"]}')
    seller_id = order["agreement"]["seller"]["id"]
    seller = get_seller(client, seller_id)
    seller_country = seller["address"]["country"]
    if is_purchase_order(order):
        _fulfill_purchase_order(client, seller_country, order)
    elif is_upsizing_order(order):  # pragma: no branch
        _fulfill_upsizing_order(client, seller_country, order)
