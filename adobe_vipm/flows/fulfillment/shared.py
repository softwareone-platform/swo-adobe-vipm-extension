"""
This module contains shared functions used by the different fulfillment flows.
"""

import logging
from collections import Counter
from datetime import date, datetime, timedelta

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

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    STATUS_PENDING,
    STATUS_PROCESSED,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.utils import (
    get_3yc_commitment,
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
    PARAM_3YC,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_ADOBE_SKU,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_CURRENT_QUANTITY,
    PARAM_RENEWAL_DATE,
    PARAM_RENEWAL_QUANTITY,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    get_address,
    get_adobe_customer_id,
    get_coterm_date,
    get_deployment_id,
    get_due_date,
    get_next_sync,
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
    set_next_sync,
    set_order_error,
    set_template,
    split_phone_number,
)
from adobe_vipm.flows.utils.customer import has_coterm_date
from adobe_vipm.notifications import mpt_notify
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

    address = customer["companyProfile"].get("address", {})
    contact = customer["companyProfile"]["contacts"][0]
    commitment = get_3yc_commitment(customer)

    customer_data = {
        PARAM_COMPANY_NAME: sanitize_company_name(
            customer["companyProfile"]["companyName"]
        ),
        PARAM_CONTACT: {
            "firstName": sanitize_first_last_name(contact["firstName"]),
            "lastName": sanitize_first_last_name(contact["lastName"]),
            "email": contact["email"],
            "phone": split_phone_number(contact.get("phoneNumber"), address.get("country", "")),
        },
    }

    if address:
        customer_data[PARAM_ADDRESS] = get_address(address)

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
    return order


def switch_order_to_query(client, order, template_name=None):
    """
    Switches the status of an MPT order to 'query' and resetting due date and
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
    Handle the reprocessing of an order.
    If the due date is reached - fail the order

    Args:
        mpt_client (MPTClient): an instance of the Marketplace platform client.
        order (dct): The MPT order.
        adobe_order_id (str): identifier of the Adobe order.
        adobe_order_type (str, optional): type of Adobe order (NEW or RETURN).
        Defaults to "NEW".

    Returns:
        None
    """
    due_date = get_due_date(order)
    due_date_str = due_date.strftime("%Y-%m-%d")
    if date.today() <= due_date:
        logger.info(
            f"Order {order['id']} ({adobe_order_id}: {adobe_order_type}) "
            "is still processing on Adobe side, wait.",
        )
        return
    logger.info(
        f'The order {order["id"]} ({adobe_order_id}) '
        f"has reached the due date ({due_date_str}).",
    )
    reason = f"Due date is reached ({due_date_str})."
    fail_order(
        client, order["id"], reason, ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=reason)
    )
    logger.warning(f"Order {order['id']} has been failed: {reason}.")


