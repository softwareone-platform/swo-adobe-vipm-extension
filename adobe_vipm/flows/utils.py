import copy
import functools
from datetime import date, datetime, timedelta

import phonenumbers
import regex as re
from django.conf import settings
from markdown_it import MarkdownIt
from swo.mpt.extensions.runtime.djapp.conf import get_for_product

from adobe_vipm.adobe.constants import (
    OFFER_TYPE_CONSUMABLES,
    OFFER_TYPE_LICENSE,
    STATUS_INACTIVE_OR_GENERIC_FAILURE,
)
from adobe_vipm.flows.constants import (
    NEW_CUSTOMER_PARAMETERS,
    OPTIONAL_CUSTOMER_ORDER_PARAMS,
    ORDER_TYPE_CHANGE,
    ORDER_TYPE_PURCHASE,
    ORDER_TYPE_TERMINATION,
    PARAM_3YC,
    PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_END_DATE,
    PARAM_3YC_ENROLL_STATUS,
    PARAM_3YC_LICENSES,
    PARAM_3YC_START_DATE,
    PARAM_ADDRESS,
    PARAM_AGREEMENT_TYPE,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_COTERM_DATE,
    PARAM_CUSTOMER_ID,
    PARAM_DUE_DATE,
    PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
    PARAM_MEMBERSHIP_ID,
    PARAM_NEXT_SYNC_DATE,
    PARAM_PHASE_FULFILLMENT,
    PARAM_PHASE_ORDERING,
    REQUIRED_CUSTOMER_ORDER_PARAMS,
    STATUS_MARKET_SEGMENT_PENDING,
)
from adobe_vipm.flows.mpt import get_product_onetime_items_by_ids
from adobe_vipm.notifications import send_exception
from adobe_vipm.utils import find_first, get_partial_sku

TRACE_ID_REGEX = re.compile(r"(\(00-[0-9a-f]{32}-[0-9a-f]{16}-01\))")


def get_parameter(parameter_phase, source, param_external_id):
    """
    Returns a parameter of a given phase by its external identifier.
    Returns an empty dictionary if the parameter is not found.
    Args:
        parameter_phase (str): The phase of the parameter (ordering, fulfillment).
        source (str): The source business object from which the parameter
        should be extracted.
        param_external_id (str): The unique external identifier of the parameter.

    Returns:
        dict: The parameter object or an empty dictionary if not found.
    """
    return find_first(
        lambda x: x["externalId"] == param_external_id,
        source["parameters"][parameter_phase],
        default={},
    )


get_ordering_parameter = functools.partial(get_parameter, PARAM_PHASE_ORDERING)

get_fulfillment_parameter = functools.partial(get_parameter, PARAM_PHASE_FULFILLMENT)


def get_adobe_membership_id(source):
    """
    Get the Adobe membership identifier from the correspoding ordering
    parameter or None if it is not set.

    Args:
        source (dict): The business object from which the membership id
        should be retrieved.

    Returns:
        str: The Adobe membership identifier or None if it isn't set.
    """
    param = get_ordering_parameter(
        source,
        PARAM_MEMBERSHIP_ID,
    )
    return param.get("value")


def is_purchase_order(order):
    """
    Check if the order is a real purchase order or a subscriptions transfer order.
    Args:
        source (str): The order to check.

    Returns:
        bool: True if it is a real purchase order, False otherwise.
    """
    return order["type"] == ORDER_TYPE_PURCHASE and is_new_customer(order)


def is_transfer_order(order):
    """
    Check if the order is a subscriptions transfer order.
    Args:
        source (str): The order to check.

    Returns:
        bool: True if it is a subscriptions transfer order, False otherwise.
    """
    return order["type"] == ORDER_TYPE_PURCHASE and not is_new_customer(order)


def is_change_order(order):
    return order["type"] == ORDER_TYPE_CHANGE


def is_termination_order(order):
    return order["type"] == ORDER_TYPE_TERMINATION


def get_adobe_customer_id(source):
    """
    Get the Adobe customer identifier from the correspoding fulfillment
    parameter or None if it is not set.

    Args:
        source (dict): The business object from which the customer id
        should be retrieved.

    Returns:
        str: The Adobe customer identifier or None if it isn't set.
    """
    param = get_fulfillment_parameter(
        source,
        PARAM_CUSTOMER_ID,
    )
    return param.get("value")


def set_adobe_customer_id(order, customer_id):
    """
    Create a copy of the order. Set the CustomerId
    fulfillment parameter on the copy of the original order.
    Return the copy of the original order with the
    CustomerId parameter filled.
    """
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_CUSTOMER_ID,
    )
    customer_ff_param["value"] = customer_id
    return updated_order


