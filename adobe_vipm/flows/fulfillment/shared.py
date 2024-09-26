"""
This module contains shared functions used by the different fulfillment flows.
"""

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from operator import itemgetter

from django.conf import settings

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    STATUS_3YC_ACTIVE,
    STATUS_3YC_COMMITTED,
    STATUS_PENDING,
    STATUS_PROCESSED,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.utils import (
    get_3yc_commitment,
    sanitize_company_name,
    sanitize_first_last_name,
)
from adobe_vipm.flows.airtable import get_prices_for_3yc_skus, get_prices_for_skus
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
    TEMPLATE_NAME_DELAYED,
)
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
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
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_coterm_date,
    get_next_sync,
    get_notifications_recipient,
    get_order_line_by_sku,
    get_price_item_by_line_sku,
    get_retry_count,
    get_subscription_by_line_and_item_id,
    increment_retry_count,
    is_renewal_window_open,
    map_returnable_to_return_orders,
    md2html,
    reset_retry_count,
    set_adobe_3yc_end_date,
    set_adobe_3yc_enroll_status,
    set_adobe_3yc_start_date,
    set_adobe_customer_id,
    set_adobe_order_id,
    set_coterm_date,
    set_customer_data,
    set_next_sync,
    set_template,
    split_phone_number,
)
from adobe_vipm.notifications import send_email
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def save_adobe_order_id_and_customer_data(client, order, order_id, customer):
    """
    Save the customer data retrieved from Adobe into the corresponding ordering
    parameters. Save the Adobe order ID as the order's vendor external ID.

    Args:
        client (MPTClient): The client used to consume the MPT API.
        order (dict): The order into which the data must be saved.
        order_id (str): The Adobe order ID to store.
        customer (_type_): The Adobe customer object from which the customer
        data must be taken.

    Returns:
        dict: The updated order.
    """
    # This function is used by VIP -> VIPM transfer only so it should be moved to
    # transfer module.
    order = set_adobe_order_id(order, order_id)
    order = set_adobe_customer_id(order, customer["customerId"])

    address = customer["companyProfile"]["address"]
    contact = customer["companyProfile"]["contacts"][0]
    commitment = get_3yc_commitment(customer)

    customer_data = {
        PARAM_COMPANY_NAME: sanitize_company_name(
            customer["companyProfile"]["companyName"]
        ),
        PARAM_ADDRESS: {
            "country": address["country"],
            "state": address["region"],
            "city": address["city"],
            "addressLine1": address["addressLine1"],
            "addressLine2": address["addressLine2"],
            "postCode": address["postalCode"],
        },
        PARAM_CONTACT: {
            "firstName": sanitize_first_last_name(contact["firstName"]),
            "lastName": sanitize_first_last_name(contact["lastName"]),
            "email": contact["email"],
            "phone": split_phone_number(contact.get("phoneNumber"), address["country"]),
        },
    }
    if commitment:
        customer_data[PARAM_3YC] = None
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
    order = reset_retry_count(order)
    agreement = order["agreement"]
    order = fail_order(
        client, order["id"], status_notes, parameters=order["parameters"]
    )
    order["agreement"] = agreement
    send_email_notification(client, order)
    return order


