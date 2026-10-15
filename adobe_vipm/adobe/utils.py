import logging

from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.constants import (
    FLEX_DISCOUNT_RESULT_SUCCESS,
    REGEX_SANITIZE_COMPANY_NAME,
    REGEX_SANITIZE_FIRST_LAST_NAME,
)

logger = logging.getLogger(__name__)


def is_flex_discount_applied(flex_discount: dict) -> bool:
    """Return whether Adobe applied a line flex discount.

    Only an explicit ``result: SUCCESS`` confirms it; a missing result is not a
    confirmation, so a code Adobe did not report on is never committed or recorded
    as redeemed.
    """
    return flex_discount.get("result") == FLEX_DISCOUNT_RESULT_SUCCESS


def get_item_by_partial_sku(line_items, sku):
    """
    Get the full SKU from a list of line_items given the partial sku.

    Args:
        line_items (list): List of item to search.
        sku (str): The partial SKU to search in
        the list of item.

    Returns:
        str: The full SKU if found, None if not.
    """
    return find_first(
        lambda line_item: line_item["offerId"].startswith(sku),
        line_items,
        default={},
    )


def get_item_by_subcription_id(line_items, subscription_id):
    """
    Get the line item by subscription id.

    Args:
        line_items (list): List of item to search.
        subscription_id (str): The subscription id to search in
        the list of item.

    Returns:
        dict: The line item if found, None if not.
    """
    return find_first(
        lambda line_item: line_item["subscriptionId"] == subscription_id,
        line_items,
        default={},
    )


def get_line_remaining_quantity(line_item: dict) -> int:
    """
    Get the quantity of an Adobe NEW or RENEWAL order line item that can still be returned.

    Adobe reports it as ``remainingQuantity``: the line quantity minus the returns and
    mid-term switch plan cancellations placed against the line. When the field is missing
    (environment without the partial returns release) the whole line quantity is used.

    Args:
        line_item: Adobe order line item.

    Returns:
        The returnable quantity of the line item.
    """
    remaining_quantity = line_item.get("remainingQuantity")
    if remaining_quantity is None:
        logger.warning(
            "Adobe line item %s (offer %s) has no remainingQuantity, using its quantity %s",
            line_item.get("extLineItemNumber"),
            line_item.get("offerId"),
            line_item["quantity"],
        )
        return line_item["quantity"]
    return remaining_quantity


def get_returned_quantity(return_orders: list[dict], order_id: str, line_item: dict) -> int:
    """
    Get the quantity that some RETURN orders returned from a line item of an order.

    Args:
        return_orders: Adobe RETURN orders.
        order_id: Adobe identifier of the returned NEW or RENEWAL order.
        line_item: Line item of the returned order.

    Returns:
        The total quantity returned from the line item.
    """
    return sum(
        return_line["quantity"]
        for return_order in return_orders
        if return_order["referenceOrderId"] == order_id
        for return_line in return_order["lineItems"]
        if return_line["extLineItemNumber"] == line_item["extLineItemNumber"]
    )


def to_adobe_line_id(mpt_line_id: str) -> int:
    """
    Converts Marketplace Line id to integer by extracting sequencial part of the line id.

    Example: ALI-1234-1234-1234-0001 --> 1
    """
    return int(mpt_line_id.rsplit("-", maxsplit=1)[-1])


def join_phone_number(phone: dict) -> str:
    """
    Returns a phone number string from a Phone object.

    Args:
        phone (dict): A phone object

    Returns:
        str: a phone number string

    Example:
        {"prefix": "+34", "number": "123456"} -> +34123456
    """
    return f"{phone['prefix']}{phone['number']}" if phone else ""


def get_3yc_commitment_request(customer, *, is_recommitment=False):  # noqa: WPS114
    """
    Extract the commitment or recommitment request object from the customer object.

    Args:
        customer (dict): A customer object from which extract the commitment
        or recommitment request object.
        is_recommitment (bool): If True it search for a recommitment request.
        Default to False.

    Returns:
        dict: The commitment or recommitment request object if
        it exists or an empty object.
    """
    recommitment_or_commitment = "recommitmentRequest" if is_recommitment else "commitmentRequest"
    benefit_3yc = find_first(  # noqa: WPS114
        lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
        customer.get("benefits", []),
        {},
    )

    return benefit_3yc.get(recommitment_or_commitment, {}) or {}


def get_3yc_recommitment_request(customer):  # noqa: WPS114
    """
    Extract the recommitment request object from the customer object.

    Args:
        customer (dict): A customer object from which extract the recommitment request object.

    Returns:
        dict: The recommitment request object if it exists or an empty object.
    """
    benefit_3yc = find_first(  # noqa: WPS114
        lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
        customer.get("benefits", []),
        {},
    )
    return benefit_3yc.get("recommitmentRequest", {}) or {}


def sanitize_company_name(company_name):
    """
    Replaces the characters not allowed by the Marketeplace platform.

    For spaces and trim the result string.

    Args:
        company_name (str): The Company Name string.

    Returns:
        str: The sanitized  Company Name string.
    """
    return REGEX_SANITIZE_COMPANY_NAME.sub(" ", company_name).strip()


def sanitize_first_last_name(first_last_name):
    """
    Replaces the characters not allowed by the Marketeplace platform.

    For spaces and trim the result string.

    Args:
        first_last_name (str): The First or Last Name string.

    Returns:
        str: The sanitized First or Last Name string.
    """
    return REGEX_SANITIZE_FIRST_LAST_NAME.sub(" ", first_last_name).strip()
