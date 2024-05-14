from adobe_vipm.utils import find_first


def get_actual_sku(items, sku):
    item = find_first(lambda item: item["offerId"].startswith(sku), items, default={})
    return item.get("offerId")


def get_item_to_return(items, line_number):
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


def get_3yc_commitment(customer):
    benefit_3yc = find_first(
        lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
        customer.get("benefits", []),
        {},
    )

    return benefit_3yc.get("commitment", {}) or {}


def get_3yc_commitment_request(customer, is_recommitment=False):
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
