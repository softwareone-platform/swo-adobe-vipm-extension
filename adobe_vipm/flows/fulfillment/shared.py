"""
This module contains shared functions used by the different fulfillment flows.
"""

import logging
from datetime import datetime, timedelta
from operator import itemgetter

from django.conf import settings

from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    STATUS_PENDING,
    STATUS_PROCESSED,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.adobe.utils import get_3yc_commitment
from adobe_vipm.flows.constants import (
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    MPT_ORDER_STATUS_QUERYING,
    PARAM_3YC,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_ADOBE_SKU,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_pricelist_items_by_product_items,
    get_product_items_by_skus,
    get_product_onetime_items_by_ids,
    get_product_template_or_default,
    get_rendered_template,
    get_subscription_by_external_id,
    query_order,
    set_processing_template,
    update_agreement,
    update_order,
    update_subscription,
)
from adobe_vipm.flows.utils import (
    get_notifications_recipient,
    get_order_line_by_sku,
    get_price_item_by_line_sku,
    get_retry_count,
    increment_retry_count,
    md2html,
    reset_retry_count,
    set_adobe_3yc_commitment_request_status,
    set_adobe_3yc_end_date,
    set_adobe_3yc_enroll_status,
    set_adobe_3yc_start_date,
    set_adobe_customer_id,
    set_adobe_order_id,
    set_customer_data,
    set_next_sync,
    split_phone_number,
)
from adobe_vipm.notifications import send_email

logger = logging.getLogger(__name__)


def save_adobe_customer_data(client, order, customer_id, request_3yc_status=None):
    """
    Sets the Adobe customer ID on the provided order and updates it using the MPT client.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order that needs to be updated.
        customer_id (str): The customer ID to be associated with the order.
        request_3yc_status (str): Status of the 3-year commitment request.

    Returns:
        dict: The updated order with the customer ID set in the corresponding fulfillment parameter.
    """
    order = set_adobe_customer_id(order, customer_id)
    if request_3yc_status:
        order = set_adobe_3yc_commitment_request_status(order, request_3yc_status)
    update_order(client, order["id"], parameters=order["parameters"])
    update_agreement(
        client, order["agreement"]["id"], externalIds={"vendor": customer_id}
    )
    return order


def save_adobe_order_id_and_customer_data(client, order, order_id, customer):
    order = set_adobe_order_id(order, order_id)
    order = set_adobe_customer_id(order, customer["customerId"])

    address = customer["companyProfile"]["address"]
    contact = customer["companyProfile"]["contacts"][0]
    commitment = get_3yc_commitment(customer)

    customer_data = {
        PARAM_COMPANY_NAME: customer["companyProfile"]["companyName"],
        PARAM_ADDRESS: {
            "country": address["country"],
            "state": address["region"],
            "city": address["city"],
            "addressLine1": address["addressLine1"],
            "addressLine2": address["addressLine2"],
            "postCode": address["postalCode"],
        },
        PARAM_CONTACT: {
            "firstName": contact["firstName"],
            "lastName": contact["lastName"],
            "email": contact["email"],
            "phone": split_phone_number(contact.get("phoneNumber"), address["country"]),
        },
    }
    if commitment:
        customer_data[PARAM_3YC] = ["Yes"]
        for mq in commitment["minimumQuantities"]:
            if mq["offerType"] == "LICENSE":
                customer_data[PARAM_3YC_LICENSES] = str(mq["quantity"])
            if mq["offerType"] == "CONSUMABLES":
                customer_data[PARAM_3YC_CONSUMABLES] = str(mq["quantity"])

        order = set_adobe_3yc_enroll_status(order, commitment["status"])
        order = set_adobe_3yc_start_date(order, commitment["startDate"])
        order = set_adobe_3yc_end_date(order, commitment["endDate"])

    order = set_customer_data(order, customer_data)

    update_order(
        client,
        order["id"],
        parameters=order["parameters"],
        externalIds=order["externalIds"],
    )
    update_agreement(
        client, order["agreement"]["id"], externalIds={"vendor": customer["customerId"]}
    )
    return order


def save_adobe_order_id(client, order, order_id):
    """
    Sets the Adobe order ID on the provided order and updates it using the MPT client.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order that needs to be updated.
        customer_id (str): The customer ID to be associated with the order.

    Returns:
        dict: The updated order with the order ID set in the corresponding fulfillment parameter.
    """
    order = set_adobe_order_id(order, order_id)
    update_order(client, order["id"], externalIds=order["externalIds"])
    return order


def switch_order_to_failed(client, order, status_notes):
    """
    Marks an MPT order as failed by resetting any retry attempts and updating its status.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be marked as failed.
        status_notes (str): Additional notes or context related to the failure.

    Returns:
        dict: The updated order with the appropriate status and notes.
    """
    order = reset_retries(client, order)
    agreement = order["agreement"]
    order = fail_order(client, order["id"], status_notes)
    order["agreement"] = agreement
    send_email_notification(client, order)
    return order


