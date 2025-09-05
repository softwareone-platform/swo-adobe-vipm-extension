import logging

from django.conf import settings
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query
from mpt_extension_sdk.mpt_http.wrap_http_error import wrap_mpt_http_error

from adobe_vipm.adobe.constants import (
    ThreeYearCommitmentStatus,
)
from adobe_vipm.flows.constants import Param

logger = logging.getLogger(__name__)


def get_agreements_by_3yc_commitment_request_status(
    mpt_client: MPTClient,
    *,
    is_recommitment: bool,
) -> list[dict]:
    """
    Retrieves active agreements having 3YC parameter enabled and 3YC status Requested or Accepted.

    Args:
        mpt_client: MPT API Client.
        is_recommitment: True if filter by recommitment status, otherwise by commitment status.

    Returns:
        Agreements.
    """
    param_external_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS.value
    )
    request_type_param_ext_id = (
        Param.THREE_YC.value if not is_recommitment else Param.THREE_YC_RECOMMITMENT.value
    )
    request_type_param_phase = (
        Param.PHASE_ORDERING.value if not is_recommitment else Param.PHASE_FULFILLMENT.value
    )

    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{param_external_id}),"
        f"in(displayValue,({ThreeYearCommitmentStatus.REQUESTED},{ThreeYearCommitmentStatus.ACCEPTED}))"
        ")"
        ")"
    )
    request_3yc_condition = (
        f"any(parameters.{request_type_param_phase},and("
        f"eq(externalId,{request_type_param_ext_id}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    status_condition = "eq(status,Active)"
    product_condition = f"in(product.id,({','.join(settings.MPT_PRODUCTS_IDS)}))"

    rql_query = (
        f"and({status_condition},{enroll_status_condition},"
        f"{request_3yc_condition},{product_condition})&select=parameters"
    )
    return get_agreements_by_query(mpt_client, rql_query)


def get_agreements_by_3yc_enroll_status(
    mpt_client: MPTClient, enroll_statuses: list[str], status: str = "Active"
) -> list[str]:
    """
    Retrieves active agreements having 3YC parameter enabled with provided 3YC statuses.

    Args:
        mpt_client: MPT API Client.
        enroll_statuses: Required enroll statuses.
        status: Agreement status.

    Returns:
        Agreements.
    """
    param_condition = (
        f"any(parameters.fulfillment,"
        f"and(eq(externalId,3YCEnrollStatus),in(displayValue,({','.join(enroll_statuses)}))))"
    )
    status_condition = f"eq(status,{status})"

    rql_query = (
        f"and({status_condition},{param_condition})"
        "&select=lines,parameters,subscriptions,product,listing"
    )
    return get_agreements_by_query(mpt_client, rql_query)


# TODO: move to SDK before merge
@wrap_mpt_http_error
def create_asset(mpt_client, asset):
    """Create a new agreement subscription."""
    response = mpt_client.post("/commerce/assets", json=asset)
    response.raise_for_status()
    return response.json()


@wrap_mpt_http_error
def create_agreement_asset(mpt_client, asset):
    """Create a new agreement subscription."""
    response = mpt_client.post(
        "/commerce/assets",
        json=asset,
    )
    response.raise_for_status()
    return response.json()


@wrap_mpt_http_error
def get_agreement_asset_by_external_id(mpt_client, agreement_id, asset_external_id):
    """Retrieve an agreement asset by external ID."""
    response = mpt_client.get(
        f"/commerce/assets?eq(externalIds.vendor,{asset_external_id})"
        f"&eq(agreement.id,{agreement_id})"
        f"&eq(status,Active)"
        f"&select=agreement.id&limit=1"
    )

    response.raise_for_status()
    assets = response.json()
    return assets["data"][0] if assets["data"] else None


@wrap_mpt_http_error
def get_order_asset_by_external_id(mpt_client, order_id, asset_external_id):
    """Retrieve an order subscription by its external ID."""
    response = mpt_client.get(
        f"/commerce/orders/{order_id}/assets?eq(externalIds.vendor,{asset_external_id})&limit=1",
    )
    response.raise_for_status()
    assets = response.json()
    if assets["$meta"]["pagination"]["total"] == 1:
        return assets["data"][0]
    return None
