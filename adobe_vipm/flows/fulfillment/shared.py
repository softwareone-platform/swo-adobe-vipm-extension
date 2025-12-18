"""This module contains shared functions used by the different fulfillment flows."""

import datetime as dt
import json
import logging
from collections import Counter

from django.conf import settings
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import (
    complete_order,
    create_order_asset,
    create_subscription,
    fail_order,
    get_asset_template_by_name,
    get_order_asset_by_external_id,
    get_order_subscription_by_external_id,
    get_product_template_or_default,
    get_rendered_template,
    get_template_by_name,
    query_order,
    set_processing_template,
    update_agreement,
    update_agreement_subscription,
    update_order,
    update_order_asset,
    update_subscription,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    UNRECOVERABLE_ORDER_STATUSES,
    AdobeStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError
from adobe_vipm.adobe.utils import (
    get_3yc_commitment_request,
    sanitize_company_name,
    sanitize_first_last_name,
)
from adobe_vipm.flows.constants import (
    ERR_COTERM_DATE_IN_LAST_24_HOURS,
    ERR_DUE_DATE_REACHED,
    ERR_DUPLICATED_ITEMS,
    ERR_EXISTING_ITEMS,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    MPT_ORDER_STATUS_QUERYING,
    TEMPLATE_ASSET_DEFAULT,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE,
    TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE,
    Param,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.sync.agreement import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    get_address,
    get_adobe_customer_id,
    get_coterm_date,
    get_deployment_id,
    get_due_date,
    get_one_time_skus,
    get_order_line_by_sku,
    get_subscription_by_line_and_item_id,
    is_coterm_date_within_order_creation_window,
    map_returnable_to_return_orders,
    md2html,
    reset_due_date,
    set_adobe_3yc_commitment_request_status,
    set_adobe_3yc_end_date,
    set_adobe_3yc_enroll_status,
    set_adobe_3yc_start_date,
    set_adobe_customer_id,
    set_adobe_order_id,
    set_coterm_date,
    set_customer_data,
    set_due_date,
    set_order_error,
    set_template,
    split_phone_number,
)
from adobe_vipm.flows.utils.customer import has_coterm_date, set_agency_type
from adobe_vipm.flows.utils.parameter import set_ordering_parameter_error
from adobe_vipm.flows.utils.template import get_template_data_by_adobe_subscription
from adobe_vipm.flows.utils.three_yc import set_adobe_3yc
from adobe_vipm.notifications import mpt_notify, send_exception
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

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

    order = set_agency_type(order, customer)

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


def switch_order_to_failed(mpt_client, order, error):
    """
    Marks an MPT order as failed by resetting due date and updating its status.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be marked as failed.
        error (dict): Additional notes or context related to the failure.

    Returns:
        dict: The updated order with the appropriate status and notes.
    """
    order = reset_due_date(order)
    agreement = order["agreement"]
    order = fail_order(
        mpt_client,
        order["id"],
        error,
        parameters=order["parameters"],
    )
    order["agreement"] = agreement
    send_mpt_notification(mpt_client, order)
    adobe_client = get_adobe_client()
    sync_agreements_by_agreement_ids(
        mpt_client, adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
    )
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


def add_asset(client, adobe_subscription, order, line):
    """
    Adds an asset to the corresponding MPT order based on the provided parameters.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        adobe_subscription (dict): A subscription object retrieved from the Adobe API.
        order (dict): The MPT order to which the subscription will be added.
        line (dict): The order line.

    """
    asset = get_order_asset_by_external_id(client, order["id"], line["subscriptionId"])
    if asset:
        logger.info(
            "Asset with external id %s already exists (%s)",
            adobe_subscription["subscriptionId"],
            asset["id"],
        )
        return asset

    order_line = get_order_line_by_sku(order, line["offerId"])
    product_id = order["agreement"]["product"]["id"]
    template = get_asset_template_by_name(client, product_id, TEMPLATE_ASSET_DEFAULT)
    asset = create_order_asset(
        client, order["id"], create_asset_payload(adobe_subscription, order_line, line, template)
    )
    logger.info(
        "Asset %s (%s) created for order %s",
        line["subscriptionId"],
        asset["id"],
        order["id"],
    )
    return asset


def create_asset_payload(adobe_subscription, order_line, item, template):
    """Create an asset payload.

    Args:
        adobe_subscription (dict): the adobe subscription
        order_line (dict): the order line.
        item (dict) : the item.
        template (dict | None): the template.

    Returns: A dict with the asset payload

    """
    template_data = {"id": template["id"], "name": template["name"]} if template else None
    return {
        "name": f"Asset for {order_line['item']['name']}",
        "parameters": {
            "fulfillment": [
                {
                    "externalId": Param.ADOBE_SKU.value,
                    "value": item["offerId"],
                },
                {
                    "externalId": Param.CURRENT_QUANTITY.value,
                    "value": str(adobe_subscription[Param.CURRENT_QUANTITY]),
                },
                {
                    "externalId": Param.USED_QUANTITY.value,
                    "value": str(adobe_subscription[Param.USED_QUANTITY]),
                },
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
        "template": template_data,
    }


def add_subscription(client, adobe_subscription, order, line):
    """
    Adds a subscription to the corresponding MPT order based on the provided parameters.

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


def set_subscription_actual_sku(client, order, subscription, sku):
    """
    Set the subscription fulfillment parameter to store the actual SKU.

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
    product_id = order["agreement"]["product"]["id"]
    template = get_product_template_or_default(
        client, product_id, MPT_ORDER_STATUS_PROCESSING, template_name
    )
    if not template:
        logger.warning("Template %s not found for product %s", template_name, product_id)
        return

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


class SetupDueDate(Step):
    """Setups properly due date."""

    def __call__(self, client, context, next_step):
        """Setups properly due date."""
        context.order = set_due_date(context.order)
        due_date = get_due_date(context.order)
        context.due_date = due_date
        due_date_str = due_date.strftime("%Y-%m-%d")

        if dt.datetime.now(tz=dt.UTC).date() > due_date:
            logger.info("%s: due date (%s) is reached.", context, due_date_str)
            switch_order_to_failed(
                client,
                context.order,
                ERR_DUE_DATE_REACHED.to_dict(due_date=due_date_str),
            )
            return
        update_order(client, context.order_id, parameters=context.order["parameters"])
        logger.info("%s: due date is set to %s successfully.", context, due_date_str)
        next_step(client, context)


class SetOrUpdateCotermDate(Step):
    """Set or update the fulfillment parameters `cotermDate` with Adobe customer coterm date."""

    def __call__(self, client, context, next_step):
        """Set or update the fulfillment parameters `cotermDate` with Adobe customer coterm date."""
        if has_coterm_date(context.adobe_customer):
            coterm_date = dt.datetime.fromisoformat(context.adobe_customer["cotermDate"]).date()

            needs_update = self.update_coterm_if_needed(context, coterm_date)
            needs_update |= self.commitment_update_if_needed(context)

            if needs_update:
                self.update_order_parameters(client, context, coterm_date)

        next_step(client, context)

    def update_coterm_if_needed(self, context, coterm_date):
        """
        Updates coterm date if coterm date differs in MPT and Adobe.

        Args:
            context (Context): step context
            coterm_date (date): coterm date from Adobe API

        Returns:
            bool: if it need to be updated or not
        """
        needs_update = False
        if coterm_date.isoformat() != get_coterm_date(context.order):
            context.order = set_coterm_date(context.order, coterm_date.isoformat())
            needs_update = True
        return needs_update

    def commitment_update_if_needed(self, context):
        """
        Updates commitment date if commitment exists on Adobe API.

        Args:
            context (Context): step context

        Returns:
            bool: was commitment date updated
        """
        if not context.adobe_customer:
            return False
        commitment = get_3yc_commitment_request(
            context.adobe_customer,
            is_recommitment=False,
        ) or get_3yc_commitment(context.adobe_customer)

        if not commitment:
            return False
        context.order = set_adobe_3yc_enroll_status(context.order, commitment.get("status"))
        context.order = set_adobe_3yc_commitment_request_status(context.order, None)
        context.order = set_adobe_3yc_start_date(context.order, commitment.get("startDate"))
        context.order = set_adobe_3yc_end_date(context.order, commitment.get("endDate"))
        context.order = set_adobe_3yc(context.order, None)
        return True

    def update_order_parameters(self, client, context, coterm_date):
        """
        Update 3YC parameters in MPT Order.

        Args:
            client (MPTClient): MPT API client
            context (Context): Step context
            coterm_date: Adobe coterm date
        """
        update_order(client, context.order_id, parameters=context.order["parameters"])
        updated_params = {"coterm_date": coterm_date.isoformat()}
        commitment = get_3yc_commitment_request(
            context.adobe_customer,
            is_recommitment=False,
        ) or get_3yc_commitment(context.adobe_customer)
        if commitment:
            updated_params.update({
                "3yc_enroll_status": commitment.get("status"),
                "3yc_commitment_request_status": None,
                "3yc_start_date": commitment.get("startDate"),
                "3yc_end_date": commitment.get("endDate"),
                "3yc": None,
            })
        params_str = ", ".join(f"{key}={value}" for key, value in updated_params.items())
        logger.info("%s: Updated parameters: %s", context, params_str)


class StartOrderProcessing(Step):
    """
    Set the template for the processing status.

    Or the delayed one if the processing is delayed due to the renewal window open.
    """

    def __init__(self, template_name):
        self.template_name = template_name

    def __call__(self, client, context, next_step):
        """Set the template for the processing status."""
        product_id = context.order["agreement"]["product"]["id"]
        template = get_product_template_or_default(
            client, product_id, MPT_ORDER_STATUS_PROCESSING, self.template_name
        )
        if not template:
            logger.warning(
                "%s: Template %s not found for product %s", context, self.template_name, product_id
            )

        current_template_id = context.order.get("template", {}).get("id")
        if template and template["id"] != current_template_id:
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


class ValidateRenewalWindow(Step):
    """Check if the renewal window is open. In that case stop the order processing."""

    def __init__(self, *, is_validation=False):
        self.is_validation = is_validation

    def __call__(self, client, context, next_step):
        """Check if the renewal window is open. In that case stop the order processing."""
        if is_coterm_date_within_order_creation_window(context.order):
            coterm_date = get_coterm_date(context.order)
            logger.info(
                "%s: Order is being created within the last 24 hours of coterm date '%s'",
                context,
                coterm_date,
            )
            if self.is_validation:
                context.order = set_order_error(
                    context.order,
                    ERR_COTERM_DATE_IN_LAST_24_HOURS.to_dict(),
                )
            else:
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_COTERM_DATE_IN_LAST_24_HOURS.to_dict(),
                )
                return
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
        return_orders_count = sum(len(value) for value in context.adobe_return_orders.values())
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

                if not is_returnable:
                    continue

                if return_order:
                    all_return_orders.append(return_order)
                    continue

                return_order_created = self._create_return_order(
                    adobe_client, context, returnable_order, deployment_id
                )

                all_return_orders.append(return_order_created)

        if not self._ensure_not_pending_return_orders(context, all_return_orders):
            return

        next_step(client, context)

    def _create_return_order(self, adobe_client, context, returnable_order, deployment_id):
        try:
            return adobe_client.create_return_order(
                context.authorization_id,
                context.adobe_customer_id,
                returnable_order.order,
                returnable_order.line,
                context.order_id,
                deployment_id,
            )
        except AdobeAPIError as error:
            logger.warning("%s", error)
            send_exception(title=f"Error creating return order {context.order_id}", text=str(error))
            raise

    def _ensure_not_pending_return_orders(self, context, all_return_orders):
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
            return False
        return True


class GetPreviewOrder(Step):
    """
    Retrieve a preview order for the upsize/new lines.

    If there are incompatible SKUs
    within the PREVIEW order an error will be thrown by the Adobe API the order will
    be failed and the processing pipeline will stop.
    In case a new order as already been submitted by a previous attempt, this step will be
    skipped and the order processing pipeline will continue.
    """

    def __call__(self, mpt_client, context, next_step):
        """Retrieve a preview order for the upsize/new lines."""
        adobe_client = get_adobe_client()
        if (context.upsize_lines or context.new_lines) and not context.adobe_new_order_id:
            try:
                context.adobe_preview_order = adobe_client.create_preview_order(context)
            except (AdobeError, AdobeCreatePreviewError) as error:
                switch_order_to_failed(
                    mpt_client,
                    context.order,
                    ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
                )
                return

        next_step(mpt_client, context)


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
            flex_discounts = _get_flex_discounts(adobe_order)
            update_order(
                client,
                context.order_id,
                externalIds=context.order["externalIds"],
                parameters={
                    Param.PHASE_FULFILLMENT.value: [
                        {
                            "externalId": Param.FLEXIBLE_DISCOUNTS,
                            "value": flex_discounts,
                        },
                    ]
                },
            )
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


def _get_flex_discounts(adobe_order: dict) -> str | None:
    flex_discounts = [
        {
            "extLineItemNumber": line.get("extLineItemNumber"),
            "offerId": line.get("offerId"),
            "subscriptionId": line.get("subscriptionId"),
            "flexDiscountCode": [flex_discount["code"] for flex_discount in line["flexDiscounts"]],
        }
        for line in adobe_order["lineItems"]
        if line.get("flexDiscounts")
    ]
    return json.dumps(flex_discounts) if flex_discounts else None


class CreateOrUpdateAssets(Step):
    """Create or update assets in MPT based on Adobe Subscriptions."""

    def __call__(self, client, context, next_step):
        """Create or update assets in MPT based on Adobe Subscriptions."""
        if not context.adobe_new_order_id:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        one_time_skus = get_one_time_skus(client, context.order)
        product_id = context.order["agreement"]["product"]["id"]
        template = get_asset_template_by_name(client, product_id, TEMPLATE_ASSET_DEFAULT)
        for line in filter(
            lambda line_item: get_partial_sku(line_item["offerId"]) in one_time_skus,
            context.adobe_new_order["lineItems"],
        ):
            order_line = get_order_line_by_sku(context.order, line["offerId"])
            adobe_subscription = adobe_client.get_subscription(
                context.authorization_id, context.adobe_customer_id, line["subscriptionId"]
            )

            if adobe_subscription["status"] != AdobeStatus.PROCESSED:
                logger.info(
                    "%s: subscription %s for customer %s is in status %s, skip it",
                    context,
                    adobe_subscription["subscriptionId"],
                    context.adobe_customer_id,
                    adobe_subscription["status"],
                )
                continue

            asset = order_line.get("asset")
            asset_data = create_asset_payload(adobe_subscription, order_line, line, template)
            if asset:
                update_order_asset(
                    client, context.order_id, asset["id"], parameters=asset_data["parameters"]
                )
                logger.info(
                    "%s: asset %s (%s) updated.", context, line["subscriptionId"], asset["id"]
                )
            else:
                asset = create_order_asset(client, context.order_id, asset_data)
                logger.info(
                    "%s: asset %s (%s) created", context, line["subscriptionId"], asset["id"]
                )

        next_step(client, context)


class CreateOrUpdateSubscriptions(Step):
    """Create or update subscriptions in MPT based on Adobe Subscriptions."""

    def __call__(self, client, context, next_step):
        """Create or update subscriptions in MPT based on Adobe Subscriptions."""
        if not context.adobe_new_order:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        one_time_skus = get_one_time_skus(client, context.order)

        lines = filter(
            lambda line_item: get_partial_sku(line_item["offerId"]) not in one_time_skus,
            context.adobe_new_order["lineItems"],
        )

        for line in lines:
            order_line = get_order_line_by_sku(context.order, line["offerId"])
            order_subscription = get_subscription_by_line_and_item_id(
                context.order["subscriptions"],
                order_line["item"]["id"],
                order_line["id"],
            )

            if order_subscription:
                self._update_existing_subscription(client, context, order_subscription, line)
            else:
                self._create_new_subscription(client, context, adobe_client, line, order_line)

        next_step(client, context)

    def _update_existing_subscription(self, client, context, order_subscription, line):
        """Update an existing subscription with new Adobe SKU."""
        adobe_sku = line["offerId"]
        set_subscription_actual_sku(
            client,
            context.order,
            order_subscription,
            adobe_sku,
        )
        logger.info(
            "%s: subscription %s (%s) updated",
            context,
            line["subscriptionId"],
            order_subscription["id"],
        )

    def _create_new_subscription(self, client, context, adobe_client, line, order_line):
        """Create a new subscription."""
        adobe_subscription = self._get_adobe_subscription(adobe_client, context, line)
        if not adobe_subscription:
            return

        template = get_template_by_name(
            client,
            context.order["agreement"]["product"]["id"],
            TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE,
        )
        subscription_data = self._build_subscription_data(
            line, order_line, adobe_subscription, template
        )

        subscription = create_subscription(client, context.order_id, subscription_data)
        logger.info(
            "%s: subscription %s (%s) created",
            context,
            line["subscriptionId"],
            subscription["id"],
        )

    def _get_adobe_subscription(self, adobe_client, context, line):
        """Get Adobe subscription and validate its status."""
        adobe_subscription = adobe_client.get_subscription(
            context.authorization_id,
            context.adobe_customer_id,
            line["subscriptionId"],
        )

        if adobe_subscription["status"] != AdobeStatus.PROCESSED:
            logger.warning(
                "%s: subscription %s for customer %s is in status %s, skip it",
                context,
                adobe_subscription["subscriptionId"],
                context.adobe_customer_id,
                adobe_subscription["status"],
            )
            return None

        return adobe_subscription

    def _build_subscription_data(self, line, order_line, adobe_subscription, template):
        """Build subscription data dictionary."""
        subscription_data = {
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
            "template": None,
        }
        if template:
            subscription_data["template"] = {
                "id": template.get("id"),
                "name": template.get("name"),
            }

        return subscription_data


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


class SetSubscriptionTemplate(Step):
    """Set subscription template."""

    def __call__(self, mpt_client, context, next_step):
        """Set subscription template."""
        adobe_client = get_adobe_client()
        adobe_subscriptions = adobe_client.get_subscriptions(
            context.authorization_id,
            context.adobe_customer_id,
        )

        adobe_subscriptions_map = {
            item["subscriptionId"]: item for item in adobe_subscriptions["items"]
        }

        for subscription in context.order["agreement"]["subscriptions"]:
            subscription_id = subscription["externalIds"]["vendor"]
            adobe_subscription = adobe_subscriptions_map.get(subscription_id)

            if not adobe_subscription:
                logger.warning(
                    "%s: Adobe subscription %s not found, skipping", context, subscription_id
                )
                continue

            product_id = context.order["agreement"]["product"]["id"]
            template_data = get_template_data_by_adobe_subscription(adobe_subscription, product_id)
            update_agreement_subscription(mpt_client, subscription["id"], template=template_data)

        next_step(mpt_client, context)


class SyncAgreement(Step):
    """Sync agreement."""

    def __call__(self, mpt_client, context, next_step):
        """Sync agreement."""
        adobe_client = get_adobe_client()
        sync_agreements_by_agreement_ids(
            mpt_client, adobe_client, [context.agreement_id], dry_run=False, sync_prices=True
        )
        logger.info("%s: agreement synchronized", context)
        next_step(mpt_client, context)


class ValidateDuplicateLines(Step):
    """Validates if Adobe Order contains duplicated items, with the same sku."""

    def __call__(self, client, context, next_step):
        """Validates if Adobe Order contains duplicated items, with the same sku."""
        items = [line["item"]["id"] for line in context.order["lines"]]
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            switch_order_to_failed(
                client,
                context.order,
                ERR_DUPLICATED_ITEMS.to_dict(duplicates=",".join(duplicates)),
            )
            return

        items = []
        for subscription in context.order["agreement"]["subscriptions"]:
            for line in subscription["lines"]:
                items.append(line["item"]["id"])

        items.extend([
            line["item"]["id"] for line in context.order["lines"] if line["oldQuantity"] == 0
        ])
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            switch_order_to_failed(
                client,
                context.order,
                ERR_EXISTING_ITEMS.to_dict(duplicates=",".join(duplicates)),
            )
            return

        next_step(client, context)


def send_gc_mpt_notification(mpt_client, order: dict, items_with_deployment: list) -> None:
    """
    Send MPT API notification to the subscribers according to the current order status.

    It embeds the current order template.

    Args:
        mpt_client (MPTClient): MPT API client
        items_with_deployment (list): The list of items with deployment ID.
        order (dict): The order for which the notification should be sent.
    """
    items = "<ul>\n" + "\n".join(f"\t<li>{item}</li>" for item in items_with_deployment) + "\n</ul>"

    context = {
        "order": order,
        "activation_template": "This order needs your attention because it contains items with "
        "a deployment ID associated. Please remove the following items with "
        f"deployment associated manually. {items}"
        "Then, change the main agreement status to 'pending' on Airtable.",
        "api_base_url": settings.MPT_API_BASE_URL,
        "portal_base_url": settings.MPT_PORTAL_BASE_URL,
    }

    subject = (
        f"This order need your attention {order['id']} for {order['agreement']['buyer']['name']}"
    )

    mpt_notify(
        mpt_client,
        order["agreement"]["licensee"]["account"]["id"],
        order["agreement"]["buyer"]["id"],
        subject,
        "notification",
        context,
    )


class NullifyFlexDiscountParam(Step):
    """Handles the nullification of flex discounts on an agreement."""

    def __call__(self, mpt_client, context, next_step):
        """
        Nullifies flex discounts on the specified agreement.

        Args:
            mpt_client: The client used to interact with the MPT API.
            context: The operational context containing details like agreement ID.
            next_step: The next processing step after nullifying discounts.

        """
        logger.info("Nullifying flex discounts on the agreement %s", context.agreement_id)
        try:
            update_agreement(
                mpt_client,
                context.agreement_id,
                parameters={
                    Param.PHASE_FULFILLMENT.value: [
                        {
                            "externalId": Param.FLEXIBLE_DISCOUNTS,
                            "value": None,
                            #  The Prop is a JSON type, but MPT API accepts only string here
                        },
                    ]
                },
            )
        except Exception:
            logger.exception("%s: failed to nullify flex discounts.", context)
        next_step(mpt_client, context)
