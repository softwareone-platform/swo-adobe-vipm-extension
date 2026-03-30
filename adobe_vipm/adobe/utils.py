def find_first(func, iterable, default=None):
    """Find the first item in an iterable that matches a predicate."""
    return next(filter(func, iterable), default)


def get_partial_sku(full_sku: str) -> str:
    """Converts full Adobe SKU to partial one."""
    return full_sku[:10]


def map_by(key, items_list):
    """Maps any list of dicts by provided key."""
    return {item[key]: item for item in items_list}


def get_item_by_subcription_id(line_items, subscription_id):
    """Get the line item by subscription id."""
    return find_first(
        lambda line_item: line_item["subscriptionId"] == subscription_id,
        line_items,
        default={},
    )


def to_adobe_line_id(mpt_line_id: str) -> int:
    """Convert a Marketplace line id to the Adobe numeric line id."""
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


def get_3yc_commitment_request(customer, *, is_recommitment=False):
    """Extract the 3YC commitment request from an Adobe customer."""
    commitment_type = "recommitmentRequest" if is_recommitment else "commitmentRequest"
    benefit_3yc = find_first(
        lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
        customer.get("benefits", []),
        {},
    )
    return benefit_3yc.get(commitment_type, {}) or {}
