"""This module contains shared functions used by the different fulfillment flows."""

import datetime as dt
import logging

from django.conf import settings
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_order_subscription_by_external_id,
    get_product_template_or_default,
    get_rendered_template,
    query_order,
    set_processing_template,
    update_agreement,
    update_order,
    update_subscription,
)

from adobe_vipm.adobe.utils import (
    sanitize_company_name,
    sanitize_first_last_name,
)
from adobe_vipm.flows.constants import (
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    MPT_ORDER_STATUS_QUERYING,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE,
    Param,
)
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    get_address,
    get_adobe_customer_id,
    get_coterm_date,
    get_due_date,
    get_order_line_by_sku,
    md2html,
    reset_due_date,
    set_adobe_3yc_end_date,
    set_adobe_3yc_enroll_status,
    set_adobe_3yc_start_date,
    set_adobe_customer_id,
    set_adobe_order_id,
    set_coterm_date,
    set_customer_data,
    set_due_date,
    split_phone_number,
)
from adobe_vipm.flows.utils.parameter import set_ordering_parameter_error
from adobe_vipm.notifications import mpt_notify
from adobe_vipm.utils import get_3yc_commitment

logger = logging.getLogger(__name__)


def save_adobe_order_id_and_customer_data(client, order, order_id, customer):
    """
    Save the customer data retrieved from Adobe into the corresponding ordering parameters.

    Save the Adobe order ID as the order's vendor external ID.

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

    address = customer["companyProfile"].get("address", {})
    contact = customer["companyProfile"]["contacts"][0]
    commitment = get_3yc_commitment(customer)

    customer_data = {
        Param.COMPANY_NAME.value: sanitize_company_name(customer["companyProfile"]["companyName"]),
        Param.CONTACT.value: {
            "firstName": sanitize_first_last_name(contact["firstName"]),
            "lastName": sanitize_first_last_name(contact["lastName"]),
            "email": contact["email"],
            "phone": split_phone_number(contact.get("phoneNumber"), address.get("country", "")),
        },
    }

    if address:
        customer_data[Param.ADDRESS.value] = get_address(address)

    if commitment:
        customer_data[Param.THREE_YC.value] = None
        for mq in commitment["minimumQuantities"]:
            if mq["offerType"] == "LICENSE":
                customer_data[Param.THREE_YC_LICENSES.value] = str(mq["quantity"])
            if mq["offerType"] == "CONSUMABLES":
                customer_data[Param.THREE_YC_CONSUMABLES.value] = str(mq["quantity"])

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
        order_id (str): MPT Order Id.

    Returns:
        dict: The updated order with the order ID set in the corresponding fulfillment parameter.
    """
    order = set_adobe_order_id(order, order_id)
    update_order(client, order["id"], externalIds=order["externalIds"])
    return order


def switch_order_to_failed(client, order, error):
    """
    Marks an MPT order as failed by resetting due date and updating its status.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be marked as failed.
        error (dict): Additional notes or context related to the failure.

    Returns:
        dict: The updated order with the appropriate status and notes.
    """
    order = reset_due_date(order)
    agreement = order["agreement"]
    order = fail_order(
        client,
        order["id"],
        error,
        parameters=order["parameters"],
    )
    order["agreement"] = agreement
    send_mpt_notification(client, order)
    sync_agreements_by_agreement_ids(client, [agreement["id"]], dry_run=False, sync_prices=False)
    return order


