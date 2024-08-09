from adobe_vipm.adobe.constants import (
    REGEX_SANITIZE_COMPANY_NAME,
    REGEX_SANITIZE_FIRST_LAST_NAME,
)
from adobe_vipm.utils import find_first


def get_actual_sku(items, sku):
    """
    Get the full SKU from a list of items
    given the partial sku.

    Args:
        items (list): List of item to search.
        sku (str): The partial SKU to search in
        the list of item.

    Returns:
        str: The full SKU if found, None if not.
    """
    item = find_first(lambda item: item["offerId"].startswith(sku), items, default={})
    return item.get("offerId")


def get_item_to_return(items, line_number):
    """
    Get the item for which a RETURN order must be created
    based on the line number.

    Args:
        items (list): list of line items.
        line_number (str): number of the line as a string.

    Returns:
        dict: the item correspoding to the provided line_number.
    """
    return find_first(
        lambda adb_item: adb_item["extLineItemNumber"] == line_number,
        items,
    )


def to_adobe_line_id(mpt_line_id: str) -> int:
    """
    Converts Marketplace Line id to integer by extracting sequencial part of the line id
    Example: ALI-1234-1234-1234-0001 --> 1
    """
    return int(mpt_line_id.split("-")[-1])


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


def get_3yc_commitment(customer_or_transfer_preview):
    """
    Extract the commitment object from the customer object
    or from the transfer preview object.

    Args:
        customer_or_transfer_preview (dict): A customer object
        or a transfer preview object from which extract the commitment
        object.

    Returns:
        dict: The commitment object if it exists or an empty object.
    """
    benefit_3yc = find_first(
        lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
        customer_or_transfer_preview.get("benefits", []),
        {},
    )

    return benefit_3yc.get("commitment", {}) or {}


def get_3yc_commitment_request(customer, is_recommitment=False):
    """
    Extract the commitment or recommitment request object
    from the customer object.

    Args:
        customer (dict): A customer object from which extract the commitment
        or recommitment request object.
        is_recommitment (bool): If True it search for a recommitment request.
        Default to False.

    Returns:
        dict: The commitment or recommitment request object if
        it exists or an empty object.
    """
    benefit_3yc = find_first(
        lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
        customer.get("benefits", []),
        {},
    )

    return (
        benefit_3yc.get(
            "commitmentRequest" if not is_recommitment else "recommitmentRequest", {}
        )
        or {}
    )


def sanitize_company_name(company_name):
    """
    Replaces the characters not allowed by the Marketeplace platform for
    spaces and trim the result string.

    Args:
        company_name (str): The Company Name string.

    Returns:
        str: The sanitized  Company Name string.
    """
    return REGEX_SANITIZE_COMPANY_NAME.sub(" ", company_name).strip()


def sanitize_first_last_name(first_last_name):
    """
    Replaces the characters not allowed by the Marketeplace platform for
    spaces and trim the result string.

    Args:
        first_last_name (str): The First or Last Name string.

    Returns:
        str: The sanitized First or Last Name string.
    """
    return REGEX_SANITIZE_FIRST_LAST_NAME.sub(" ", first_last_name).strip()
