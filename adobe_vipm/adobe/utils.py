import datetime as dt

from adobe_vipm.adobe.constants import (
    REGEX_SANITIZE_COMPANY_NAME,
    REGEX_SANITIZE_FIRST_LAST_NAME,
    ThreeYearCommitmentStatus,
)


def find_first(func, iterable, default=None):
    """Find the first item in an iterable that matches a predicate."""
    return next(filter(func, iterable), default)


def get_partial_sku(full_sku: str) -> str:
    """Converts full Adobe SKU to partial one."""
    return full_sku[:10]


def map_by(key, items_list):
    """Maps any list of dicts by provided key."""
    return {item[key]: item for item in items_list}


def get_item_by_partial_sku(line_items, sku):
    """Get the full SKU from a list of line items given the partial sku."""
    return find_first(
        lambda line_item: line_item["offerId"].startswith(sku),
        line_items,
        default={},
    )


def get_deployment_id(source: dict) -> str | None:
    """
    Get the deploymentId parameter from the source.

    Args:
        source: MPT order or agreement.

    Returns:
        The value of the deploymentId parameter.
    """
    param = get_fulfillment_parameter(source, "deploymentId")
    return param.get("value")


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


def get_commitment_start_date(customer: dict) -> dt.date | None:
    """
    Retrieves 3YC commitment start date from Adobe customer.

    Returns start date only if commitment is commited or active and end date is somewhere in the
    future.

    Args:
        customer: Adobe customer.

    Returns:
        Commitment start date or None
    """
    commitment = get_3yc_commitment(customer)
    today = dt.datetime.now(tz=dt.UTC).date()

    if (
        commitment
        and commitment["status"]
        in {ThreeYearCommitmentStatus.COMMITTED, ThreeYearCommitmentStatus.ACTIVE}
        and dt.date.fromisoformat(commitment["endDate"]) >= today
    ):
        return dt.date.fromisoformat(commitment["startDate"])
    return None


def get_3yc_commitment(customer_or_transfer_preview: dict) -> dict:
    """
    Extract the commitment object from the customer object or from the transfer preview object.

    Args:
        customer_or_transfer_preview: A customer object
        or a transfer preview object from which extract the commitment
        object.

    Returns:
        The commitment object if it exists or an empty object.
    """
    benefit_3yc = find_first(
        lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
        customer_or_transfer_preview.get("benefits", []),
        {},
    )
    return benefit_3yc.get("commitment", {}) or {}


def sanitize_company_name(company_name):
    """Normalize company name according to Adobe constraints."""
    return REGEX_SANITIZE_COMPANY_NAME.sub(" ", company_name).strip()


def sanitize_first_last_name(first_last_name):
    """Normalize contact names according to Adobe constraints."""
    return REGEX_SANITIZE_FIRST_LAST_NAME.sub(" ", first_last_name).strip()
