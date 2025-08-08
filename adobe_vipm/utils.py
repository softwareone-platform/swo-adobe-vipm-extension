import datetime as dt

from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.constants import ThreeYearCommitmentStatus


def get_partial_sku(full_sku: str) -> str:
    """Converts full Adobe SKU to partial one."""
    return full_sku[:10]


def map_by(key, items_list):
    """Maps any list of dicts by provided key."""
    return {item[key]: item for item in items_list}


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
