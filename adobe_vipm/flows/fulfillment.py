import logging

from django.conf import settings

from adobe_vipm.adobe.client import AdobeError, get_adobe_client
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_seller,
    update_order,
)
from adobe_vipm.flows.shared import create_customer_account
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_order_id,
    get_order_item,
    is_purchase_order,
    set_adobe_order_id,
)

logger = logging.getLogger(__name__)


def _fulfill_purchase_order(client, seller_country, order):
    adobe_client = get_adobe_client()
    customer_id = get_adobe_customer_id(order)
    if not customer_id:
        order = create_customer_account(client, seller_country, order)
        if not order:
            return

    customer_id = get_adobe_customer_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        adobe_order = None
        try:
            preview_order = adobe_client.create_preview_order(
                seller_country, customer_id, order
            )
            adobe_order = adobe_client.create_new_order(
                seller_country, customer_id, preview_order
            )
            logger.info(
                f'New order created for {order["id"]}: {adobe_order["orderId"]}'
            )
        except AdobeError as e:
            fail_order(client, order["id"], str(e))
            return

        adobe_order_id = adobe_order["orderId"]
        order = set_adobe_order_id(order, adobe_order_id)
        logger.debug(
            f'Updating the order {order["id"]} to save the OrderId fulfillment parameter'
        )
        order = update_order(client, order["id"], {"parameters": order["parameters"]})

    if not order.get("subscriptions"):
        adobe_order = adobe_client.get_order(
            seller_country,
            customer_id,
            adobe_order_id,
        )
        if adobe_order["status"] != "1000":
            logger.info(
                f'Order {order["id"]} ({adobe_order_id}) '
                "is still processing on Adobe side, wait.",
            )
            return

        for item in adobe_order["lineItems"]:
            adobe_subscription = adobe_client.get_subscription(
                seller_country,
                customer_id,
                item["subscriptionId"],
            )
            order_item = get_order_item(
                order,
                adobe_subscription["offerId"],
            )
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
            create_subscription(client, order["id"], subscription)
            logger.info(
                f'Subscription {item["subscriptionId"]} created for order {order["id"]}'
            )
        complete_order(
            client, order["id"], settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"]
        )
        logger.info(f'Order {order["id"]} has been completed successfully')


def fulfill_order(client, order):
    logger.info(f'Start processing {order["type"]} order {order["id"]}')
    seller_id = order["agreement"]["seller"]["id"]
    seller = get_seller(client, seller_id)
    seller_country = seller["address"]["country"]
    if is_purchase_order(order):  # pragma: no branch
        _fulfill_purchase_order(client, seller_country, order)
        return