def switch_order_to_completed(client, order, template_name):
    """
    Reset the retry count to zero and switch the MPT order
    to completed using the completed template.

    Args:
        client (MPTClient):  an instance of the Marketplace platform client.
        order (dict): The MPT order that have to be switched to completed.
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
    logger.info(f'Order {order["id"]} has been completed successfully')


def add_subscription(client, adobe_subscription, order, line):
    """
    Adds a subscription to the correspoding MPT order based on the provided parameters.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        adobe_subscription(dict): A subscription object retrieved from the
            Adobe API.
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
                        "externalId": PARAM_ADOBE_SKU,
                        "value": line["offerId"],
                    },
                    {
                        "externalId": PARAM_CURRENT_QUANTITY,
                        "value": str(adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": PARAM_RENEWAL_QUANTITY,
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
                        ),
                    },
                    {
                        "externalId": PARAM_RENEWAL_DATE,
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
    Sets due date and send email notification

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


def send_mpt_notification(mpt_client: MPTClient, order: dict) -> None:
    """
    Send an MPT notification to the customer according to the
    current order status.
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
    subject = (
        f"Order status update {order['id']} "
        f"for {order['agreement']['buyer']['name']}"
    )
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
    return (TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE
            if auto_renewal
            else TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE)


class SetupDueDate(Step):
    """
    Setups properly due date
    """

    def __call__(self, client, context, next_step):
        context.order = set_due_date(context.order)
        due_date = get_due_date(context.order)
        context.due_date = due_date
        due_date_str = due_date.strftime("%Y-%m-%d")

        if date.today() > due_date:
            logger.info(
                f"{context}: due date ({due_date_str}) is reached.",
            )
            switch_order_to_failed(
                client,
                context.order,
                ERR_DUE_DATE_REACHED.to_dict(due_date=due_date_str),
            )
            return
        update_order(client, context.order_id, parameters=context.order["parameters"])
        logger.info(f"{context}: due date is set to {due_date_str} successfully.")
        next_step(client, context)


class SetOrUpdateCotermNextSyncDates(Step):
    """
    Set or update the fulfillment parameters `cotermDate` and
    `nextSync` according to the Adobe customer coterm date.
    """

    def __call__(self, client, context, next_step):
        if has_coterm_date(context.adobe_customer):
            coterm_date = datetime.fromisoformat(
                context.adobe_customer["cotermDate"]
            ).date()
            next_sync = coterm_date + timedelta(days=1)

            needs_update = self.coterm_and_next_sync_update_if_needed(
                context,
                coterm_date,
                next_sync
            )
            needs_update |= self.commitment_update_if_needed(context)

            if needs_update:
                self.update_order_parameters(client, context, coterm_date, next_sync)

        next_step(client, context)

    def coterm_and_next_sync_update_if_needed(self, context, coterm_date, next_sync):
        needs_update = False
        if coterm_date.isoformat() != get_coterm_date(context.order):
            context.order = set_coterm_date(context.order, coterm_date.isoformat())
            needs_update = True
        if next_sync.isoformat() != get_next_sync(context.order):
            context.order = set_next_sync(context.order, next_sync.isoformat())
            needs_update = True
        return needs_update

    def commitment_update_if_needed(self, context):
        if not context.adobe_customer:
            return False
        commitment = get_3yc_commitment_request(context.adobe_customer)
        if not commitment:
            return False
        context.order = set_adobe_3yc_enroll_status(context.order, commitment["status"])
        context.order = set_adobe_3yc_commitment_request_status(context.order, commitment["status"])
        context.order = set_adobe_3yc_start_date(context.order, commitment["startDate"])
        context.order = set_adobe_3yc_end_date(context.order, commitment["endDate"])
        return True

    def update_order_parameters(self, client, context, coterm_date, next_sync):
        update_order(client, context.order_id, parameters=context.order["parameters"])
        updated_params = {
            "coterm_date": coterm_date.isoformat(),
            "next_sync": next_sync.isoformat(),
        }
        commitment = get_3yc_commitment_request(context.adobe_customer)
        if commitment:
            updated_params.update({
                "3yc_enroll_status": commitment["status"],
                "3yc_commitment_request_status": commitment["status"],
                "3yc_start_date": commitment["startDate"],
                "3yc_end_date": commitment["endDate"]
            })
        params_str = ', '.join(f'{k}={v}' for k, v in updated_params.items())
        logger.info(f"{context}: Updated parameters: {params_str}")

class StartOrderProcessing(Step):
    """
    Set the template for the processing status or the
    delayed one if the processing is delated due to the
    renewal window open.
    """

    def __init__(self, template_name):
        self.template_name = template_name

    def __call__(self, client, context, next_step):
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
                f"{context}: processing template set to {self.template_name} "
                f"({template['id']})"
            )
        logger.info(f"{context}: processing template is ok, continue")
        if not context.due_date:
            send_mpt_notification(client, context.order)
        next_step(client, context)

class ValidateRenewalWindow(Step):
    """
    Check if the renewal window is open. In that case stop the order processing.
    """

    def __init__(self, is_validation=False):
        self.is_validation = is_validation

    def __call__(self, client, context, next_step):
        if is_coterm_date_within_order_creation_window(context.order):
            coterm_date = get_coterm_date(context.order)
            logger.info(
                f"{context}: Order is being created within the last 24 "
                f"hours of coterm date '{coterm_date}'"
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
    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        context.adobe_return_orders = (
            adobe_client.get_return_orders_by_external_reference(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
            )
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
        deployment_id = get_deployment_id(context.order)
        is_returnable = False
        for sku, returnable_orders in context.adobe_returnable_orders.items():
            return_orders = context.adobe_return_orders.get(sku, [])
            for returnable_order, return_order in map_returnable_to_return_orders(
                returnable_orders or [], return_orders
            ):
                returnable_order_deployment_id = returnable_order.line.get(
                    "deploymentId", None
                )
                is_returnable = (
                    (deployment_id == returnable_order_deployment_id)
                    if deployment_id
                    else True
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
        if (
            context.upsize_lines or context.new_lines
        ) and not context.adobe_new_order_id:
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


class SubmitNewOrder(Step):
    """
    Submit a new order if there are new/upsizing items to purchase.
    Wait for the order to be processed by Adobe before moving to
    the next step.
    """

    def __call__(self, client, context, next_step):
        if not (context.upsize_lines or context.new_lines):
            logger.info(
                f"{context}: skip creating order. There are no upsize lines or new lines",
            )
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
            logger.info(f'{context}: new adobe order created: {adobe_order["orderId"]}')
            context.order = set_adobe_order_id(context.order, adobe_order["orderId"])
            update_order(
                client, context.order_id, externalIds=context.order["externalIds"]
            )
        elif not context.adobe_new_order_id and not context.adobe_preview_order:
            logger.info(
                f"{context}: skip creating Adobe Order, preview order creation was skipped"
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
        if adobe_order["status"] == STATUS_PENDING:
            logger.info(
                f"{context}: adobe order {context.adobe_new_order_id} is still pending."
            )
            return
        elif adobe_order["status"] in UNRECOVERABLE_ORDER_STATUSES:
            error = ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS.to_dict(
                description=ORDER_STATUS_DESCRIPTION[adobe_order["status"]],
            )
            switch_order_to_failed(
                client,
                context.order,
                error,
            )
            logger.warning(
                f"{context}: The adobe order has been failed {error['message']}."
            )
            return
        elif adobe_order["status"] != STATUS_PROCESSED:
            error = ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(
                status=adobe_order["status"]
            )
            switch_order_to_failed(client, context.order, error)
            logger.warning(
                f"{context}: the order has been failed due to {error['message']}."
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
                context.adobe_new_order["lineItems"],
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
                                },
                                {
                                    "externalId": PARAM_CURRENT_QUANTITY,
                                    "value": str(adobe_subscription["currentQuantity"]),
                                },
                                {
                                    "externalId": PARAM_RENEWAL_QUANTITY,
                                    "value": str(
                                        adobe_subscription["autoRenewal"][
                                            "renewalQuantity"
                                        ]
                                    ),
                                },
                                {
                                    "externalId": PARAM_RENEWAL_DATE,
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
                    subscription = create_subscription(
                        client, context.order_id, subscription
                    )
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

class CompleteOrder(Step):
    def __init__(self, template_name):
        self.template_name = template_name

    def __call__(self, client, context, next_step):
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
        logger.info(f"{context}: order has been completed successfully")
        next_step(client, context)

class SyncAgreement(Step):
    def __call__(self, client, context, next_step):
        sync_agreements_by_agreement_ids(client, [context.agreement_id])
        logger.info(f"{context}: agreement synchoronized")
        next_step(client, context)


class ValidateDuplicateLines(Step):
    def __call__(self, client, context, next_step):
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

        items.extend(
            [
                line["item"]["id"]
                for line in context.order["lines"]
                if line["oldQuantity"] == 0
            ]
        )
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
    """Send MPT API notification to the subscribers according to the
    current order status.
    It embeds the current order template.

    Args:
        items_with_deployment (list): The list of items with deployment ID.
        order (dict): The order for which the notification should be sent.
    """
    items = (
        "<ul>\n"
        + "\n".join(f"\t<li>{item}</li>" for item in items_with_deployment)
        + "\n</ul>"
    )

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