def switch_order_to_query(client, order, template_name=None):
    """
    Switches the status of an MPT order to 'query' and resetting due date.

    Initiating a query order process.

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
    order = reset_due_date(order)
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
    send_mpt_notification(client, order)


def handle_retries(client, order, adobe_order_id, adobe_order_type="NEW"):
    """
    Handle the reprocessing of an order. If the due date is reached - fail the order.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order (dct): The MPT order.
        adobe_order_id (str): identifier of the Adobe order.
        adobe_order_type (str, optional): type of Adobe order (NEW or RETURN).
        Defaults to "NEW".

    Returns:
        None
    """
    due_date = get_due_date(order)
    due_date_str = due_date.strftime("%Y-%m-%d")
    if dt.datetime.now(tz=dt.UTC).date() <= due_date:
        logger.info(
            "Order %s (%s: %s) is still processing on Adobe side, wait.",
            order["id"],
            adobe_order_id,
            adobe_order_type,
        )
        return
    logger.info(
        "The order %s (%s) has reached the due date (%s).",
        order["id"],
        adobe_order_id,
        due_date_str,
    )
    reason = f"Due date is reached ({due_date_str})."
    fail_order(client, order["id"], reason, ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=reason))
    logger.warning("Order %s has been failed: %s.", order["id"], reason)


def handle_error(
    mpt_client,
    context,
    error_data,
    *,
    is_validation=False,
    parameter=None,
):
    """Handle errors based on validation mode."""
    if is_validation:
        context.order = set_ordering_parameter_error(
            context.order,
            parameter,
            error_data,
        )
        context.validation_succeeded = False
    else:
        switch_order_to_failed(mpt_client, context.order, error_data)


def switch_order_to_completed(client, order, template_name):
    """
    Reset the retry count to zero and switch the MPT order to completed.

    Uses the completed template.

    Args:
        client (MPTClient):  an instance of the Marketplace platform client.
        order (dict): The MPT order that have to be switched to completed.
        template_name (str): MPT template name.
    """
    order = reset_due_date(order)
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
    send_mpt_notification(client, order)
    logger.info("Order %s has been completed successfully", order["id"])


def add_subscription(client, adobe_subscription, order, line):
    """
    Adds a subscription to the correspoding MPT order based on the provided parameters.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        adobe_subscription(dict): A subscription object retrieved from the Adobe API.
        order (dict): The MPT order to which the subscription will be added.
        line (dict): The order line.

    Returns:
        None
    """
    order_line = get_order_line_by_sku(order, line["offerId"])

    subscription = get_order_subscription_by_external_id(
        client, order["id"], line["subscriptionId"]
    )
    if not subscription:
        subscription = {
            "name": f"Subscription for {order_line['item']['name']}",
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": Param.ADOBE_SKU.value,
                        "value": line["offerId"],
                    },
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": Param.RENEWAL_DATE.value,
                        "value": str(adobe_subscription["renewalDate"]),
                    },
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
            "Subscription %s (%s) created for order %s",
            line["subscriptionId"],
            subscription["id"],
            order["id"],
        )
    return subscription


def set_subscription_actual_sku(
    client,
    order,
    subscription,
    sku,
):
    """
    Set the subscription fullfilment parameter to store the actual SKU.

    Adobe SKU with discount level.

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
                    "externalId": Param.ADOBE_SKU.value,
                    "value": sku,
                },
            ],
        },
    )


def check_processing_template(client, order, template_name):
    """
    Check if the order as the right processing template according to the type of the order.

    Set the right one if it's not already set.

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
    Sets due date and send email notification.

    Args:
        client (MPTClient): the MPT client used to update the order.
        order (dict): The order currently processing.

    Returns:
        dict: The order with the due date parameter updated.
    """
    current_due_date = get_due_date(order)
    if current_due_date:
        return order

    order = set_due_date(order)
    update_order(client, order["id"], parameters=order["parameters"])
    send_mpt_notification(client, order)

    return order


def save_coterm_dates(client, order, coterm_date):
    """
    Save the customer coterm date as a fulfillment parameter.

    Args:
        client (MPTClient): The client used to consume the MPT API.
        order (dict): The order that must be updated.
        coterm_date (str): The customer coterm date.

    Returns:
        dict: The updated order.
    """
    coterm_date = dt.datetime.fromisoformat(coterm_date).date()
    order = set_coterm_date(order, coterm_date.isoformat())
    update_order(client, order["id"], parameters=order["parameters"])
    return order


def send_mpt_notification(mpt_client: MPTClient, order: dict) -> None:
    """
    Send an MPT notification to the customer according to the current order status.

    It embeds the current order template into the body.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        order (dict): The order for which the notification should be sent.
    """
    context = {
        "order": order,
        "activation_template": md2html(get_rendered_template(mpt_client, order["id"])),
        "api_base_url": settings.MPT_API_BASE_URL,
        "portal_base_url": settings.MPT_PORTAL_BASE_URL,
    }
    subject = f"Order status update {order['id']} for {order['agreement']['buyer']['name']}"
    if order["status"] == "Querying":
        subject = (
            f"This order need your attention {order['id']} "
            f"for {order['agreement']['buyer']['name']}"
        )
    mpt_notify(
        mpt_client,
        order["agreement"]["licensee"]["account"]["id"],
        order["agreement"]["buyer"]["id"],
        subject,
        "notification",
        context,
    )


def set_customer_coterm_date_if_null(client, adobe_client, order):
    """
    Retrieves the customer object from adobe and set the coterm date for such order if needed.

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


def get_configuration_template_name(order):
    """
    Helper function to determine the template name based on auto renewal status.

    Args:
        order (dict): The order containing subscription information.

    Returns:
        str: The appropriate template name based on auto renewal status.
    """
    auto_renewal = order["subscriptions"][0]["autoRenew"]
    return (
        TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE
        if auto_renewal
        else TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE
    )
