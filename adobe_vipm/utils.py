from datetime import date

from adobe_vipm.adobe.constants import ThreeYearCommitmentStatus


def find_first(func, iterable, default=None):
    return next(filter(func, iterable), default)


def get_partial_sku(full_sku):
    return full_sku[:10]


def map_by(key, items_list):
    return {item[key]: item for item in items_list}


def get_commitment_start_date(customer):
    commitment = get_3yc_commitment(customer)
    commitment_start_date = None
    if (
        commitment
        and commitment["status"]
        in (ThreeYearCommitmentStatus.COMMITTED, ThreeYearCommitmentStatus.ACTIVE)
        and date.fromisoformat(commitment["endDate"]) >= date.today()
    ):
        commitment_start_date = date.fromisoformat(commitment["startDate"])
    return commitment_start_date


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