def switch_order_to_query(client, order):
    """
    Switches the status of an MPT order to 'query' and resetting any retry attempts and
    initiating a query order process.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be switched to 'query' status.

    Returns:
        None
    """
    template = get_product_template_or_default(
        client, order["agreement"]["product"]["id"], MPT_ORDER_STATUS_QUERYING
    )
    order = reset_retry_count(order)
    kwargs = {
        "parameters": order["parameters"],
        "template": template,
    }
    if order.get("error"):
        kwargs["error"] = order["error"]

    agreement = order["agreement"]
    order = query_order(
        client,
        order["id"],
        **kwargs,
    )
    order["agreement"] = agreement
    send_email_notification(client, order)


def handle_retries(mpt_client, order, adobe_order_id, adobe_order_type="NEW"):
    """
    Handle the reprocessing of an order.
    If the maximum processing attempts has not been reached, it updates the order
    incrementing the retry count fulfillment parameter otherwise it fails the
    order.

    Args:
        mpt_client (MPTClient): an instance of the Marketplace platform client.
        order (dct): The MPT order.
        adobe_order_id (str): identifier of the Adobe order.
        adobe_order_type (str, optional): type of Adobe order (NEW or RETURN).
        Defaults to "NEW".

    Returns:
        None
    """
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


def reset_retries(mpt_client, order):
    """
    Updates the order to set the retry count parameter to zero.

    Args:
        mpt_client (MPTClient): an instance of the Marketplace platform client.
        order (dct): The MPT order.

    Returns:
        order (dct): The updated MPT order.
    """
    order = reset_retry_count(order)
    update_order(mpt_client, order["id"], parameters=order["parameters"])
    return order


def check_adobe_order_fulfilled(
    mpt_client, adobe_client, order, customer_id, adobe_order_id
):
    """
    Check if the order that has been placed in Adobe has been fulfilled or not.
    If the order is still pending, it increments the retry count or fail the order
    if the maximum number of attempts has been reached.
    If the order processing has failed, it fails the MPT order reporting the error
    returned by Adobe.
    If the order has been fulfilled this function return it.

    Args:
        mpt_client (MPTClient):  an instance of the Marketplace platform client.
        order (dct): The MPT order from which the Adobe order has been derived.
        customer_id (str): The id used in Adobe to identify the customer attached
        to this MPT order.
        adobe_order_id (str): The Adobe order identifier.

    Returns:
        dict: The Adobe order if it has been fulfilled, None otherwise.
    """
    authorization_id = order["authorization"]["id"]
    adobe_order = adobe_client.get_order(
        authorization_id,
        customer_id,
        adobe_order_id,
    )

    if adobe_order["status"] == STATUS_PENDING:
        handle_retries(mpt_client, order, adobe_order_id)
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


def handle_return_orders(mpt_client, adobe_client, customer_id, order, lines):
    """
    Handles return orders for a given MPT order by processing the necessary
    actions based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        adobe_client (AdobeClient): An instance of the Adobe client for communication with the
            Adobe API.
        customer_id (str): The ID used in Adobe to identify the customer attached to this MPT order.
        order (dict): The MPT order being processed.
        lines (list): The MPT order lines associated with the return.

    Returns:
        tuple or None: A tuple containing completed order IDs (if any) and the updated MPT order.
            If there are pending return orders, returns None.
    """
    completed_order_ids = []
    pending_order_ids = []
    authorization_id = order["authorization"]["id"]
    for line in lines:
        orders_4_item = adobe_client.search_new_and_returned_orders_by_sku_line_number(
            authorization_id,
            customer_id,
            line["item"]["externalIds"]["vendor"],
            line["id"],
        )
        for order_to_return, item_to_return, return_order in orders_4_item:
            if not return_order:
                logger.debug(f"Return order not found for {line['item']['id']}")
                return_order = adobe_client.create_return_order(
                    authorization_id,
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
                order = reset_retries(mpt_client, order)

    if pending_order_ids:
        handle_retries(
            mpt_client, order, ", ".join(pending_order_ids), adobe_order_type="RETURN"
        )
        return None, order

    return completed_order_ids, order


def switch_order_to_completed(mpt_client, order, template_name):
    """
    Reset the retry count to zero and switch the MPT order
    to completed using the completed template.

    Args:
        mpt_client (MPTClient):  an instance of the Marketplace platform client.
        order (dict): The MPT order that have to be switched to completed.
    """
    order = reset_retries(mpt_client, order)
    template = get_product_template_or_default(
        mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        template_name,
    )
    agreement = order["agreement"]
    order = complete_order(
        mpt_client,
        order["id"],
        template,
    )
    order["agreement"] = agreement
    send_email_notification(mpt_client, order)
    logger.info(f'Order {order["id"]} has been completed successfully')


def add_subscription(mpt_client, adobe_client, customer_id, order, line):
    """
    Adds a subscription to the correspoding MPT order based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        adobe_client (AdobeClient): An instance of the Adobe client for communication with the
            Adobe API.
        customer_id (str): The ID used in Adobe to identify the customer attached to this MPT order.
        order (dict): The MPT order to which the subscription will be added.
        line (dict): The order line.

    Returns:
        None
    """
    authorization_id = order["authorization"]["id"]
    adobe_subscription = adobe_client.get_subscription(
        authorization_id,
        customer_id,
        line["subscriptionId"],
    )

    if adobe_subscription["status"] != STATUS_PROCESSED:
        logger.warning(
            f"Subscription {adobe_subscription['subscriptionId']} "
            f"for customer {customer_id} is in status "
            f"{adobe_subscription['status']}, skip it"
        )
        return

    order_line = get_order_line_by_sku(order, line["offerId"])

    subscription = get_subscription_by_external_id(
        mpt_client, order["id"], line["subscriptionId"]
    )
    if not subscription:
        subscription = {
            "name": f"Subscription for {order_line['item']['name']}",
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": PARAM_ADOBE_SKU,
                        "value": line["offerId"],
                    }
                ]
            },
            "externalIds": {
                "vendor": line["subscriptionId"],
            },
            "lines": [
                {
                    "id": order_line["id"],
                },
            ],
            "startDate": adobe_subscription["creationDate"],
            "commitmentDate": adobe_subscription["renewalDate"],
        }
        subscription = create_subscription(mpt_client, order["id"], subscription)
        logger.info(
            f'Subscription {line["subscriptionId"]} ({subscription["id"]}) '
            f'created for order {order["id"]}'
        )
    return subscription