def set_next_sync(order, next_sync):
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_NEXT_SYNC_DATE,
    )
    customer_ff_param["value"] = next_sync
    return updated_order


def get_next_sync(order):
    return get_fulfillment_parameter(
        order,
        PARAM_NEXT_SYNC_DATE,
    ).get("value")


def get_adobe_order_id(order):
    """
    Retrieve the Adobe order identifier from the order vendor external id.

    Args:
        order (dict): The order from which the Adobe order id should
        be retrieved.

    Returns:
        str: The Adobe order identifier or None if it is not set.
    """
    return order.get("externalIds", {}).get("vendor")


def set_adobe_order_id(order, adobe_order_id):
    """
    Set Adobe order identifier as the order vendor external id attribute.

    Args:
        order (dict): The order for which the Adobe order id should
        be set.

    Returns:
        dict: The updated order with the vendor external id attribute set.
    """
    updated_order = copy.deepcopy(order)
    updated_order["externalIds"] = updated_order.get("externalIds", {}) | {
        "vendor": adobe_order_id
    }
    return updated_order


def get_customer_data(order):
    """
    Returns a dictionary with the customer data extracted from the
    corresponding ordering parameters.

    Args:
        order (dict): The order from which the customer data must be
        retrieved.

    Returns:
        dict: A dictionary with the customer data.
    """
    customer_data = {}
    for param_external_id in (
        PARAM_COMPANY_NAME,
        PARAM_ADDRESS,
        PARAM_CONTACT,
        PARAM_3YC,
        PARAM_3YC_CONSUMABLES,
        PARAM_3YC_LICENSES,
    ):
        param = get_ordering_parameter(
            order,
            param_external_id,
        )
        customer_data[param_external_id] = param.get("value")

    return customer_data


def set_customer_data(order, customer_data):
    """
    Set the ordering parameters with the customer data.

    Args:
        order (dict): The order for which the parameters must be set.
        customer_data (dict): the customer data that must be set

    Returns:
        dict: The order updated with the ordering parameters for customer data.
    """
    updated_order = copy.deepcopy(order)
    for param_external_id, value in customer_data.items():
        get_ordering_parameter(
            updated_order,
            param_external_id,
        )["value"] = value
    return updated_order


def set_ordering_parameter_error(order, param_external_id, error, required=True):
    """
    Set a validation error on an ordering parameter.

    Args:
        order (dict): The order that contains the parameter.
        param_external_id (str): The external identifier of the parameter.
        error (dict): The error (id, message) that must be set.

    Returns:
        dict: The order updated.
    """
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["error"] = error
    param["constraints"] = {
        "hidden": False,
        "required": required,
    }
    return updated_order


def reset_ordering_parameters_error(order):
    """
    Reset errors for all ordering parameters

    Args:
        order (dict): The order that contains the parameter.

    Returns:
        dict: The order updated.
    """
    updated_order = copy.deepcopy(order)

    for param in updated_order["parameters"][PARAM_PHASE_ORDERING]:
        param["error"] = None

    return updated_order


def get_order_line_by_sku(order, sku):
    """
    Returns an order line object by sku or None if not found.

    Args:
        order (dict): The order from which the line
        must be retrieved.
        sku (str): Full Adobe Item SKU, including discount level

    Returns:
        dict: The line object or None if not found.
    """
    # important to have `in` here, since line items contain cutted Adobe Item SKU
    # and sku is a full Adobe Item SKU including discount level
    return find_first(
        lambda line: line["item"]["externalIds"]["vendor"] in sku,
        order["lines"],
    )


def get_price_item_by_line_sku(prices, line_sku):
    return find_first(
        lambda price_item: price_item[0].startswith(line_sku),
        list(prices.items()),
    )


def set_due_date(order):
    """
    Sets DUE_DATE parameter to the value of today() + EXT_DUE_DATE_DAYS if it is not set yet
    Args:
        order (dict): The order that containts the due date fulfillment
        parameter.

    Returns:
        dict: The updated order.
    """
    updated_order = copy.deepcopy(order)
    param = get_fulfillment_parameter(
        updated_order,
        PARAM_DUE_DATE,
    )

    if not param or not param.get("value"):
        due_date = date.today() + timedelta(
            days=int(settings.EXTENSION_CONFIG.get("DUE_DATE_DAYS"))
        )
        param["value"] = due_date.strftime("%Y-%m-%d")

    return updated_order


def get_due_date(order):
    """
    Gets DUE_DATE parameter
    Args:
        order (dict): The order that containts the due date fulfillment
        parameter.

    Returns:
        dict: The updated order.
    """
    param = get_fulfillment_parameter(
        order,
        PARAM_DUE_DATE,
    )

    return (
        datetime.strptime(param["value"], "%Y-%m-%d").date() if param.get("value") else None
    )