def switch_order_to_query(client, order, template_name=None):
    """
    Switches the status of an MPT order to 'query' and resetting any retry attempts and
    initiating a query order process.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be switched to 'query' status.
        template_name: The name of the template to use, if None -> use default

    Returns:
        None
    """
    template = get_product_template_or_default(
        client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_QUERYING,
        name=template_name,
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


def handle_retries(client, order, adobe_order_id, adobe_order_type="NEW"):
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
    fail_order(client, order["id"], reason)
    logger.warning(f"Order {order['id']} has been failed: {reason}.")


def switch_order_to_completed(client, order, template_name):
    """
    Reset the retry count to zero and switch the MPT order
    to completed using the completed template.

    Args:
        client (MPTClient):  an instance of the Marketplace platform client.
        order (dict): The MPT order that have to be switched to completed.
    """
    order = reset_retry_count(order)
    template = get_product_template_or_default(
        client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        template_name,
    )
    agreement = order["agreement"]
    order = complete_order(
        client,
        order["id"],
        template,
        parameters=order["parameters"],
    )
    order["agreement"] = agreement
    send_email_notification(client, order)
    logger.info(f'Order {order["id"]} has been completed successfully')


def add_subscription(client, adobe_client, customer_id, order, line):
    """
    Adds a subscription to the correspoding MPT order based on the provided parameters.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
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
        client, order["id"], line["subscriptionId"]
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
            "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
        }
        subscription = create_subscription(client, order["id"], subscription)
        logger.info(
            f'Subscription {line["subscriptionId"]} ({subscription["id"]}) '
            f'created for order {order["id"]}'
        )
    return subscription


def set_subscription_actual_sku(
    client,
    order,
    subscription,
    sku,
):
    """
    Set the subscription fullfilment parameter to store the actual SKU
    (Adobe SKU with discount level)

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to which the subscription will be added.
        subscription (dict): The MPT subscription that need to be updated.
        sku (str, optional): The Adobe full SKU. If None a lookup to the corresponding
        Adobe subscription will be done to retreive such SKU.

    Returns:
        dict: The updated MPT subscription.
    """
    return update_subscription(
        client,
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


def check_processing_template(client, order, template_name):
    """
    Check if the order as the right processing template according to
    the type of the order. Set the right one if it's not already set.

    Args:
        client (MPTClient): The client for consuming the MPT API
        order (dict): The order to check.
        template_name (str): Name of the template that must be used.
    """
    template = get_product_template_or_default(
        client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        template_name,
    )
    if template != order.get("template"):
        set_processing_template(client, order["id"], template)


def start_processing_attempt(client, order):
    """
    Increments the retry count parameter to register the new attempt,
    send the processing email notification to the customer.

    Args:
        client (MPTClient): the MPT client used to update the order.
        order (dict): The order currently processing.

    Returns:
        dict: The order with the retry count parameter updated.
    """
    current_attempt = get_retry_count(order)
    order = increment_retry_count(order)
    update_order(client, order["id"], parameters=order["parameters"])
    if current_attempt == 0:
        send_email_notification(client, order)
    return order


def save_next_sync_and_coterm_dates(client, order, coterm_date):
    """
    Save the customer coterm date as a fulfillment parameter.
    It also calculates the next sync fulfillment parameter as
    the coterm date plus 1 day. The next sync date is used by
    the agreement synchronization process to know when the
    agreement has to be synchronized.

    Args:
        client (MPTClient): The client used to consume the MPT API.
        order (dict): The order that must be updated.
        coterm_date (str): The customer coterm date.

    Returns:
        dict: The updated order.
    """
    coterm_date = datetime.fromisoformat(coterm_date).date()
    order = set_coterm_date(order, coterm_date.isoformat())
    next_sync = coterm_date + timedelta(days=1)
    order = set_next_sync(order, next_sync.isoformat())
    update_order(client, order["id"], parameters=order["parameters"])
    return order


def send_email_notification(client, order):
    """
    Send a notification email to the customer according to the
    current order status.
    It embeds the current order template into the email body.

    Args:
        client (MPTClient): The client used to consume the
        MPT API.
        order (dict): The order for which the notification should be sent.
    """
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
            "activation_template": md2html(get_rendered_template(client, order["id"])),
            "api_base_url": settings.MPT_API_BASE_URL,
            "portal_base_url": settings.MPT_PORTAL_BASE_URL,
        }
        subject = (
            f"Order status update {order['id']} "
            f"for {order['agreement']['buyer']['name']}"
        )
        if order["status"] == "Querying":
            subject = (
                f"This order need your attention {order['id']} "
                f"for {order['agreement']['buyer']['name']}"
            )
        send_email(
            recipient,
            subject,
            "email",
            context,
        )


def get_one_time_skus(client, order):
    """
    Get tge SKUs from the order lines that correspond
    to One-Time items.

    Args:
        client (MPTClient): The client to consume the MPT API.
        order (dict): The order from which the One-Time items SKUs
        must be extracted.

    Returns:
        list: List of One-Time SKUs.
    """
    one_time_items = get_product_onetime_items_by_ids(
        client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    return [item["externalIds"]["vendor"] for item in one_time_items]


def set_customer_coterm_date_if_null(client, adobe_client, order):
    """
    If the customer coterm date fulfillment parameter is not set
    for the provided order, it retrieves the customer object from Adobe and
    set the coterm date fulfillment parameter for such order.

    Args:
        client (MPTClient): The client used to consume the MPT API.
        adobe_client (AdobeClient): The client used to consume the Adobe VIPM API.
        order (dict): The order that must be updated with the customer coterm date
        fulfillment parameter.

    Returns:
        dict: The updated order.
    """
    coterm_date = get_coterm_date(order)
    if coterm_date:
        return order
    customer_id = get_adobe_customer_id(order)
    authorization_id = order["authorization"]["id"]
    customer = adobe_client.get_customer(authorization_id, customer_id)
    coterm_date = customer["cotermDate"]
    order = set_coterm_date(order, coterm_date)
    update_order(client, order["id"], parameters=order["parameters"])
    return order


class IncrementAttemptsCounter(Step):
    """
    Increments the `retryCount` fulfillment parameter and update the order to reflect the change.
    """

    def __call__(self, client, context, next_step):
        context.order = increment_retry_count(context.order)
        next_attempt_count = get_retry_count(context.order)
        max_attemps = int(settings.EXTENSION_CONFIG.get("MAX_RETRY_ATTEMPS", "10"))
        if next_attempt_count > max_attemps:
            logger.info(f"{context}: maximum ({max_attemps}) of attemps reached.",
            )
            reason = f"Max processing attemps reached ({max_attemps})."
            switch_order_to_failed(client, context.order, reason)
            return
        update_order(
            client, context.order_id, parameters=context.order["parameters"]
        )
        logger.info(
            f"{context}: retry count incremented successfully "
            f"{context.current_attempt} -> {next_attempt_count}."
        )
        next_step(client, context)


class SetOrUpdateCotermNextSyncDates(Step):
    """
    Set or update the fulfillment parameters `cotermDate` and
    `nextSync` according to the Adobe customer coterm date.
    """

    def __call__(self, client, context, next_step):
        coterm_date = datetime.fromisoformat(
            context.adobe_customer["cotermDate"]
        ).date()
        next_sync = coterm_date + timedelta(days=1)

        if coterm_date.isoformat() != get_coterm_date(
            context.order
        ) or next_sync.isoformat() != get_next_sync(context.order):
            context.order = set_coterm_date(context.order, coterm_date.isoformat())
            context.order = set_next_sync(context.order, next_sync.isoformat())
            update_order(
                client, context.order_id, parameters=context.order["parameters"]
            )
            logger.info(
                f"{context}: coterm ({coterm_date.isoformat()}) "
                f"and next sync ({next_sync.isoformat()}) updated successfully")
        next_step(client, context)


class StartOrderProcessing(Step):
    """
    Set the template for the processing status or the
    delayed one if the processing is delated due to the
    renewal window open.

    """

    def __init__(self, template_name):
        self.template_name = template_name

    def __call__(self, client, context, next_step):
        template_name = (
            self.template_name
            if not is_renewal_window_open(context.order)
            else TEMPLATE_NAME_DELAYED
        )
        template = get_product_template_or_default(
            client,
            context.order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            template_name,
        )
        current_template_id = context.order.get("template", {}).get("id")
        if template["id"] != current_template_id:
            context.order = set_template(context.order, template)
            update_order(client, context.order_id, template=context.order["template"])
            logger.info(
                f"{context}: processing template set to {self.template_name} "
                f"({template['id']})"
            )
        logger.info(f"{context}: processing template is ok, continue")
        if context.current_attempt == 0:
            send_email_notification(client, context.order)
        next_step(client, context)


class ValidateRenewalWindow(Step):
    """
    Check if the renewal window is open. In that case stop the order processing.
    """

    def __call__(self, client, context, next_step):
        if is_renewal_window_open(context.order):
            coterm_date = get_coterm_date(context.order)
            logger.warning(
                f"{context}: Renewal window is open, coterm date is '{coterm_date}'"
            )
            return
        logger.info(f"{context}: not in renewal window, continue")
        next_step(client, context)


class GetReturnOrders(Step):
    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        context.adobe_return_orders = adobe_client.get_return_orders_by_external_reference(
            context.authorization_id,
            context.adobe_customer_id,
            context.order_id,
        )
        return_orders_count = sum(len(x) for x in context.adobe_return_orders.values())
        logger.info(f"{context}: found {return_orders_count} return order")
        next_step(client, context)


class SubmitReturnOrders(Step):
    """
    Creates the return orders for each returnable order
    to match the downsize quantities.
    Wait for the return orders to be processed before
    moving to the next step.
    """

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        all_return_orders = []
        for sku, returnable_orders in context.adobe_returnable_orders.items():
            return_orders = context.adobe_return_orders.get(sku, [])
            for returnable_order, return_order in map_returnable_to_return_orders(
                returnable_orders or [], return_orders
            ):
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
                    )
                )
        pending_orders = [
            return_order["orderId"]
            for return_order in all_return_orders
            if return_order["status"] != STATUS_PROCESSED
        ]

        if pending_orders:
            logger.info(
                f"{context}: There are pending return orders {', '.join(pending_orders)}"
            )
            return

        next_step(client, context)


class GetPreviewOrder(Step):
    """
    Retrieve a preview order for the upsize/new lines. If there are incompatible SKUs
    within the PREVIEW order an error will be thrown by the Adobe API the order will
    be failed and the processing pipeline will stop.
    In case a new order as already been submitted by a previous attempt, this step will be
    skipped and the order processing pipeline will continue.
    """

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        if context.upsize_lines and not context.adobe_new_order_id:
            try:
                context.adobe_preview_order = adobe_client.create_preview_order(
                    context.authorization_id,
                    context.adobe_customer_id,
                    context.order_id,
                    context.upsize_lines,
                )
            except AdobeError as e:
                switch_order_to_failed(client, context.order, str(e))
                return

        next_step(client, context)


class SubmitNewOrder(Step):
    """
    Submit a new order if there are new/upsizing items to purchase.
    Wait for the order to be processed by Adobe before moving to
    the next step.
    """

    def __call__(self, client, context, next_step):
        if not context.upsize_lines:
            next_step(client, context)
            return
        adobe_client = get_adobe_client()
        adobe_order = None
        if not context.adobe_new_order_id:
            adobe_order = adobe_client.create_new_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.adobe_preview_order,
            )
            logger.info(f'{context}: new adobe order created: {adobe_order["orderId"]}')
            context.order = set_adobe_order_id(context.order, adobe_order["orderId"])
            update_order(client, context.order_id, externalIds=context.order["externalIds"])
        else:
            adobe_order = adobe_client.get_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.adobe_new_order_id,
            )
        context.adobe_new_order = adobe_order
        context.adobe_new_order_id = adobe_order["orderId"]
        if adobe_order["status"] == STATUS_PENDING:
            logger.info(f"{context}: adobe order {context.adobe_new_order_id} is still pending.")
            return
        elif adobe_order["status"] in UNRECOVERABLE_ORDER_STATUSES:
            reason = ORDER_STATUS_DESCRIPTION[adobe_order["status"]]
            switch_order_to_failed(client, context.order_id, reason)
            logger.warning(
                f"{context}: The adobe order has been failed {reason}."
            )
            return
        elif adobe_order["status"] != STATUS_PROCESSED:
            reason = (
                f"Unexpected status ({adobe_order['status']}) received from Adobe."
            )
            switch_order_to_failed(client, context.order_id, reason)
            logger.warning(
                f"{context}: the order has been failed due to {reason}."
            )
            return
        next_step(client, context)


class CreateOrUpdateSubscriptions(Step):
    def __call__(self, client, context, next_step):
        if context.adobe_new_order:
            adobe_client = get_adobe_client()
            one_time_skus = get_one_time_skus(client, context.order)
            for line in filter(
                lambda x: get_partial_sku(x["offerId"]) not in one_time_skus,
                context.adobe_new_order["lineItems"]
            ):
                order_line = get_order_line_by_sku(context.order, line["offerId"])

                order_subscription = get_subscription_by_line_and_item_id(
                    context.order["subscriptions"],
                    order_line["item"]["id"],
                    order_line["id"],
                )
                if not order_subscription:
                    adobe_subscription = adobe_client.get_subscription(
                        context.authorization_id,
                        context.adobe_customer_id,
                        line["subscriptionId"],
                    )

                    if adobe_subscription["status"] != STATUS_PROCESSED:
                        logger.warning(
                            f"{context}: subscription {adobe_subscription['subscriptionId']} "
                            f"for customer {context.adobe_customer_id} is in status "
                            f"{adobe_subscription['status']}, skip it"
                        )
                        continue

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
                    subscription = create_subscription(client, context.order_id, subscription)
                    logger.info(
                        f'{context}: subscription {line["subscriptionId"]} '
                        f'({subscription["id"]}) created'
                    )
                else:
                    adobe_sku = line["offerId"]
                    set_subscription_actual_sku(
                        client,
                        context.order,
                        order_subscription,
                        adobe_sku,
                    )
                    logger.info(
                        f'{context}: subscription {line["subscriptionId"]} '
                        f'({order_subscription["id"]}) updated'
                    )
        next_step(client, context)


class UpdatePrices(Step):
    def __call__(self, client, context, next_step):
        if context.adobe_new_order:  # pragma: no branch
            actual_skus = [item["offerId"] for item in context.adobe_new_order["lineItems"]]
            commitment = get_3yc_commitment(context.adobe_customer)
            if (
                commitment
                and commitment["status"] in (STATUS_3YC_COMMITTED, STATUS_3YC_ACTIVE)
                and date.fromisoformat(commitment["endDate"]) >= date.today()
            ):
                prices = get_prices_for_3yc_skus(
                    context.product_id,
                    context.currency,
                    date.fromisoformat(commitment["startDate"]),
                    actual_skus,
                )
            else:
                prices = get_prices_for_skus(context.product_id, context.currency, actual_skus)

            lines = []
            for line in [get_order_line_by_sku(context.order, sku) for sku in actual_skus]:
                new_price_item = get_price_item_by_line_sku(
                    prices, line["item"]["externalIds"]["vendor"]
                )
                lines.append(
                    {
                        "id": line["id"],
                        "price": {
                            "unitPP": new_price_item[1],
                        },
                    }
                )

            # to have total list of lines, leave other not updated
            updated_lines_ids = {line["id"] for line in lines}
            for line in context.order["lines"]:
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

            update_order(client, context.order_id, lines=lines)
            logger.info(f"{context}: order lines prices updated successfully")
        next_step(client, context)


class CompleteOrder(Step):
    def __init__(self, template_name):
        self.template_name = template_name

    def __call__(self, client, context, next_step):
        context.order = reset_retry_count(context.order)
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
        send_email_notification(client, context.order)
        logger.info(f'{context}: order has been completed successfully')
        next_step(client, context)


class SyncAgreement(Step):
    def __call__(self, client, context, next_step):
        sync_agreements_by_agreement_ids(client, [context.agreement_id])
        logger.info(f'{context}: agreement synchoronized')
        next_step(client, context)


class ValidateDuplicateLines(Step):
    def __call__(self, client, context, next_step):
        items = [line["item"]["id"] for line in context.order["lines"]]
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            switch_order_to_failed(
                client,
                context.order,
                (
                    "The order cannot contain multiple lines "
                    f"for the same item: {','.join(duplicates)}."
                ),
            )
            return

        items = []
        for subscription in context.order["agreement"]["subscriptions"]:
            for line in subscription["lines"]:
                items.append(line["item"]["id"])

        items.extend(
            [line["item"]["id"] for line in context.order["lines"] if line["oldQuantity"] == 0]
        )
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            switch_order_to_failed(
                client,
                context.order,
                f"The order cannot contain new lines for an existing item: {','.join(duplicates)}.",
            )
            return

        next_step(client, context)