def set_subscription_actual_sku(
    mpt_client,
    order,
    subscription,
    sku,
):
    """
    Set the subscription fullfilment parameter to store the actual SKU
    (Adobe SKU with discount level)

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to which the subscription will be added.
        subscription (dict): The MPT subscription that need to be updated.
        sku (str, optional): The Adobe full SKU. If None a lookup to the corresponding
        Adobe subscription will be done to retreive such SKU.

    Returns:
        dict: The updated MPT subscription.
    """
    return update_subscription(
        mpt_client,
        order["id"],
        subscription["id"],
        parameters={
            "fulfillment": [
                {
                    "externalId": PARAM_ADOBE_SKU,
                    "value": sku,
                },
            ],
        },
    )


def update_order_actual_price(
    mpt_client,
    order,
    lines_to_update,
    adobe_items,
):
    actual_skus = [item["offerId"] for item in adobe_items]
    pricelist_id = order["agreement"]["listing"]["priceList"]["id"]
    product_id = order["agreement"]["product"]["id"]
    product_actual_items = get_product_items_by_skus(
        mpt_client, product_id, actual_skus
    )
    price_items = get_pricelist_items_by_product_items(
        mpt_client,
        pricelist_id,
        [item["id"] for item in product_actual_items],
    )

    lines = []
    for line in lines_to_update:
        new_price_item = get_price_item_by_line_sku(
            price_items, line["item"]["externalIds"]["vendor"]
        )
        lines.append(
            {
                "id": line["id"],
                "price": {
                    "unitPP": new_price_item["unitPP"],
                },
            }
        )

    # to have total list of lines, leave other not updated
    updated_lines_ids = {line["id"] for line in lines}
    for line in order["lines"]:
        if line["id"] in updated_lines_ids:
            continue

        lines.append(
            {
                "id": line["id"],
                "price": {
                    "unitPP": line["price"]["unitPP"],
                },
            }
        )

    lines = sorted(lines, key=itemgetter("id"))

    return update_order(mpt_client, order["id"], lines=lines)


def check_processing_template(mpt_client, order, template_name):
    template = get_product_template_or_default(
        mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        template_name,
    )
    if template != order.get("template"):
        set_processing_template(mpt_client, order["id"], template)


def send_processing_notification(mpt_client, order):
    if get_retry_count(order) == 0:
        send_email_notification(mpt_client, order)


def save_next_sync_date(client, order, coterm_date):
    next_sync = (
        (datetime.fromisoformat(coterm_date) + timedelta(days=1)).date().isoformat()
    )
    order = set_next_sync(order, next_sync)
    update_order(client, order["id"], parameters=order["parameters"])
    return order


def send_email_notification(mpt_client, order):
    email_notification_enabled = bool(
        settings.EXTENSION_CONFIG.get("EMAIL_NOTIFICATIONS_ENABLED", False)
    )

    if email_notification_enabled:
        recipient = get_notifications_recipient(order)
        if not recipient:
            logger.warning(
                f"Cannot send email notifications for order {order['id']}: no recipient found"
            )
            return

        context = {
            "order": order,
            "activation_template": md2html(get_rendered_template(mpt_client, order["id"])),
            "api_base_url": settings.MPT_API_BASE_URL,
            "portal_base_url": settings.MPT_PORTAL_BASE_URL,
        }
        subject = (
            f"Order status update {order["id"]} "
            f"for {order['agreement']['buyer']['name']}"
        )
        if order["status"] == "Querying":
            subject = (
                f"This order need your attention {order["id"]} "
                f"for {order['agreement']['buyer']['name']}"
            )
        send_email(
            recipient,
            subject,
            "email",
            context,
        )


def get_one_time_skus(mpt_client, order):
    one_time_items = get_product_onetime_items_by_ids(
        mpt_client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]]
    )
    return [item["externalIds"]["vendor"] for item in one_time_items]