def reset_due_date(order):
    """
    Reset the due date fulfillment parameter to None. It is needed to
    have due date empty on next order published
    Args:
        order (dict): The order that containts the due date fulfillment
        parameter.

    Returns:
        dict: The updated order.
    """
    param = get_fulfillment_parameter(
        order,
        PARAM_DUE_DATE,
    )
    param["value"] = None

    return order


def get_subscription_by_line_and_item_id(subscriptions, item_id, line_id):
    """
    Return a subscription by line id and sku.

    Args:
        subscriptions (list): a list of subscription obects.
        vendor_external_id (str): the item SKU
        line_id (str): the id of the order line that should contain the given SKU.

    Returns:
        dict: the corresponding subscription if it is found, None otherwise.
    """
    for subscription in subscriptions:
        item = find_first(
            lambda x: x["id"] == line_id and x["item"]["id"] == item_id,
            subscription["lines"],
        )

        if item:
            return subscription


def get_adobe_subscription_id(subscription):
    """
    Return the value of the subscription id from the subscription.

    Args:
        subscription (dict): the subscription object from which extract
        the adobe subscription id.
    Returns:
        str: the value of the subscription id parameter if found, None otherwise.
    """
    return subscription.get("externalIds", {}).get("vendor")


def split_downsizes_and_upsizes(order):
    """
    Returns a tuple where the first element
    is a list of items to downsize and the second
    a list of items to upsize.

    Args:
        order (dict): The order which lines must be splitted.

    Returns:
        tuple: (downsizes, upsizes)
    """
    return (
        list(
            filter(lambda line: line["quantity"] < line["oldQuantity"], order["lines"])
        ),
        list(
            filter(lambda line: line["quantity"] > line["oldQuantity"], order["lines"])
        ),
    )


def is_new_customer(source):
    param = get_ordering_parameter(
        source,
        PARAM_AGREEMENT_TYPE,
    )
    return param.get("value") == "New"


def set_parameter_visible(order, param_external_id):
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": False,
        "required": param_external_id not in OPTIONAL_CUSTOMER_ORDER_PARAMS,
    }
    return updated_order


def set_parameter_hidden(order, param_external_id):
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": True,
        "required": False,
    }
    return updated_order


def set_adobe_3yc_enroll_status(order, enroll_status):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_ENROLL_STATUS,
    )
    ff_param["value"] = enroll_status
    return updated_order


def set_adobe_3yc_commitment_request_status(order, status):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    )
    ff_param["value"] = status
    return updated_order


def set_adobe_3yc_start_date(order, start_date):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_START_DATE,
    )
    ff_param["value"] = start_date
    return updated_order


def set_adobe_3yc_end_date(order, end_date):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_END_DATE,
    )
    ff_param["value"] = end_date
    return updated_order


def set_order_error(order, error):
    updated_order = copy.deepcopy(order)
    updated_order["error"] = error
    return updated_order


def reset_order_error(order):
    updated_order = copy.deepcopy(order)
    updated_order["error"] = None
    return updated_order


def split_phone_number(phone_number, country):
    if not phone_number:
        return

    pn = None
    try:
        pn = phonenumbers.parse(phone_number, keep_raw_input=True)
    except phonenumbers.NumberParseException:
        try:
            pn = phonenumbers.parse(phone_number, country, keep_raw_input=True)
        except phonenumbers.NumberParseException:
            return

    country_code = f"+{pn.country_code}"
    leading_zero = "0" if pn.italian_leading_zero else ""
    number = f"{leading_zero}{pn.national_number}{pn.extension or ''}".strip()
    return {
        "prefix": country_code,
        "number": number,
    }


def is_ordering_param_required(source, param_external_id):
    param = get_ordering_parameter(source, param_external_id)
    return (param.get("constraints", {}) or {}).get("required", False)


def is_purchase_validation_enabled(order):
    return all(
        is_ordering_param_required(order, param_external_id)
        for param_external_id in REQUIRED_CUSTOMER_ORDER_PARAMS
    )


def is_transfer_validation_enabled(order):
    return is_ordering_param_required(order, PARAM_MEMBERSHIP_ID)


def update_parameters_visibility(order):
    if is_new_customer(order):
        for param in NEW_CUSTOMER_PARAMETERS:
            order = set_parameter_visible(order, param)
        order = set_parameter_hidden(order, PARAM_MEMBERSHIP_ID)
    else:
        for param in NEW_CUSTOMER_PARAMETERS:
            order = set_parameter_hidden(order, param)
        order = set_parameter_visible(order, PARAM_MEMBERSHIP_ID)
    return order


def get_company_name(source):
    return get_ordering_parameter(
        source,
        PARAM_COMPANY_NAME,
    ).get("value")


def strip_trace_id(traceback):
    return TRACE_ID_REGEX.sub("(<omitted>)", traceback)


@functools.cache
def notify_unhandled_exception_in_teams(process, order_id, traceback):
    send_exception(
        f"Order {process} unhandled exception!",
        f"An unhandled exception has been raised while performing {process} "
        f"of the order **{order_id}**:\n\n"
        f"```{traceback}```",
    )


def get_notifications_recipient(order):
    return (get_ordering_parameter(order, PARAM_CONTACT).get("value", {}) or {}).get(
        "email"
    ) or (order["agreement"]["buyer"].get("contact", {}) or {}).get("email")


def md2html(template):
    return MarkdownIt("commonmark", {"breaks": True, "html": True}).render(template)


def update_ordering_parameter_value(order, param_external_id, value):
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["value"] = value

    return updated_order


def is_transferring_item_expired(item):
    if "status" in item and item["status"] == STATUS_INACTIVE_OR_GENERIC_FAILURE:
        return True

    renewal_date = date.fromisoformat(item["renewalDate"])
    return date.today() > renewal_date


def are_all_transferring_items_expired(adobe_items):
    """
    Check if all Adobe subscriptions to be transferred are expired.
    Args:
        adobe_items (list): List of adobe items to be transferred.
        must be extracted.

    Returns:
        bool: True if all Adobe subscriptions are expired, False otherwise.
    """
    return all(is_transferring_item_expired(item) for item in adobe_items)


def get_transfer_item_sku_by_subscription(trf, sub_id):
    item = find_first(
        lambda x: x["subscriptionId"] == sub_id,
        trf["lineItems"],
    )
    return item.get("offerId") if item else None


def get_customer_licenses_discount_level(customer):
    licenses_discount = find_first(
        lambda x: x["offerType"] == OFFER_TYPE_LICENSE, customer["discounts"]
    )
    return licenses_discount["level"]


def get_customer_consumables_discount_level(customer):
    licenses_discount = find_first(
        lambda x: x["offerType"] == OFFER_TYPE_CONSUMABLES, customer["discounts"]
    )
    return licenses_discount["level"]


def is_consumables_sku(sku):
    return sku[10] == "T"


def get_market_segment(product_id):
    return get_for_product(settings, "PRODUCT_SEGMENT", product_id)


def get_market_segment_eligibility_status(order):
    return get_fulfillment_parameter(
        order,
        PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
    ).get("value")


def set_market_segment_eligibility_status_pending(order):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
    )
    ff_param["value"] = STATUS_MARKET_SEGMENT_PENDING
    return updated_order


def set_coterm_date(order, coterm_date):
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_COTERM_DATE,
    )
    customer_ff_param["value"] = coterm_date
    return updated_order


def get_coterm_date(order):
    return get_fulfillment_parameter(
        order,
        PARAM_COTERM_DATE,
    ).get("value")


def is_renewal_window_open(order):
    if not get_coterm_date(order):
        return False
    coterm_date = datetime.fromisoformat(get_coterm_date(order)).date()
    today = date.today()
    return coterm_date - timedelta(days=4) <= today <= coterm_date


def map_returnable_to_return_orders(returnable_orders, return_orders):
    mapped = []

    def filter_by_reference_order(reference_order_id, item):
        return item["referenceOrderId"] == reference_order_id

    for returnable_order in returnable_orders:
        return_order = find_first(
            functools.partial(
                filter_by_reference_order, returnable_order.order["orderId"]
            ),
            return_orders,
        )
        mapped.append((returnable_order, return_order))

    return mapped


def set_template(order, template):
    updated_order = copy.deepcopy(order)
    updated_order["template"] = template
    return updated_order


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


def has_order_line_updated(order_lines, adobe_items, quantity_field):
    """
    Compare order lines and Adobe items to be transferred
    Args:
        order_lines (list): List of order lines
        adobe_items (list): List of adobe items to be transferred.
        quantity_field (str): The name of the field that contains the quantity depending on the
        provided `adobe_object` argument.

    Returns:
        bool: True if order line is not equal to adobe items, False otherwise.

    """
    order_line_map = {
        order_line["item"]["externalIds"]["vendor"]: order_line["quantity"]
        for order_line in order_lines
    }

    adobe_items_map = {
        get_partial_sku(adobe_item["offerId"]): adobe_item[quantity_field]
        for adobe_item in adobe_items
    }
    return order_line_map != adobe_items_map

